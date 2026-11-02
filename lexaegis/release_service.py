"""Compose formal-release contracts with live process identity and task actions.

Identity probes run before a business transaction; checks/permit transitions run
inside it. Evidence remains in the app's controlled storage, never in gateway.
"""
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import httpx
from . import formal_release as release
from .contracts import FormalReleasePolicy, OneTimeDispatchGrant, ReadinessCheck
from .evidence import EvidenceStore, EvidenceIntakeService
from .release_build import ValidationResults, build_manifest_identity_hash, readiness_for_context
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


def _readiness_for_request(repo, context, request_hash: str, *, mode="report_only"):
    """Project existing verified isolation evidence into the readiness contract."""
    checks: dict[str, ReadinessCheck] = {}
    records = []
    try:
        records = repo.list("isolation_receipt")
    except AttributeError:
        records = []
    manifest = context.get("build_manifest") if context else None
    manifest_hash = build_manifest_identity_hash(manifest) if manifest else ""
    matching = [row for row in records
                if row.get("request_hash") == request_hash and row.get("status") == "valid"
                and (not manifest or row.get("build_manifest_hash") == manifest_hash)]
    receipt = matching[-1] if matching else None
    if receipt:
        probe_pass = all(receipt.get(name) is True for name in (
            "api_no_egress", "worker_no_egress", "gateway_no_case_volume",
            "redteam_no_secrets", "benchmark_no_secrets"))
        common = {
            "artifact_ids": sorted(set((receipt.get("evidence_artifact_ids") or {}).values())),
            "source_kind": "manual_upload",
            "source_command": "",
            "environment": {"deployment": receipt.get("deployment_mode", "unknown")},
            "generated_at": receipt.get("generated_at") or now(),
            "valid_until": receipt.get("expires_at"),
            "redaction_profile": "manual",
        }
        checks["compose_isolation"] = ReadinessCheck(
            status="pass" if probe_pass else "fail", reason="五项 Compose 隔离探测" if probe_pass else "Compose 探测未全部通过", **common)
        checks["host_firewall"] = ReadinessCheck(
            status="pass" if receipt.get("host_firewall_evidence_hash") else "pending",
            reason="宿主机防火墙证据已绑定" if receipt.get("host_firewall_evidence_hash") else "缺少宿主机防火墙证据", **common)
        checks["supply_chain"] = ReadinessCheck(
            status="pass" if receipt.get("supply_chain_evidence_hash") else "pending",
            reason="供应链证据已绑定" if receipt.get("supply_chain_evidence_hash") else "缺少镜像供应链证据", **common)
    # A raw command-generated report can be bound only when it carries the
    # current commit/build/request tuple. Reading the controlled blob directly
    # avoids opening a nested database transaction while the release check is
    # already inside one.
    intake = (context or {}).get("evidence_intake")
    evidence_store = getattr(intake, "evidence_store", None)
    if evidence_store and manifest:
        for artifact_row in repo.list("evidence_artifact"):
            if artifact_row.get("template_kind") not in {
                "readiness_compose_isolation", "readiness_k8s_conformance",
                "readiness_host_firewall", "readiness_supply_chain",
            }:
                continue
            try:
                path = evidence_store._path_for_ref(artifact_row["storage_ref"])
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != artifact_row.get("content_hash"):
                    continue
                payload = json.loads(content.decode("utf-8"))
                check_id = payload.get("check_id")
                if check_id not in {"compose_isolation", "k8s_conformance", "host_firewall", "supply_chain"}:
                    continue
                if payload.get("status") != "pass":
                    continue
                if payload.get("source_commit") != manifest.source_commit:
                    continue
                if payload.get("build_manifest_hash") != manifest_hash:
                    continue
                if payload.get("request_hash") != request_hash:
                    continue
                if payload.get("image_digests") and payload.get("image_digests") != manifest.container_image_digests:
                    continue
                raw = ReadinessCheck(
                    status="pass", artifact_ids=[artifact_row["id"]],
                    source_kind=artifact_row.get("source_kind", "command_generated"),
                    source_command=artifact_row.get("source_command", ""),
                    environment=artifact_row.get("environment") or payload.get("environment") or {},
                    generated_at=artifact_row.get("created_at") or payload.get("generated_at") or now(),
                    valid_until=artifact_row.get("valid_until") or payload.get("valid_until"),
                    redaction_profile=artifact_row.get("redaction_profile", "synthetic-v1"),
                    reason=f"已绑定 {check_id} 工程证据",
                )
                checks[check_id] = raw
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                continue
    return readiness_for_context(
        {**(context or {}), "validation_results": ValidationResults(readiness=checks)},
        request_hash=request_hash,
        mode=mode,
    )


def status(repo, task, case, context):
    if not required(task):
        return {"state": "not_applicable", "reason": "非生产云端请求"}
    try:
        frozen, decision = evaluate(repo, task, case, context)
        readiness = _readiness_for_request(repo, context, frozen.request_hash, mode="report_only")
        return {"state": "eligible" if decision.approval_eligible else "blocked",
                "frozen_request": frozen.model_dump(mode="json"), "decision": decision.model_dump(mode="json"),
                "readiness": readiness.model_dump(mode="json")}
    except (ValueError, TypeError, KeyError) as exc:
        return {"state": "blocked", "reason": str(exc)}


def assert_allowed(repo, task, case, context, phase):
    if not required(task):
        return
    frozen, decision = evaluate(repo, task, case, context)
    readiness = _readiness_for_request(repo, context, frozen.request_hash, mode="enforced")
    if readiness.state != "eligible":
        raise ValueError("正式放行未满足：readiness 缺少构建、Compose、宿主机防火墙或供应链证据")
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
