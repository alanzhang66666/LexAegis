"""Fail-closed, request-scoped formal release and one-time dispatch helpers.

This module deliberately performs no network I/O.  Mutating helpers accept the
repository yielded by ``Store.transaction`` so a caller can compose them with
its own task transition in one SQLite transaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Mapping, Sequence

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .contracts import (
    FormalReleasePolicy,
    FrozenFormalRequest,
    GateDecision,
    GateHit,
    ReleaseBuildManifest,
    OneTimeDispatchGrant,
)
from .release_build import build_manifest_identity_hash
from .util import audit, canonical, digest, uid


FIRST_RELEASE_TUPLE = {
    "case_id": "LA-001",
    "purpose": "R_fact_summary",
    "recipient": "D_DeepSeek_official_API",
}
_REQUIRED_GATES = ("G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10")
_G3_REQUIRED_LEGAL_TEMPLATES = frozenset({"法03", "法04"})
_RECEIPT_KIND = "gate_evidence_receipt"
_ACTION_KIND = "evidence_role_action"
_ARTIFACT_KIND = "evidence_artifact"
_HEX = set("0123456789abcdef")


class FormalReleaseError(ValueError):
    """A requested formal release transition is invalid or incomplete."""


def _time(value: str | datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: str | datetime | None = None) -> str:
    return _time(value).isoformat()


def _sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.removeprefix("sha256:")
    return len(raw) == 64 and set(raw) <= _HEX


def _identity_hashes(identities: Sequence[Any], manifest: ReleaseBuildManifest) -> bool:
    expected = build_manifest_identity_hash(manifest)
    if not identities:
        return False
    processes: set[str] = set()
    for identity in identities:
        data = identity.public() if hasattr(identity, "public") else dict(identity)
        if data.get("status") != "verified" or data.get("runtime_identity_hash") != expected:
            return False
        process = data.get("process")
        if process not in {"api", "worker", "gateway"} or process in processes:
            return False
        processes.add(process)
    return processes == {"api", "worker", "gateway"}


def _manifest(value: ReleaseBuildManifest | Mapping[str, Any]) -> ReleaseBuildManifest:
    result = value if isinstance(value, ReleaseBuildManifest) else ReleaseBuildManifest.model_validate(value)
    if result.status != "verified" or not result.worktree_clean:
        raise FormalReleaseError("release build manifest is not verified and clean")
    if not _sha256(build_manifest_identity_hash(result)):
        raise FormalReleaseError("release build identity is invalid")
    return result


def _current_documents(repo, case_id: str) -> dict[str, int]:
    return {str(item["id"]): int(item["version"]) for item in repo.list("document", case_id)}


def _provider(repo, request: Mapping[str, Any]) -> tuple[str, str]:
    dependencies = request.get("dependencies") or {}
    provider_id = dependencies.get("primary_provider_id") or dependencies.get("provider_id")
    if not provider_id:
        raise FormalReleaseError("formal request has no frozen primary provider profile")
    try:
        profile = repo.get(provider_id, "provider")
    except KeyError as exc:
        raise FormalReleaseError("formal provider profile is missing") from exc
    profile_hash = digest(profile)
    expected = dependencies.get("primary_provider_hash") or dependencies.get("provider_hash")
    if expected != profile_hash:
        raise FormalReleaseError("formal provider profile changed")
    if profile.get("status") != "reviewed":
        raise FormalReleaseError("formal provider profile is not reviewed")
    return provider_id, profile_hash


def _tuple_for_request(case: Mapping[str, Any], task: Mapping[str, Any], request: Mapping[str, Any], *, include_pilot: bool = True) -> dict[str, str]:
    """Build the live product scope; retain the named LA-001 pilot tuple."""
    dependencies = request.get("dependencies") or {}
    provider_id = dependencies.get("primary_provider_id") or dependencies.get("provider_id")
    if task.get("type") != "fact_summary":
        raise FormalReleaseError("formal release supports only the registered fact-summary task")
    purpose = "R_fact_summary"
    case_ref = case.get("reference_code") or case.get("id")
    target = request.get("target") or ""
    body_model = (request.get("body") or {}).get("model")
    if (include_pilot and case_ref == "LA-001" and purpose == "R_fact_summary"
            and target == "https://api.deepseek.com/v1/chat/completions"
            and body_model == "deepseek-chat"):
        return dict(FIRST_RELEASE_TUPLE)
    if not case_ref or not provider_id or purpose != "R_fact_summary":
        raise FormalReleaseError("request release scope requires a named case, R fact summary, and primary provider")
    return {"case_id": str(case_ref), "purpose": "R_fact_summary", "recipient": str(provider_id)}


def _published_scope_matches(scope: Mapping[str, Any], case: Mapping[str, Any], request_tuple: Mapping[str, str]) -> bool:
    if not isinstance(scope, Mapping) or any(not isinstance(value, str) or not value.strip()
                                              or value != value.strip() or "*" in value
                                              for value in scope.values()):
        return False
    if scope.get("purpose") != "R_fact_summary":
        return False
    recipient_matches = scope.get("recipient") == request_tuple.get("recipient")
    if not recipient_matches:
        return False
    if set(scope) == {"case_id", "purpose", "recipient"}:
        return scope["case_id"] in {case.get("id"), case.get("reference_code")}
    if set(scope) == {"domain", "purpose", "recipient"}:
        return bool(case.get("domain")) and scope["domain"] == case.get("domain")
    return False


def _g1_adoption_valid(repo, receipt: Mapping[str, Any], task: Mapping[str, Any], case: Mapping[str, Any],
                       request: Mapping[str, Any]) -> bool:
    """Bind 法01 adoption to the current, source-anchored disclosure facts."""
    adopted = receipt.get("adopted_fact_ids")
    if (not isinstance(adopted, list) or not adopted
            or any(not isinstance(item, str) or not item for item in adopted)
            or len(set(adopted)) != len(adopted)):
        return False
    snapshot = task.get("fact_snapshot") or []
    if not isinstance(snapshot, list):
        return False
    snapshot_by_id = {str(item.get("id")): item for item in snapshot if isinstance(item, Mapping) and item.get("id")}
    current_facts = {str(item.get("id")): item for item in repo.list("fact", str(case.get("id") or ""))
                     if item.get("id")}
    anchors = {
        str(block.get("id"))
        for document in repo.list("document", str(case.get("id") or ""))
        for block in ((document.get("ir") or {}).get("blocks") or [])
        if block.get("id")
    }
    for fact_id in adopted:
        key = str(fact_id)
        fact = current_facts.get(key)
        captured = snapshot_by_id.get(key)
        if not fact or not captured or fact.get("case_id") != case.get("id"):
            return False
        if fact.get("stale") or fact.get("confirmed") is not True:
            return False
        source_ids = fact.get("source_ids") or []
        captured_sources = captured.get("source_ids") or []
        if (not source_ids or any(not isinstance(item, str) or not item for item in source_ids)
                or set(source_ids) != set(captured_sources) or not set(source_ids) <= anchors):
            return False
    wire_facts = (request.get("wire_payload") or {}).get("facts")
    if not isinstance(wire_facts, list) or not wire_facts:
        return False
    decisions = {str(item.get("fact_id")): item for item in task.get("decisions") or []
                 if isinstance(item, Mapping) and item.get("fact_id")}
    wire_ids = []
    for item in wire_facts:
        if not isinstance(item, Mapping) or not item.get("id"):
            return False
        key = str(item["id"])
        decision = decisions.get(key)
        if key not in adopted or not decision or item.get("text") != decision.get("output"):
            return False
        if item.get("field") is not None and item.get("field") != decision.get("field"):
            return False
        wire_ids.append(key)
    return len(set(wire_ids)) == len(wire_ids)


def _g3_has_required_legal_reviews(receipts: Sequence[Mapping[str, Any]]) -> bool:
    """G3 requires both signed legal reviews; the engineering 技01 is auxiliary."""
    templates = {
        item.get("template_kind") for item in receipts
        if item.get("confirmed_role") == "legal_reviewer"
        and item.get("conclusion") == "pass"
        and item.get("template_kind") in _G3_REQUIRED_LEGAL_TEMPLATES
    }
    return templates == _G3_REQUIRED_LEGAL_TEMPLATES


def _policy_for_request(repo, request: FrozenFormalRequest) -> FormalReleasePolicy:
    request_policies = []
    for raw in repo.list("formal_release_policy"):
        policy = FormalReleasePolicy.model_validate(raw)
        if policy.scope_kind == "request" and policy.bound_request_hash == request.request_hash:
            request_policies.append(policy)
    if request_policies:
        if len(request_policies) != 1:
            raise FormalReleaseError("duplicate request-bound policies exist")
        return request_policies[0]
    first_acceptance = [FormalReleasePolicy.model_validate(raw) for raw in repo.list("formal_release_policy")
                        if raw.get("scope_kind", "first_acceptance") == "first_acceptance"
                        and raw.get("tuple") == request.tuple]
    if len(first_acceptance) != 1:
        raise FormalReleaseError("exactly one current request policy is required")
    return first_acceptance[0]


def freeze_request(
    repo,
    *,
    task: dict,
    case: dict,
    build_manifest: ReleaseBuildManifest | Mapping[str, Any],
    runtime_identities: Sequence[Any],
    at: str | datetime | None = None,
) -> FrozenFormalRequest:
    """Freeze the exact current cloud fact-summary request.

    No fields are accepted from a client projection; the snapshot is derived
    from persisted task, case, material, provider, rules and runtime records.
    """
    manifest = _manifest(build_manifest)
    if not _identity_hashes(runtime_identities, manifest):
        raise FormalReleaseError("API, worker and gateway build identities do not match")
    try:
        persisted_task = repo.get(str(task.get("id") or ""), "task")
        persisted_case = repo.get(str(case.get("id") or ""), "case")
    except KeyError as exc:
        raise FormalReleaseError("formal task or case is not persisted") from exc
    if persisted_task != task or persisted_case != case:
        raise FormalReleaseError("formal request must be derived from current persisted task and case")
    request = task.get("request")
    if not isinstance(request, dict) or task.get("status") not in {"review", "approved", "queued"}:
        raise FormalReleaseError("task has no current dispatchable request")
    if request.get("case_id") != case.get("id") or request.get("mode") != "formal":
        raise FormalReleaseError("formal request is outside its persisted case scope")
    if request.get("transport") != "cloud" or task.get("transport") != "cloud":
        raise FormalReleaseError("formal release requires cloud transport")
    dependencies = request.get("dependencies") or {}
    if task.get("request_hash") != digest(request):
        raise FormalReleaseError("task request hash does not match its current envelope")
    if (case.get("runtime_profile") != "production"
            or case.get("data_origin") in {"synthetic", "bundled_synthetic"}
            or dependencies.get("runtime_profile") != "production"
            or dependencies.get("data_origin") in {"synthetic", "bundled_synthetic"}
            or bool((request.get("policy") or {}).get("demo_exception"))):
        raise FormalReleaseError("formal release requires a production-profile customer-material request")
    request_policy = request.get("policy") or {}
    if request_policy.get("approved_for_dispatch") is not True or request_policy.get("risk_completion") != "complete":
        raise FormalReleaseError("formal request has not completed its current risk gate")
    if task.get("type") != "fact_summary":
        raise FormalReleaseError("formal release supports the registered R fact-summary task")
    target = request.get("target")
    body = request.get("body") or {}
    model = body.get("model")
    if not isinstance(target, str) or not target.startswith("https://") or not model:
        raise FormalReleaseError("formal request target or model is missing")
    if dependencies.get("standby_provider_id") or (dependencies.get("dual_slot") or {}).get("standby"):
        raise FormalReleaseError("first release allows the primary slot only")
    _provider(repo, request)
    try:
        pack = repo.get(str(task.get("pack_id") or ""), "pack")
    except KeyError as exc:
        raise FormalReleaseError("formal rule pack is missing") from exc
    if pack.get("status") != "published" or dependencies.get("pack_hash") != digest(pack):
        raise FormalReleaseError("formal rule pack is unpublished or stale")
    pack_scope = pack.get("published_scope") or {}
    scope_kind = pack.get("scope_kind", "first_acceptance")
    activations = [row for row in repo.list("runtime_pack_activation") if row.get("pack_id") == pack.get("id")]
    if len(activations) > 1:
        raise FormalReleaseError("active runtime pack provenance is ambiguous")
    if activations:
        try:
            runtime_pack = repo.get(activations[0].get("runtime_pack_id", ""), "runtime_pack")
        except KeyError as exc:
            raise FormalReleaseError("active runtime pack provenance is missing") from exc
        pack_scope = runtime_pack.get("published_scope") or pack_scope
        scope_kind = runtime_pack.get("scope_kind", scope_kind)
    if scope_kind == "first_acceptance":
        if pack_scope != FIRST_RELEASE_TUPLE or _tuple_for_request(case, task, request) != FIRST_RELEASE_TUPLE:
            raise FormalReleaseError("first-acceptance rule pack must retain the exact LA-001 × R × D scope")
    elif scope_kind == "request":
        provisional_tuple = _tuple_for_request(case, task, request, include_pilot=False)
        if not _published_scope_matches(pack_scope, case, provisional_tuple):
            raise FormalReleaseError("published rule scope does not cover the current case and primary provider")
    else:
        raise FormalReleaseError("unknown published rule scope kind")
    material_versions = dependencies.get("material_versions")
    if not isinstance(material_versions, dict) or material_versions != _current_documents(repo, case["id"]):
        raise FormalReleaseError("formal request material versions are stale or incomplete")
    pack_hash = dependencies.get("pack_hash")
    if not _sha256(pack_hash):
        raise FormalReleaseError("formal request has no content-addressed rule version")
    prompt = "\n".join(
        str(message.get("content", ""))
        for message in body.get("messages", [])
        if message.get("role") == "system"
    )
    if not prompt:
        raise FormalReleaseError("formal request has no frozen system prompt")
    wire_payload = request.get("wire_payload")
    if not isinstance(wire_payload, dict) or not wire_payload:
        raise FormalReleaseError("formal request has no wire payload")
    combination_hash = dependencies.get("combination_input_hash")
    if not _sha256(combination_hash):
        raise FormalReleaseError("formal request has no combination-input hash")
    protocols = dependencies.get("risk_protocol_hashes") or {}
    if not isinstance(protocols, dict) or not protocols or any(not _sha256(v) for v in protocols.values()):
        raise FormalReleaseError("formal request has no valid attack protocol hashes")
    _, provider_hash = _provider(repo, request)
    request_hash = str(task.get("request_hash") or "")
    request_policies = [FormalReleasePolicy.model_validate(raw) for raw in repo.list("formal_release_policy")
                        if raw.get("scope_kind") == "request" and raw.get("bound_request_hash") == request_hash]
    if request_policies:
        activations = [row for row in repo.list("runtime_pack_activation")
                       if row.get("pack_id") == pack.get("id")]
        if len(activations) != 1 or activations[0].get("artifact_sha256") != manifest.runtime_pack_hash:
            raise FormalReleaseError("request policy requires an active runtime pack matching the verified build artifact")
    derived_tuple = _tuple_for_request(case, task, request)
    if len(request_policies) > 1:
        raise FormalReleaseError("duplicate request-bound policies exist")
    if request_policies:
        selected_tuple = request_policies[0].tuple
        if selected_tuple != _tuple_for_request(case, task, request, include_pilot=False):
            raise FormalReleaseError("request policy tuple differs from the current case and primary provider")
    else:
        selected_tuple = derived_tuple
    if scope_kind == "first_acceptance" and selected_tuple != FIRST_RELEASE_TUPLE:
        raise FormalReleaseError("first-acceptance pack cannot authorize a product request scope")
    frozen_data = {
        "request_id": request.get("request_id") or task.get("request_id") or "",
        "tuple": selected_tuple,
        "wire_payload": wire_payload,
        "prompt": prompt,
        "target": target,
        "model": model,
        "provider_profile_hash": provider_hash,
        "runtime_pack_hash": pack_hash,
        "material_versions": material_versions,
        "rule_versions": {str(task.get("pack_id", "rules")): str(pack_hash)},
        "task_version": int(task.get("version") or 0),
        "mapping_version": int(dependencies.get("mapping_version") or 0),
        "ledger_version": int(dependencies.get("ledger_version", -1)),
        "combination_input_hash": combination_hash,
        "attack_protocol_hashes": protocols,
        "build_manifest_hash": build_manifest_identity_hash(manifest),
        "created_at": _iso(at),
    }
    if not frozen_data["request_id"] or frozen_data["task_version"] < 1 or frozen_data["mapping_version"] < 1 or frozen_data["ledger_version"] < 0:
        raise FormalReleaseError("formal request versions are incomplete")
    # Approval and gateway already use this digest over the ApprovedRequest
    # envelope. Keep that contract; the separate gate snapshot binds these
    # additional provenance fields without creating a second approval hash.
    frozen_data["request_hash"] = str(task.get("request_hash") or "")
    if not _sha256(frozen_data["request_hash"]):
        raise FormalReleaseError("task has no canonical request hash")
    frozen = FrozenFormalRequest.model_validate(frozen_data)
    return frozen


def install_policy(repo, policy: FormalReleasePolicy | Mapping[str, Any], *, actor: str, actor_role: str, at=None) -> FormalReleasePolicy:
    """Install a blocked pilot policy or one exact-request policy."""
    candidate = policy if isinstance(policy, FormalReleasePolicy) else FormalReleasePolicy.model_validate(policy)
    if candidate.maximum_dispatches != 1 or candidate.consumed_dispatches != 0:
        raise FormalReleaseError("formal policy must allow exactly one dispatch and start unconsumed")
    if candidate.scope_kind == "first_acceptance" and candidate.tuple != FIRST_RELEASE_TUPLE:
        raise FormalReleaseError("first-acceptance policy must use the exact LA-001 × R × D scope")
    if candidate.scope_kind == "request":
        matching_tasks = [item for item in repo.list("task")
                          if item.get("request_hash") == candidate.bound_request_hash
                          and item.get("request") and digest(item["request"]) == candidate.bound_request_hash]
        if len(matching_tasks) != 1:
            raise FormalReleaseError("request policy must bind one currently persisted request")
        task = matching_tasks[0]
        try:
            case = repo.get(task.get("case_id", ""), "case")
            expected_tuple = _tuple_for_request(case, task, task["request"], include_pilot=False)
        except (KeyError, FormalReleaseError) as exc:
            raise FormalReleaseError("request policy has no valid current task scope") from exc
        if candidate.tuple != expected_tuple:
            raise FormalReleaseError("request policy must match its case, purpose, and primary provider")
    if candidate.status != "blocked":
        raise FormalReleaseError("a new formal release policy must start blocked")
    if actor_role != "admin" or not actor.strip():
        raise FormalReleaseError("only a named administrator may install formal release policy")
    if not _sha256(candidate.build_manifest_hash) or not _sha256(candidate.allowed_provider_profile_hash):
        raise FormalReleaseError("policy requires explicit build and provider profile hashes")
    if not candidate.allowed_target.startswith("https://") or not candidate.allowed_model.strip():
        raise FormalReleaseError("policy requires an exact HTTPS target and model")
    existing = [FormalReleasePolicy.model_validate(raw) for raw in repo.list("formal_release_policy")]
    if any(item.id == candidate.id for item in existing):
        raise FormalReleaseError("formal release policy IDs are immutable")
    if candidate.scope_kind == "first_acceptance" and any(item.scope_kind == "first_acceptance" for item in existing):
        raise FormalReleaseError("the first-acceptance policy already exists")
    if candidate.scope_kind == "request" and any(
            item.scope_kind == "request" and item.bound_request_hash == candidate.bound_request_hash for item in existing):
        raise FormalReleaseError("a request policy already exists for this request hash")
    installed = candidate.model_copy(update={"installed_by": actor.strip(), "installed_at": _iso(at)})
    repo.put("formal_release_policy", installed.model_dump(mode="json"))
    audit(repo, installed.tuple["case_id"], "formal_release.policy_installed", policy_id=installed.id,
          scope_kind=installed.scope_kind, bound_request_hash=installed.bound_request_hash, actor=actor.strip())
    return installed


def _receipt_role_action(repo, receipt: Mapping[str, Any]) -> bool:
    expected = {
        "G10": (("approver",), "g10_approval"),
    }
    gate = receipt.get("gate_id")
    wanted = expected.get(gate)
    if not wanted:
        code = str(receipt.get("template_kind") or "")
        wanted = (("case_operator", "technical_reviewer"), "engineering_record") if code.startswith("技") else (("legal_reviewer",), "legal_confirmation")
    roles, action_name = wanted
    return any(
        action.get("receipt_id") == receipt.get("id")
        and action.get("actor") == receipt.get("confirmed_by")
        and action.get("role") == receipt.get("confirmed_role") in roles
        and action.get("action") == action_name
        for action in repo.list(_ACTION_KIND)
    )


def _receipt_live(repo, receipt: Mapping[str, Any], at, expected_tuple=FIRST_RELEASE_TUPLE) -> bool:
    try:
        return (
            receipt.get("conclusion") == "pass"
            and not receipt.get("revoked_at")
            and receipt.get("tuple") == expected_tuple
            and _time(receipt.get("valid_from")) <= _time(at) < _time(receipt.get("valid_until"))
            and _receipt_manifest_intact(repo, receipt)
            and _receipt_role_action(repo, receipt)
        )
    except (TypeError, ValueError, KeyError):
        return False


def _isolation_legal_confirmation(repo, isolation: Mapping[str, Any], request_hash: str, at, expected_tuple=FIRST_RELEASE_TUPLE) -> bool:
    """Require the isolation receipt to cite a live, named G8 legal review."""
    receipt_id = isolation.get("legal_confirmation_receipt_id")
    if not receipt_id:
        return False
    try:
        receipt = repo.get(str(receipt_id), _RECEIPT_KIND)
    except KeyError:
        return False
    return (
        receipt.get("gate_id") == "G8"
        and receipt.get("tuple") == expected_tuple
        and receipt.get("request_hash") == request_hash
        and receipt.get("confirmed_role") == "legal_reviewer"
        and _receipt_live(repo, receipt, at, expected_tuple)
    )


def _receipt_manifest_intact(repo, receipt: Mapping[str, Any]) -> bool:
    ids = receipt.get("evidence_artifact_ids") or []
    if not ids or not receipt.get("evidence_manifest_hash"):
        return False
    entries = []
    for artifact_id in ids:
        try:
            artifact = repo.get(artifact_id, _ARTIFACT_KIND)
        except KeyError:
            return False
        if not _sha256("sha256:" + str(artifact.get("content_hash", ""))):
            return False
        template = artifact.get("template_kind")
        import re
        match = re.search(r"(法|技)\s*0?(\d{1,2})", str(template or ""))
        normalized = f"{match.group(1)}{int(match.group(2)):02d}" if match else None
        entries.append({"id": artifact["id"], "content_hash": artifact["content_hash"],
                        "template_kind": normalized})
    entries.sort(key=lambda item: item["id"])
    expected = digest({
        "gate_id": receipt.get("gate_id"),
        "tuple": receipt.get("tuple"),
        "template_kind": receipt.get("template_kind"),
        "template_version": receipt.get("template_version"),
        "bound_versions": receipt.get("bound_versions") or {},
        "request_hash": receipt.get("request_hash"),
        "artifacts": entries,
        "technical_evidence_hash": receipt.get("technical_evidence_hash"),
        "technical_evidence_request_hash": receipt.get("technical_evidence_request_hash"),
    })
    return expected == receipt.get("evidence_manifest_hash")


def evaluate_release(
    repo,
    *,
    frozen: FrozenFormalRequest | Mapping[str, Any],
    task: dict,
    case: dict,
    build_manifest: ReleaseBuildManifest | Mapping[str, Any],
    runtime_identities: Sequence[Any],
    evidence_intake,
    at=None,
) -> GateDecision:
    """Return a fail-closed receipt-backed eligibility decision."""
    request = frozen if isinstance(frozen, FrozenFormalRequest) else FrozenFormalRequest.model_validate(frozen)
    hits: list[GateHit] = []
    try:
        manifest = _manifest(build_manifest)
        if not _identity_hashes(runtime_identities, manifest):
            raise FormalReleaseError("runtime build identities mismatch")
        if request.build_manifest_hash != build_manifest_identity_hash(manifest):
            raise FormalReleaseError("frozen request build manifest changed")
        current = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                                 runtime_identities=runtime_identities, at=request.created_at)
        if current.request_hash != request.request_hash or current.tuple != request.tuple:
            raise FormalReleaseError("current request differs from frozen request")
        if task.get("approval") and task["approval"].get("request_hash") != task.get("request_hash"):
            raise FormalReleaseError("approval does not bind current request")
        policy = _policy_for_request(repo, request)
        if policy.status not in {"blocked", "armed_once"} or policy.tuple != request.tuple:
            raise FormalReleaseError("formal release policy is unavailable")
        if policy.scope_kind == "request" and policy.bound_request_hash != request.request_hash:
            raise FormalReleaseError("request policy is bound to another request")
        if (policy.build_manifest_hash != request.build_manifest_hash or policy.allowed_target != request.target
                or policy.allowed_model != request.model or policy.allowed_provider_profile_hash != request.provider_profile_hash):
            raise FormalReleaseError("request is outside installed policy scope")
        if policy.consumed_dispatches >= 1:
            raise FormalReleaseError("single formal dispatch slot is already consumed")
        if policy.status == "armed_once" and (
            not policy.valid_from or not policy.valid_until
            or not (_time(policy.valid_from) <= _time(at) < _time(policy.valid_until))
        ):
            raise FormalReleaseError("scoped formal release policy is outside its validity period")
        if evidence_intake is None:
            raise FormalReleaseError("controlled evidence intake is required to verify artifact integrity")
        by_gate: dict[str, list[Any]] = {}
        expected_versions = {
            "materials": digest(request.material_versions),
            "rules": digest(request.rule_versions),
            "task": str(request.task_version),
            "mapping": str(request.mapping_version),
            "ledger": str(request.ledger_version),
            "combination": request.combination_input_hash,
        }
        # Resolve each receipt against its own exact version binding. The
        # service checks validity/revocation and verifies all referenced bytes
        # through the configured controlled EvidenceStore.
        for raw in repo.list(_RECEIPT_KIND):
            if raw.get("tuple") != request.tuple or raw.get("gate_id") not in _REQUIRED_GATES:
                continue
            if raw.get("request_hash") not in (None, request.request_hash):
                continue
            if raw.get("gate_id") in {"G1", "G2", "G3", "G5"} and raw.get("bound_versions") != expected_versions:
                continue
            try:
                resolved = evidence_intake.resolve_evidence(
                    request.tuple,
                    request_hash=request.request_hash if raw.get("gate_id") in {"G6", "G7", "G8", "G9", "G10"} else None,
                    bound_versions=raw.get("bound_versions") or {},
                    at=_time(at),
                )
            except (KeyError, ValueError, TypeError):
                continue
            matched = next((item for item in resolved if item.id == raw.get("id")), None)
            if matched is not None:
                data = matched.model_dump(mode="json") if hasattr(matched, "model_dump") else dict(matched)
                if matched.gate_id == "G1" and not _g1_adoption_valid(repo, data, task, case, task["request"]):
                    continue
                by_gate.setdefault(matched.gate_id, []).append(matched)
        for gate_id in _REQUIRED_GATES:
            valid = []
            for receipt in by_gate.get(gate_id, []):
                data = receipt.model_dump(mode="json") if hasattr(receipt, "model_dump") else dict(receipt)
                if (data.get("conclusion") == "pass" and data.get("request_hash") in (None, request.request_hash)
                        and _receipt_manifest_intact(repo, data) and _receipt_role_action(repo, data)):
                    valid.append(data)
            if gate_id == "G3" and not _g3_has_required_legal_reviews(valid):
                valid = []
            if not valid:
                hits.append(GateHit(gate_id=gate_id, status="pending", kind="verification",
                                    reason_code="formal_evidence_missing", message=f"{gate_id} 缺少当前请求有效签署证据"))
        isolation = [item for item in repo.list("isolation_receipt")
                     if item.get("request_hash") == request.request_hash
                     and item.get("tuple") == request.tuple
                     and item.get("build_manifest_hash") == request.build_manifest_hash
                     and item.get("status") == "valid" and item.get("deployment_mode") == "isolated"
                     and item.get("api_no_egress") and item.get("worker_no_egress")
                     and item.get("gateway_no_case_volume") and item.get("redteam_no_secrets")
                     and item.get("benchmark_no_secrets") and item.get("attested_by")]
        isolation = [item for item in isolation
                     if item.get("legal_confirmation_receipt_id")
                     and _sha256(item.get("deployment_identity_hash"))
                     and _sha256(item.get("compose_hash"))
                     and _sha256(item.get("probe_output_hash"))
                     and _sha256(item.get("host_firewall_evidence_hash"))
                     and _sha256(item.get("supply_chain_evidence_hash"))
                     and item.get("image_digests") == manifest.container_image_digests
                     and item.get("generated_at") and item.get("expires_at")
                     and _time(item["generated_at"]) <= _time(at) < _time(item["expires_at"])
                     and _isolation_legal_confirmation(repo, item, request.request_hash, at, request.tuple)]
        if not isolation:
            hits.append(GateHit(gate_id="G-product", status="pending", kind="engineering",
                                reason_code="isolation_receipt_missing", message="缺少绑定本次请求的有效隔离收据"))
    except (FormalReleaseError, ValidationError, KeyError, TypeError, ValueError) as exc:
        hits.append(GateHit(gate_id="G-product", status="fail", kind="engineering",
                            reason_code="formal_release_blocked", message=str(exc)))
    snapshot = {"request_hash": request.request_hash, "build_manifest_hash": request.build_manifest_hash,
                "hits": [hit.model_dump(mode="json") for hit in hits]}
    snapshot_hash = "sha256:" + hashlib.sha256(canonical(snapshot).encode()).hexdigest()
    allowed = not hits
    decision = GateDecision(phase="evaluate", request_hash=request.request_hash, hits=hits,
                        snapshot_hash=snapshot_hash, disposition="allowed" if allowed else "needs_verification",
                        system_readiness="ready" if allowed else "blocked", approval_eligible=allowed,
                        dispatch_allowed=False, evaluated_at=_iso(at))
    receipt_ids = sorted(
        receipt.get("id", "") for receipt in repo.list(_RECEIPT_KIND)
        if receipt.get("request_hash") == request.request_hash and receipt.get("id")
    )
    snapshot_id = "formal-release-snapshot-" + snapshot_hash.removeprefix("sha256:")
    repo.put("gate_snapshot", {
        "id": snapshot_id,
        "request_hash": request.request_hash,
        "snapshot_hash": snapshot_hash,
        "build_manifest_hash": request.build_manifest_hash,
        "evidence_receipt_ids": receipt_ids,
        "status": "current" if allowed else "blocked",
        "approval_eligible": allowed,
        "dispatch_allowed": False,
        "decision": decision.model_dump(mode="json"),
        "created_at": decision.evaluated_at,
    })
    return decision


def issue_grant(repo, *, frozen, decision, actor: str, actor_role: str, approval: Mapping[str, Any], at=None) -> OneTimeDispatchGrant:
    request = frozen if isinstance(frozen, FrozenFormalRequest) else FrozenFormalRequest.model_validate(frozen)
    result = decision if isinstance(decision, GateDecision) else GateDecision.model_validate(decision)
    if actor_role != "approver" or not actor.strip():
        raise FormalReleaseError("only a named approver may issue the one-time dispatch grant")
    if not result.approval_eligible or result.dispatch_allowed or result.request_hash != request.request_hash:
        raise FormalReleaseError("formal release decision is not eligible")
    snapshots = [item for item in repo.list("gate_snapshot")
                 if item.get("snapshot_hash") == result.snapshot_hash
                 and item.get("request_hash") == request.request_hash
                 and item.get("build_manifest_hash") == request.build_manifest_hash
                 and item.get("status") == "current" and item.get("approval_eligible") is True
                 and item.get("dispatch_allowed") is False]
    if not snapshots or not any(item.get("decision") == result.model_dump(mode="json") for item in snapshots):
        raise FormalReleaseError("a current persisted server-side release evaluation is required")
    try:
        if _time(snapshots[-1].get("created_at")) < _time(at) - timedelta(minutes=5):
            raise FormalReleaseError("formal release evaluation expired; reevaluate before grant")
    except (TypeError, ValueError):
        raise FormalReleaseError("formal release evaluation timestamp is invalid")
    expected_versions = {
        "materials": digest(request.material_versions),
        "rules": digest(request.rule_versions),
        "task": str(request.task_version),
        "mapping": str(request.mapping_version),
        "ledger": str(request.ledger_version),
        "combination": request.combination_input_hash,
    }
    current_receipts = []
    for item in repo.list(_RECEIPT_KIND):
        gate_id = item.get("gate_id")
        if gate_id not in _REQUIRED_GATES or item.get("tuple") != request.tuple:
            continue
        expected_hash = request.request_hash if gate_id in {"G6", "G7", "G8", "G9", "G10"} else None
        if item.get("request_hash") != expected_hash or not _receipt_live(repo, item, at, request.tuple):
            continue
        if gate_id == "G1":
            bound_tasks = [row for row in repo.list("task") if row.get("request_hash") == request.request_hash]
            if len(bound_tasks) != 1:
                continue
            try:
                bound_case = repo.get(bound_tasks[0].get("case_id", ""), "case")
            except KeyError:
                continue
            if not _g1_adoption_valid(repo, item, bound_tasks[0], bound_case, bound_tasks[0].get("request") or {}):
                continue
        if gate_id in {"G1", "G2", "G3", "G5"} and item.get("bound_versions") != expected_versions:
            continue
        current_receipts.append(item)
    g3_receipts = [item for item in current_receipts if item.get("gate_id") == "G3"]
    if ({item.get("gate_id") for item in current_receipts} != set(_REQUIRED_GATES)
            or not _g3_has_required_legal_reviews(g3_receipts)):
        raise FormalReleaseError("required evidence expired, was revoked, or changed after evaluation")
    if not any(item.get("request_hash") == request.request_hash
               and item.get("status") == "valid"
               and item.get("tuple") == request.tuple
               and item.get("build_manifest_hash") == request.build_manifest_hash
               and item.get("deployment_mode") == "isolated"
               and item.get("api_no_egress") and item.get("worker_no_egress")
               and item.get("gateway_no_case_volume") and item.get("redteam_no_secrets")
               and item.get("benchmark_no_secrets")
               and item.get("generated_at") and item.get("expires_at")
               and _time(item["generated_at"]) <= _time(at) < _time(item["expires_at"])
               and _isolation_legal_confirmation(repo, item, request.request_hash, at, request.tuple)
               for item in repo.list("isolation_receipt")):
        raise FormalReleaseError("isolation receipt expired or was revoked after evaluation")
    if approval.get("actor_role") != "approver" or not approval.get("actor") or approval.get("request_hash") != request.request_hash:
        raise FormalReleaseError("G10 approval does not bind this request")
    if approval.get("actor") != actor.strip():
        raise FormalReleaseError("grant issuer must match the named G10 approver")
    try:
        if _time(approval["expires_at"]) <= _time(at):
            raise FormalReleaseError("G10 approval expired")
    except (KeyError, ValueError, TypeError) as exc:
        raise FormalReleaseError("G10 approval expiry is invalid") from exc
    g10 = [receipt for receipt in repo.list(_RECEIPT_KIND)
           if receipt.get("gate_id") == "G10" and receipt.get("request_hash") == request.request_hash
           and receipt.get("conclusion") == "pass" and not receipt.get("revoked_at")
           and receipt.get("confirmed_by") == approval.get("actor")
           and receipt.get("confirmed_role") == "approver" and _receipt_role_action(repo, receipt)]
    if not g10:
        raise FormalReleaseError("named G10 role-action receipt is required")
    policy = _policy_for_request(repo, request)
    if policy.status != "blocked" or policy.consumed_dispatches != 0:
        raise FormalReleaseError("single release policy is not available")
    if policy.scope_kind == "request" and policy.bound_request_hash != request.request_hash:
        raise FormalReleaseError("request policy is bound to another request")
    stamp = _time(at)
    grant = OneTimeDispatchGrant(
        id=uid("grant"), nonce=secrets.token_urlsafe(32), request_hash=request.request_hash,
        gate_snapshot_hash=result.snapshot_hash, evidence_manifest_hash=digest([r["evidence_manifest_hash"] for r in repo.list(_RECEIPT_KIND) if r.get("request_hash") == request.request_hash]),
        build_manifest_hash=request.build_manifest_hash, release_policy_id=policy.id, tuple=request.tuple,
        actor=actor.strip(), actor_role="approver", issued_at=stamp.isoformat(),
        expires_at=(stamp + timedelta(minutes=30)).isoformat(), state="issued")
    armed = policy.model_copy(update={"status": "armed_once", "valid_from": stamp.isoformat(),
                                      "valid_until": grant.expires_at})
    repo.put("formal_release_policy", armed.model_dump(mode="json"))
    repo.put("one_time_dispatch_grant", grant.model_dump(mode="json"))
    audit(repo, request.tuple["case_id"], "formal_release.grant_issued", grant_id=grant.id,
          request_hash=request.request_hash, actor=actor.strip())
    return grant


def reserve_grant(repo, grant_id: str, *, task_id: str, request_hash: str, at=None) -> OneTimeDispatchGrant:
    grant = OneTimeDispatchGrant.model_validate(repo.get(grant_id, "one_time_dispatch_grant"))
    if grant.state != "issued" or grant.request_hash != request_hash or _time(grant.expires_at) <= _time(at):
        raise FormalReleaseError("grant is expired, already reserved, or bound to another request")
    if not any(task.get("id") == task_id and task.get("request_hash") == request_hash for task in repo.list("task")):
        raise FormalReleaseError("grant task and request binding are missing")
    reserved = grant.model_copy(update={"state": "reserved"})
    repo.put("one_time_dispatch_grant", reserved.model_dump(mode="json"))
    return reserved


def revoke_task_grants(repo, task_id: str, reason: str, *, actor: str, at=None) -> int:
    reason, actor = reason.strip(), actor.strip()
    if not reason or not actor:
        raise FormalReleaseError("grant revocation requires actor and reason")
    task = repo.get(task_id, "task")
    request_hash = task.get("request_hash")
    count = 0
    for raw in repo.list("one_time_dispatch_grant"):
        if raw.get("request_hash") != request_hash or raw.get("state") not in {"pending", "issued", "reserved"}:
            continue
        raw.update(state="revoked")
        repo.put("one_time_dispatch_grant", raw)
        count += 1
    # A pre-claim revocation releases only the still-unconsumed policy latch.
    # Once any durable claim exists, the single-dispatch budget is never reset.
    claimed = repo.conn.execute(
        text("SELECT 1 FROM formal_release_claims WHERE request_hash=:h LIMIT 1"),
        {"h": request_hash or ""},
    ).first()
    if count and not claimed:
        affected_policy_ids = {raw.get("release_policy_id") for raw in repo.list("one_time_dispatch_grant")
                               if raw.get("request_hash") == request_hash and raw.get("state") == "revoked"}
        for policy_raw in repo.list("formal_release_policy"):
            if policy_raw.get("status") != "armed_once" or policy_raw.get("consumed_dispatches") != 0:
                continue
            if policy_raw.get("id") not in affected_policy_ids:
                continue
            policy = FormalReleasePolicy.model_validate(policy_raw)
            repo.put("formal_release_policy", policy.model_copy(update={
                "status": "blocked", "valid_from": None, "valid_until": None,
            }).model_dump(mode="json"))
    audit(repo, task.get("case_id", ""), "formal_release.grants_revoked", task_id=task_id,
          count=count, reason=reason, actor=actor)
    return count


def gateway_claim(repo, *, frozen, approval: Mapping[str, Any], grant_id: str,
                  gateway_request_id: str, projection: Mapping[str, Any],
                  runtime_identity: Any, build_manifest, at=None) -> dict:
    """Persist the unique one-time claim before provider I/O; replays never resend."""
    request = frozen if isinstance(frozen, FrozenFormalRequest) else FrozenFormalRequest.model_validate(frozen)
    manifest = _manifest(build_manifest)
    identity = runtime_identity.public() if hasattr(runtime_identity, "public") else dict(runtime_identity or {})
    if (identity.get("process") != "gateway" or identity.get("status") != "verified"
            or identity.get("runtime_identity_hash") != build_manifest_identity_hash(manifest)):
        raise FormalReleaseError("gateway runtime identity does not match frozen build")
    if approval.get("request_hash") != request.request_hash or approval.get("actor_role") != "approver":
        raise FormalReleaseError("approval does not bind frozen request")
    if not approval.get("actor"):
        raise FormalReleaseError("approval has no named approver")
    try:
        if _time(approval.get("expires_at")) <= _time(at):
            raise FormalReleaseError("approval expired")
    except (TypeError, ValueError) as exc:
        raise FormalReleaseError("approval expiry is invalid") from exc
    if projection.get("request_hash") != request.request_hash or projection.get("target") != request.target or projection.get("model") != request.model:
        raise FormalReleaseError("gateway projection is outside frozen request scope")
    if gateway_request_id != request.request_id:
        raise FormalReleaseError("gateway request ID differs from frozen request")
    grant = OneTimeDispatchGrant.model_validate(repo.get(grant_id, "one_time_dispatch_grant"))
    if grant.state not in {"issued", "reserved", "claimed", "consumed"} or grant.request_hash != request.request_hash or grant.build_manifest_hash != request.build_manifest_hash or grant.tuple != request.tuple:
        raise FormalReleaseError("one-time grant is unavailable or out of scope")
    if grant.actor_role != "approver" or grant.actor != approval.get("actor"):
        raise FormalReleaseError("one-time grant actor does not match the named request approver")
    if _time(grant.expires_at) <= _time(at):
        raise FormalReleaseError("one-time grant expired")
    policies = {item.get("id"): item for item in repo.list("formal_release_policy")}
    if grant.release_policy_id not in policies:
        raise FormalReleaseError("release policy is missing")
    policy = FormalReleasePolicy.model_validate(policies[grant.release_policy_id])
    if (policy.status not in {"armed_once", "consumed"}
            or (policy.scope_kind == "request" and policy.bound_request_hash != request.request_hash)
            or (policy.scope_kind == "first_acceptance" and request.tuple != FIRST_RELEASE_TUPLE)
            or policy.tuple != request.tuple
            or policy.build_manifest_hash != request.build_manifest_hash
            or policy.allowed_target != request.target
            or policy.allowed_model != request.model
            or policy.allowed_provider_profile_hash != request.provider_profile_hash
            or policy.consumed_dispatches not in {0, 1}
            or not policy.valid_from or not policy.valid_until
            or not (_time(policy.valid_from) <= _time(at) < _time(policy.valid_until))):
        raise FormalReleaseError("scoped one-time policy is not armed")
    # A durable SQL unique row consumes the sole slot before network I/O.
    existing = repo.conn.execute(
        text("SELECT id, request_hash, grant_nonce, gateway_request_id FROM formal_release_claims WHERE request_hash=:h OR grant_nonce=:n OR gateway_request_id=:g"),
        {"h": request.request_hash, "n": grant.nonce, "g": gateway_request_id},
    ).mappings().first()
    if existing:
        if existing["request_hash"] == request.request_hash and existing["grant_nonce"] == grant.nonce and existing["gateway_request_id"] == gateway_request_id:
            try:
                known = repo.get(existing["id"], "formal_release_claim")
            except KeyError:
                known = {"id": existing["id"], "request_hash": request.request_hash, "state": "unknown"}
            return {**known, "replay": True}
        raise FormalReleaseError("formal release claim key collision")
    claim_id = uid("formal_claim")
    policy_slot = 1
    try:
        repo.conn.execute(
            text("INSERT INTO formal_release_claims(id,request_hash,grant_nonce,gateway_request_id,policy_id,policy_slot) VALUES(:id,:hash,:nonce,:request_id,:policy_id,:slot)"),
            {"id": claim_id, "hash": request.request_hash, "nonce": grant.nonce,
             "request_id": gateway_request_id, "policy_id": grant.release_policy_id, "slot": policy_slot},
        )
    except IntegrityError as exc:
        raise FormalReleaseError("formal release unique claim was already consumed") from exc
    claimed = grant.model_copy(update={"state": "claimed", "claimed_at": _iso(at), "gateway_attempt_id": gateway_request_id})
    repo.put("one_time_dispatch_grant", claimed.model_dump(mode="json"))
    policy = FormalReleasePolicy.model_validate(next(p for p in repo.list("formal_release_policy") if p["id"] == grant.release_policy_id))
    repo.put("formal_release_policy", policy.model_copy(update={"status": "consumed", "consumed_dispatches": 1}).model_dump(mode="json"))
    record = {"id": claim_id, "request_hash": request.request_hash, "grant_id": grant.id,
              "gateway_request_id": gateway_request_id, "state": "claimed", "created_at": _iso(at), "result": None}
    repo.put("formal_release_claim", record)
    audit(repo, request.tuple["case_id"], "formal_release.gateway_claimed", claim_id=claim_id,
          request_hash=request.request_hash, gateway_request_id=gateway_request_id)
    return {**record, "replay": False}


def complete_gateway_claim(repo, claim_id: str, outcome: Mapping[str, Any], *, at=None) -> dict:
    """Record terminal status; uncertain outcomes are consumed and never refunded."""
    record = repo.get(claim_id, "formal_release_claim")
    if record.get("state") != "claimed":
        return record
    status = outcome.get("status")
    if status not in {"complete", "unknown", "failed_before_disclosure"}:
        raise FormalReleaseError("gateway outcome must be terminal and recognized")
    record.update(state=status, completed_at=_iso(at), result_hash=digest(outcome),
                  error_code=str(outcome.get("error_code") or "")[:120])
    repo.put("formal_release_claim", record)
    grant = OneTimeDispatchGrant.model_validate(repo.get(record["grant_id"], "one_time_dispatch_grant"))
    repo.put("one_time_dispatch_grant", grant.model_copy(update={"state": "consumed"}).model_dump(mode="json"))
    audit(repo, grant.tuple["case_id"], "formal_release.gateway_completed", claim_id=claim_id, state=status)
    return record
