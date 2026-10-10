"""Compose formal-release contracts with live process identity and task actions.

Identity probes run before a business transaction; checks/permit transitions run
inside it. Evidence remains in the app's controlled storage, never in gateway.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import httpx
from . import formal_release as release
from .gate_experience import summarize_gate_decision
from .gate_evidence_scope import proposed_dependencies
from .contracts import FormalReleasePolicy, OneTimeDispatchGrant
from .evidence import EvidenceStore, EvidenceIntakeService
from .runtime_identity import _load_manifest, runtime_identity
from .runtime_profile import current_profile
from .util import audit, now, sign


def collect_context(store, root, *, build_manifest=None, gateway_client=None):
    manifest, status = _load_manifest(build_manifest, None)
    context = {"build_manifest": manifest, "runtime_identities": [], "evidence_intake": None}
    if current_profile() != "production" or manifest is None or status != "verified":
        return context
    root = Path(root)
    identities = []
    for process in ("api", "worker"):
        try:
            identities.append(json.loads((root / f"{process}-runtime-identity.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            identities.append({"process": process, "status": "unconfigured"})
    client = gateway_client or httpx.Client(timeout=3, trust_env=False)
    try:
        response = client.get(os.getenv("LEX_GATEWAY_URL", "http://127.0.0.1:38766") + "/health",
                              headers={"X-Gateway-Signature": sign({"op": "health"}, os.getenv("LEX_GATEWAY_SECRET", ""))})
        response.raise_for_status()
        identities.append(response.json()["runtime_identity"])
    except Exception:
        identities.append({"process": "gateway", "status": "unconfigured"})
    finally:
        if gateway_client is None:
            client.close()
    context.update(runtime_identities=identities,
                   evidence_intake=EvidenceIntakeService(EvidenceStore(store, root / "release-evidence")))
    return context


def required(task):
    return current_profile() == "production" and task.get("transport") == "cloud"


def evaluate(repo, task, case, context):
    if not required(task):
        return None, None
    context = context or {}
    frozen = release.freeze_request(repo, task=task, case=case,
                                    build_manifest=context.get("build_manifest"),
                                    runtime_identities=context.get("runtime_identities", []))
    decision = release.evaluate_release(repo, frozen=frozen, task=task, case=case,
                                         build_manifest=context.get("build_manifest"),
                                         runtime_identities=context.get("runtime_identities", []),
                                         evidence_intake=context.get("evidence_intake"))
    return frozen, decision


def status(repo, task, case, context):
    if not required(task):
        return {"state": "not_applicable", "reason": "非生产云端请求"}
    try:
        frozen, decision = evaluate(repo, task, case, context)
        return {"state": "eligible" if decision.approval_eligible else "blocked",
                "frozen_request": frozen.model_dump(mode="json"), "decision": decision.model_dump(mode="json"),
                "experience": summarize_gate_decision(decision.model_dump(mode="json")),
                "dependency_diagnostics": proposed_dependencies(frozen)}
    except (ValueError, TypeError, KeyError) as exc:
        return {"state": "blocked", "reason": str(exc)}


def assert_allowed(repo, task, case, context, phase):
    if not required(task):
        return
    frozen, decision = evaluate(repo, task, case, context)
    if not decision.approval_eligible:
        raise ValueError("正式放行未满足：" + "；".join(hit.message for hit in decision.hits))
    if phase != "approve":
        bundle = task.get("formal_release") or {}
        grant = OneTimeDispatchGrant.model_validate(repo.get((bundle.get("grant") or {}).get("id", ""), "one_time_dispatch_grant"))
        if grant.state != ("issued" if phase == "enqueue" else "reserved"):
            raise ValueError("一次性许可未就绪或已撤销")
        try:
            expired = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        except (AttributeError, TypeError, ValueError):
            expired = True
        if grant.request_hash != task["request_hash"] or expired:
            raise ValueError("一次性许可不匹配或已过期")
        if (bundle.get("frozen_request") or {}).get("request_hash") != frozen.request_hash:
            raise ValueError("正式冻结请求不匹配")


def approve(repo, task, case, context):
    if not required(task):
        return
    frozen, decision = evaluate(repo, task, case, context)
    approval = task["approval"]
    grant = release.issue_grant(repo, frozen=frozen, decision=decision, actor=approval["actor"],
                                actor_role=approval["actor_role"], approval=approval)
    policy = repo.get(grant.release_policy_id, "formal_release_policy")
    task["formal_release"] = {"version": 1, "frozen_request": frozen.model_dump(mode="json"),
                              "policy": policy, "grant": grant.model_dump(mode="json"),
                              "projection": {"request_hash": frozen.request_hash, "target": frozen.target,
                                             "model": frozen.model, "provider_profile_hash": frozen.provider_profile_hash}}
    task["product_release"] = {"state": "armed_once", "grant_id": grant.id, "expires_at": grant.expires_at}


def reserve(repo, task):
    if not required(task):
        return
    grant = release.reserve_grant(repo, task["formal_release"]["grant"]["id"],
                                   task_id=task["id"], request_hash=task["request_hash"])
    task["formal_release"]["grant"] = grant.model_dump(mode="json")


def mark_sending(repo, task):
    """Consume the API-side latch at the durable sending boundary.

    The reserved grant projection in ``task.formal_release`` is intentionally
    left intact for the signed gateway request. The gateway has its own
    authoritative claim ledger; this mirror prevents API-side revocation or
    retry logic from refunding the release if the response is lost.
    """
    if not task.get("formal_release"):
        return
    grant_data = task["formal_release"].get("grant") or {}
    grant = OneTimeDispatchGrant.model_validate(repo.get(grant_data.get("id", ""), "one_time_dispatch_grant"))
    if grant.request_hash != task.get("request_hash") or grant.state != "reserved":
        raise ValueError("正式发送边界缺少匹配的已预留许可")
    policy = FormalReleasePolicy.model_validate(repo.get(grant.release_policy_id, "formal_release_policy"))
    if policy.status != "armed_once" or policy.consumed_dispatches != 0:
        raise ValueError("正式发送边界的一次性策略已被消费或撤销")
    stamp = now()
    repo.put("one_time_dispatch_grant", grant.model_copy(update={
        "state": "claimed", "claimed_at": stamp,
        "gateway_attempt_id": task.get("request", {}).get("request_id"),
    }).model_dump(mode="json"))
    repo.put("formal_release_policy", policy.model_copy(update={
        "status": "consumed", "consumed_dispatches": 1,
    }).model_dump(mode="json"))
    task["product_release"] = {"state": "sending", "grant_id": grant.id,
                               "request_hash": grant.request_hash, "consumed_at": stamp}
    audit(repo, task.get("case_id", ""), "formal_release.sending_claimed",
          task_id=task.get("id"), grant_id=grant.id, request_hash=grant.request_hash)


def mirror_outcome(repo, task, record):
    """Mirror a durable worker outcome without ever reopening the policy slot."""
    if not task.get("formal_release"):
        return
    grant_data = task["formal_release"].get("grant") or {}
    try:
        grant = OneTimeDispatchGrant.model_validate(repo.get(grant_data.get("id", ""), "one_time_dispatch_grant"))
    except (KeyError, ValueError):
        return
    # Only the durable worker sending marker proves that the request crossed
    # the non-retractable boundary. Pre-send rejection must not consume budget.
    if grant.state not in {"claimed", "consumed"}:
        return
    state = record.get("status") if isinstance(record, dict) else "unknown"
    terminal = state if state in {"complete", "unknown", "rejected", "failed"} else "unknown"
    if grant.state == "claimed":
        repo.put("one_time_dispatch_grant", grant.model_copy(update={"state": "consumed"}).model_dump(mode="json"))
    policy = FormalReleasePolicy.model_validate(repo.get(grant.release_policy_id, "formal_release_policy"))
    if policy.status != "consumed" or policy.consumed_dispatches != 1:
        repo.put("formal_release_policy", policy.model_copy(update={
            "status": "consumed", "consumed_dispatches": 1,
        }).model_dump(mode="json"))
    task["formal_release"]["grant"] = grant.model_copy(update={"state": "consumed"}).model_dump(mode="json")
    task["formal_release"]["policy"] = repo.get(grant.release_policy_id, "formal_release_policy")
    task["product_release"] = {"state": terminal, "grant_id": grant.id,
                               "request_hash": grant.request_hash, "consumed": True,
                               "outcome_at": now()}
    audit(repo, task.get("case_id", ""), "formal_release.outcome_mirrored",
          task_id=task.get("id"), grant_id=grant.id, outcome=terminal)


def revoke(repo, task, reason, actor="system"):
    if not task.get("formal_release"):
        return
    revoked = release.revoke_task_grants(repo, task["id"], reason, actor=actor)
    grant_data = task["formal_release"].get("grant") or {}
    try:
        current = OneTimeDispatchGrant.model_validate(
            repo.get(grant_data.get("id", ""), "one_time_dispatch_grant"))
    except (KeyError, ValueError):
        current = None
    if revoked:
        if current is not None:
            task["formal_release"]["grant"] = current.model_dump(mode="json")
            task["formal_release"]["policy"] = repo.get(current.release_policy_id, "formal_release_policy")
        task["product_release"] = {"state": "blocked", "reason": reason}
    elif current and current.state in {"claimed", "consumed"}:
        # A later case edit cannot make a dispatched request appear refundable.
        if not task.get("product_release") or task["product_release"].get("state") not in {
                "sending", "complete", "unknown", "rejected", "failed"}:
            task["product_release"] = {"state": "sending" if current.state == "claimed" else "consumed",
                                       "grant_id": current.id, "request_hash": current.request_hash,
                                       "consumed": True}
    else:
        task["product_release"] = {"state": "blocked", "reason": reason}
