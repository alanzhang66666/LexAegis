"""Content-addressed runtime packs derived from the repository labor draft.

Repository packs are read-only inputs.  Review and publication mutate only the
independent ``runtime_pack`` aggregate and never authorize a dispatch by
themselves.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .registry import validate_pack
from .util import audit, canonical, now


DEFAULT_SOURCE_PACK = Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json"
EXPECTED_PACK_ID = "labor"
EXPECTED_PACK_VERSION = "2.0.0-draft.3"
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
FIRST_RELEASE_SCOPE = {
    "case_id": "LA-001",
    "purpose": "R_fact_summary",
    "recipient": "D_DeepSeek_official_API",
}
RISK_WEIGHT_KEYS = frozenset({"entity", "density", "context", "combination", "cross_round"})
LAW_05_TEMPLATE_KINDS = frozenset({
    "法05",
    "法05_门5_规则发布法学签署",
    "法 05 · 门 5 · 劳动争议 V2 规则发布的法学签署",
})
PUBLICATION_EFFECT = "eligible_for_downstream_gates_only"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_LIFECYCLE_METADATA = frozenset({
    "content_hash",
    "status",
    "published_by",
    "published_at",
    "frozen_at",
    "retired_by",
    "retired_at",
    "retirement_reason",
    "replaced_by_runtime_pack_id",
    "replaces_runtime_pack_id",
    "dependent_invalidation",
})
_FROZEN_REQUEST_KINDS = ("frozen_formal_request", "frozen_request")
_SNAPSHOT_KINDS = ("gate_snapshot", "evidence_snapshot")
_RECEIPT_KINDS = ("gate_evidence_receipt",)
_UNCLAIMED_GRANT_STATES = frozenset({"pending", "issued", "reserved"})
_PENDING_INTENT_STATES = frozenset({"pending", "queued", "reserved"})
_CLAIMED_REQUEST_STATES = frozenset({
    "claimed",
    "sending",
    "complete",
    "unknown",
    "consumed",
    "consumed_complete",
    "consumed_unknown",
    "failed_before_disclosure",
})


def _sha256_ref(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _read_artifact(path: Path, label: str) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}必须是本机普通文件")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"{label}为空或超过20MB")
    return path.read_bytes()


def _read_json_artifact(path: Path, label: str) -> tuple[bytes, Any]:
    content = _read_artifact(path, label)
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}不是有效UTF-8 JSON") from error
    return content, value


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any, *, prefixed: bool) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.removeprefix("sha256:") if prefixed else value
    if prefixed and not value.startswith("sha256:"):
        return False
    return _SHA256_RE.fullmatch(candidate) is not None


def runtime_pack_content_hash(runtime_pack: Mapping[str, Any]) -> str:
    """Hash frozen review content while allowing lifecycle status to change.

    Publication and retirement metadata are excluded so the hash reviewed under
    法05 remains verifiable throughout lifecycle transitions. Scope, risk
    weights, evidence, references, source provenance, and copied pack content
    remain covered.
    """
    content = {key: value for key, value in runtime_pack.items() if key not in _LIFECYCLE_METADATA}
    return _sha256_ref(canonical(content).encode("utf-8"))


def _validate_draft_address(runtime_pack: Mapping[str, Any]) -> None:
    if not _valid_sha256(runtime_pack.get("source_pack_hash"), prefixed=True):
        raise ValueError("运行库源pack哈希无效")
    if not _valid_sha256(runtime_pack.get("import_report_hash"), prefixed=True):
        raise ValueError("运行库导入报告哈希无效")
    draft_content = {
        "schema_version": runtime_pack.get("schema_version"),
        "source_pack_id": runtime_pack.get("source_pack_id"),
        "source_pack_hash": runtime_pack.get("source_pack_hash"),
        "import_report_hash": runtime_pack.get("import_report_hash"),
        "status": "draft",
        "dispatch_allowed": False,
        "pack": runtime_pack.get("pack"),
    }
    expected_hash = _sha256_ref(canonical(draft_content).encode("utf-8"))
    if runtime_pack.get("runtime_pack_hash") != expected_hash:
        raise ValueError("运行库draft内容地址无效")
    if runtime_pack.get("id") != "runtime-pack:" + expected_hash.removeprefix("sha256:"):
        raise ValueError("运行库ID与内容地址不一致")


def _resolve_law_05_evidence(repo, evidence_id: str) -> dict:
    if not _nonempty_text(evidence_id):
        raise ValueError("发布前必须引用既有法05证据")
    try:
        evidence = repo.get(evidence_id, "evidence_artifact")
    except KeyError as error:
        raise ValueError("发布前必须引用已登记的法05证据") from error
    if evidence.get("template_kind") not in LAW_05_TEMPLATE_KINDS:
        raise ValueError("review evidence必须来自既有法05模板")
    content_hash = evidence.get("content_hash")
    if not _valid_sha256(content_hash, prefixed=False):
        raise ValueError("法05证据内容哈希无效")
    if evidence.get("storage_ref") != f"sha256:{content_hash}":
        raise ValueError("法05证据内容地址与哈希不一致")
    return evidence


def _validate_reviewed_runtime_pack(runtime_pack: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    _validate_draft_address(runtime_pack)
    if runtime_pack.get("legal_status") != "reviewed":
        raise ValueError("运行库发布要求reviewed legal state")
    if runtime_pack.get("dispatch_allowed") is not True:
        raise ValueError("运行库发布要求显式dispatch_allowed=true")
    if runtime_pack.get("published_scope") != FIRST_RELEASE_SCOPE:
        raise ValueError("首发published_scope必须精确为LA-001 × R_fact_summary × D_DeepSeek_official_API")

    risk_weights = runtime_pack.get("risk_weights")
    if not isinstance(risk_weights, dict) or set(risk_weights) != RISK_WEIGHT_KEYS:
        raise ValueError("运行库发布要求精确冻结五类风险权重")
    if runtime_pack.get("risk_weights_frozen") is not True:
        raise ValueError("五类风险权重必须显式冻结")
    for value in risk_weights.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("五类风险权重必须是0到1之间的数值")

    references = runtime_pack.get("references")
    if not isinstance(references, list) or not references or any(not _nonempty_text(item) for item in references):
        raise ValueError("运行库发布前必须冻结非空法源引用")
    source_pack = runtime_pack.get("pack")
    if not isinstance(source_pack, dict) or not source_pack.get("legal_sources"):
        raise ValueError("运行库发布前必须保留法源记录")
    if not _nonempty_text(runtime_pack.get("review_record")):
        raise ValueError("运行库发布前必须具有法05审核记录")
    if not _nonempty_text(runtime_pack.get("reviewer")) or not _nonempty_text(runtime_pack.get("reviewed_at")):
        raise ValueError("运行库发布前必须具有具名审核人与审核时间")
    if runtime_pack.get("law_05_evidence_id") != evidence.get("id"):
        raise ValueError("运行库法05证据引用不一致")
    if runtime_pack.get("law_05_evidence_hash") != evidence.get("content_hash"):
        raise ValueError("运行库法05证据哈希不一致")
    if runtime_pack.get("publication_effect") != PUBLICATION_EFFECT:
        raise ValueError("运行库发布不得被标记为发送授权")
    content_hash = runtime_pack.get("content_hash")
    if not _valid_sha256(content_hash, prefixed=True):
        raise ValueError("运行库内容哈希无效")
    if content_hash != runtime_pack_content_hash(runtime_pack):
        raise ValueError("运行库内容哈希不匹配")


def create_runtime_pack_draft(repo, source_pack: Path, import_report: Path) -> dict:
    """Persist an independent, content-addressed runtime draft.

    The source and report hashes cover their exact bytes. The runtime address
    covers the immutable draft envelope and copied pack data, so equal inputs
    are idempotent while a changed source pack or import report derives a new
    record. Repository files are opened read-only and never rewritten.
    """
    source_bytes, raw_pack = _read_json_artifact(source_pack, "源pack")
    report_bytes, report = _read_json_artifact(import_report, "导入报告")
    if not isinstance(raw_pack, dict):
        raise ValueError("源pack必须是JSON对象")
    if not isinstance(report, dict):
        raise ValueError("导入报告必须是JSON对象")

    validate_pack(raw_pack)
    if raw_pack.get("id") != EXPECTED_PACK_ID or raw_pack.get("version") != EXPECTED_PACK_VERSION:
        raise ValueError("运行库draft只能从labor 2.0.0-draft.3派生")
    if raw_pack.get("status") != "draft" or raw_pack.get("dispatch_allowed") is not False:
        raise ValueError("仓库源pack必须保持draft且dispatch_allowed=false")

    source_pack_hash = _sha256_ref(source_bytes)
    import_report_hash = _sha256_ref(report_bytes)
    draft_content = {
        "schema_version": 1,
        "source_pack_id": f"pack:{EXPECTED_PACK_ID}:{EXPECTED_PACK_VERSION}",
        "source_pack_hash": source_pack_hash,
        "import_report_hash": import_report_hash,
        "status": "draft",
        "dispatch_allowed": False,
        "pack": raw_pack,
    }
    runtime_pack_hash = _sha256_ref(canonical(draft_content).encode("utf-8"))
    record_id = "runtime-pack:" + runtime_pack_hash.removeprefix("sha256:")

    for existing in repo.list("runtime_pack"):
        if existing.get("id") != record_id:
            continue
        expected = {**draft_content, "id": record_id, "runtime_pack_hash": runtime_pack_hash}
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ValueError("运行库内容地址冲突")
        return existing

    record = {
        "id": record_id,
        **draft_content,
        "runtime_pack_hash": runtime_pack_hash,
        "created_at": now(),
    }
    repo.put("runtime_pack", record)
    return record


def review_runtime_pack(
    repo,
    runtime_pack_id: str,
    *,
    actor: str,
    review_record: str,
    law_05_evidence_id: str,
    legal_status: str,
    dispatch_allowed: bool,
    published_scope: Mapping[str, str],
    risk_weights: Mapping[str, float],
    references: list[str],
) -> dict:
    """Freeze a draft's 法05 review inputs without publishing it.

    All publication prerequisites are validated together.  Failure occurs
    before persistence, leaving the draft blocked.  The resulting reviewed
    record is still non-dispatchable because G5 also requires ``published``.
    """
    if not _nonempty_text(actor):
        raise ValueError("运行库审核人不能为空")
    runtime_pack = repo.get(runtime_pack_id, "runtime_pack")
    if runtime_pack.get("status") != "draft":
        raise ValueError("只有运行库draft可以进入reviewed")
    _validate_draft_address(runtime_pack)
    evidence = _resolve_law_05_evidence(repo, law_05_evidence_id)

    reviewed = dict(runtime_pack)
    reviewed.update(
        status="reviewed",
        legal_status=legal_status,
        dispatch_allowed=dispatch_allowed,
        published_scope=dict(published_scope),
        risk_weights=dict(risk_weights),
        risk_weights_frozen=True,
        references=list(references),
        review_record=review_record,
        reviewer=actor.strip(),
        reviewed_at=now(),
        law_05_evidence_id=evidence["id"],
        law_05_evidence_hash=evidence["content_hash"],
        publication_effect=PUBLICATION_EFFECT,
    )
    reviewed["content_hash"] = runtime_pack_content_hash(reviewed)
    _validate_reviewed_runtime_pack(reviewed, evidence)
    repo.put("runtime_pack", reviewed)
    return reviewed


def _published_runtime_pack(repo, runtime_pack: Mapping[str, Any], actor: str) -> dict:
    if runtime_pack.get("status") != "reviewed":
        raise ValueError("只有reviewed运行库pack可以发布")
    evidence = _resolve_law_05_evidence(repo, runtime_pack.get("law_05_evidence_id", ""))
    _validate_reviewed_runtime_pack(runtime_pack, evidence)

    published = dict(runtime_pack)
    published.update(
        status="published",
        published_by=actor.strip(),
        published_at=now(),
        frozen_at=now(),
    )
    if published.get("content_hash") != runtime_pack_content_hash(published):
        raise ValueError("发布转换改变了已审核的运行库内容")
    repo.put("runtime_pack", published)
    return published


def publish_runtime_pack(repo, runtime_pack_id: str, *, actor: str) -> dict:
    """Publish one fully reviewed Runtime Pack for downstream gate evaluation.

    Publication does not create a release policy, G10 receipt, one-time grant,
    dispatch intent, gateway record, or provider attempt.  Those remain later,
    independent gates.
    """
    if not _nonempty_text(actor):
        raise ValueError("运行库发布人不能为空")
    runtime_pack = repo.get(runtime_pack_id, "runtime_pack")
    return _published_runtime_pack(repo, runtime_pack, actor)


def _record_state(record: Mapping[str, Any]) -> str:
    value = record.get("state", record.get("status", ""))
    return value if isinstance(value, str) else ""


def _claimed_request_keys(repo, requests: list[dict]) -> tuple[set[str], set[str]]:
    request_ids = {
        str(request.get("request_id") or request.get("id")): request.get("request_hash")
        for request in requests
    }
    claimed_hashes: set[str] = set()
    claimed_ids: set[str] = set()

    for request_id, request_hash in request_ids.items():
        request = next(item for item in requests if str(item.get("request_id") or item.get("id")) == request_id)
        if _record_state(request) in _CLAIMED_REQUEST_STATES:
            claimed_ids.add(request_id)
            if request_hash:
                claimed_hashes.add(str(request_hash))

    for grant in repo.list("one_time_dispatch_grant"):
        state = _record_state(grant)
        if state in {"claimed", "consumed"} or state not in _UNCLAIMED_GRANT_STATES | {"revoked", "expired"}:
            if grant.get("request_hash"):
                claimed_hashes.add(str(grant["request_hash"]))

    for gateway_record in repo.list("gateway_record"):
        if gateway_record.get("request_hash"):
            claimed_hashes.add(str(gateway_record["request_hash"]))
        if gateway_record.get("request_id"):
            claimed_ids.add(str(gateway_record["request_id"]))

    for request_id, request_hash in request_ids.items():
        if request_id in claimed_ids and request_hash:
            claimed_hashes.add(str(request_hash))
        if request_hash in claimed_hashes:
            claimed_ids.add(request_id)
    return claimed_hashes, claimed_ids


def _matching_requests(repo, runtime_pack_hash: str) -> list[tuple[str, dict]]:
    matches: list[tuple[str, dict]] = []
    for kind in _FROZEN_REQUEST_KINDS:
        for request in repo.list(kind):
            if request.get("runtime_pack_hash") == runtime_pack_hash:
                matches.append((kind, request))
    return matches


def invalidate_runtime_pack_dependents(
    repo,
    runtime_pack_hash: str,
    *,
    reason: str,
    actor: str,
    replacement_hash: str | None = None,
) -> dict:
    """Invalidate only unclaimed records bound to one former Runtime Pack hash.

    This is deliberately Pack-specific rather than the generic revocation graph
    planned by later tasks. Gateway records are read only to detect a claim and
    are never rewritten. Records are retained with terminal metadata; no
    aggregate is deleted.
    """
    if not _valid_sha256(runtime_pack_hash, prefixed=True):
        raise ValueError("待失效的运行库hash无效")
    if not _nonempty_text(reason) or not _nonempty_text(actor):
        raise ValueError("运行库失效传播要求具名操作者和原因")
    if replacement_hash is not None:
        if not _valid_sha256(replacement_hash, prefixed=True) or replacement_hash == runtime_pack_hash:
            raise ValueError("替换运行库hash必须有效且不同于旧hash")

    matches = _matching_requests(repo, runtime_pack_hash)
    requests = [record for _, record in matches]
    claimed_hashes, claimed_ids = _claimed_request_keys(repo, requests)
    invalidated_at = now()
    affected_hashes = {
        str(request["request_hash"])
        for request in requests
        if request.get("request_hash")
        and str(request["request_hash"]) not in claimed_hashes
        and str(request.get("request_id") or request.get("id")) not in claimed_ids
    }
    report = {
        "runtime_pack_hash": runtime_pack_hash,
        "replacement_hash": replacement_hash,
        "reason": reason.strip(),
        "invalidated_at": invalidated_at,
        "request_ids": [],
        "snapshot_ids": [],
        "receipt_ids": [],
        "intent_ids": [],
        "grant_ids": [],
        "preserved_claimed_request_ids": sorted(claimed_ids),
    }

    for kind, request in matches:
        request_hash = str(request.get("request_hash", ""))
        request_id = str(request.get("request_id") or request.get("id"))
        if request_hash not in affected_hashes or request.get("invalidation_status") == "invalidated":
            continue
        updated = dict(request)
        updated.update(
            invalidation_status="invalidated",
            invalidated_at=invalidated_at,
            invalidation_reason=reason.strip(),
            invalidated_runtime_pack_hash=runtime_pack_hash,
            replacement_runtime_pack_hash=replacement_hash,
        )
        repo.put(kind, updated)
        report["request_ids"].append(request_id)

    for kind in _SNAPSHOT_KINDS:
        for snapshot in repo.list(kind):
            if snapshot.get("request_hash") not in affected_hashes or snapshot.get("status") == "invalidated":
                continue
            updated = dict(snapshot)
            updated.update(
                status="invalidated",
                approval_eligible=False,
                dispatch_allowed=False,
                invalidated_at=invalidated_at,
                invalidation_reason=reason.strip(),
            )
            repo.put(kind, updated)
            report["snapshot_ids"].append(str(updated["id"]))

    for kind in _RECEIPT_KINDS:
        for receipt in repo.list(kind):
            if receipt.get("request_hash") not in affected_hashes or receipt.get("revoked_at"):
                continue
            updated = dict(receipt)
            updated.update(revoked_at=invalidated_at, revocation_reason=reason.strip())
            repo.put(kind, updated)
            report["receipt_ids"].append(str(updated["id"]))

    for intent in repo.list("dispatch_intent"):
        if intent.get("request_hash") not in affected_hashes or _record_state(intent) not in _PENDING_INTENT_STATES:
            continue
        updated = dict(intent)
        state_field = "state" if "state" in updated else "status"
        updated[state_field] = "cancelled"
        updated.update(cancelled_at=invalidated_at, cancellation_reason=reason.strip())
        repo.put("dispatch_intent", updated)
        report["intent_ids"].append(str(updated["id"]))

    for grant in repo.list("one_time_dispatch_grant"):
        if grant.get("request_hash") not in affected_hashes or _record_state(grant) not in _UNCLAIMED_GRANT_STATES:
            continue
        updated = dict(grant)
        state_field = "state" if "state" in updated else "status"
        updated[state_field] = "revoked"
        updated.update(revoked_at=invalidated_at, revocation_reason=reason.strip())
        repo.put("one_time_dispatch_grant", updated)
        report["grant_ids"].append(str(updated["id"]))

    for key in ("request_ids", "snapshot_ids", "receipt_ids", "intent_ids", "grant_ids"):
        report[key].sort()
    audit(
        repo,
        "formal-release",
        "runtime_pack_dependents_invalidated",
        actor=actor.strip(),
        runtime_pack_hash=runtime_pack_hash,
        replacement_hash=replacement_hash,
        reason_code=reason.strip(),
        affected_request_hashes=sorted(affected_hashes),
        counts={key: len(report[key]) for key in ("request_ids", "snapshot_ids", "receipt_ids", "intent_ids", "grant_ids")},
    )
    return report


def retire_runtime_pack(
    repo,
    runtime_pack_id: str,
    *,
    actor: str,
    reason: str = "runtime_pack_retired",
    replacement_hash: str | None = None,
    replaced_by_runtime_pack_id: str | None = None,
) -> dict:
    """Retire a published Runtime Pack and synchronously void unclaimed dependents."""
    if not _nonempty_text(actor) or not _nonempty_text(reason):
        raise ValueError("运行库retire要求具名操作者和原因")
    runtime_pack = repo.get(runtime_pack_id, "runtime_pack")
    if runtime_pack.get("status") != "published":
        raise ValueError("只有published运行库pack可以retire")
    evidence = _resolve_law_05_evidence(repo, runtime_pack.get("law_05_evidence_id", ""))
    _validate_reviewed_runtime_pack(runtime_pack, evidence)

    report = invalidate_runtime_pack_dependents(
        repo,
        runtime_pack["runtime_pack_hash"],
        reason=reason,
        actor=actor,
        replacement_hash=replacement_hash,
    )
    retired = dict(runtime_pack)
    retired.update(
        status="retired",
        dispatch_allowed=False,
        retired_by=actor.strip(),
        retired_at=now(),
        retirement_reason=reason.strip(),
        replaced_by_runtime_pack_id=replaced_by_runtime_pack_id,
        dependent_invalidation=report,
    )
    repo.put("runtime_pack", retired)
    audit(
        repo,
        "formal-release",
        "runtime_pack_retired",
        actor=actor.strip(),
        runtime_pack_id=runtime_pack_id,
        runtime_pack_hash=runtime_pack["runtime_pack_hash"],
        replacement_hash=replacement_hash,
        reason_code=reason.strip(),
    )
    return retired


def replace_runtime_pack(
    repo,
    current_runtime_pack_id: str,
    replacement_runtime_pack_id: str,
    *,
    actor: str,
    reason: str = "runtime_pack_hash_changed",
) -> dict:
    """Atomically publish a changed hash and retire the formerly bound pack."""
    if current_runtime_pack_id == replacement_runtime_pack_id:
        raise ValueError("替换运行库pack必须使用不同内容地址")
    if not _nonempty_text(actor) or not _nonempty_text(reason):
        raise ValueError("运行库change要求具名操作者和原因")
    current = repo.get(current_runtime_pack_id, "runtime_pack")
    if current.get("status") != "published":
        raise ValueError("只有published运行库pack可以被替换")
    replacement = repo.get(replacement_runtime_pack_id, "runtime_pack")
    if replacement.get("runtime_pack_hash") == current.get("runtime_pack_hash"):
        raise ValueError("替换运行库hash必须不同于旧hash")
    if replacement.get("status") == "reviewed":
        replacement = _published_runtime_pack(repo, replacement, actor)
    elif replacement.get("status") == "published":
        evidence = _resolve_law_05_evidence(repo, replacement.get("law_05_evidence_id", ""))
        _validate_reviewed_runtime_pack(replacement, evidence)
    else:
        raise ValueError("替换运行库pack必须是reviewed或published")

    retired = retire_runtime_pack(
        repo,
        current_runtime_pack_id,
        actor=actor,
        reason=reason,
        replacement_hash=replacement["runtime_pack_hash"],
        replaced_by_runtime_pack_id=replacement_runtime_pack_id,
    )
    replacement = dict(replacement)
    replacement.update(
        replaces_runtime_pack_id=current_runtime_pack_id,
        dependent_invalidation=retired["dependent_invalidation"],
    )
    repo.put("runtime_pack", replacement)
    audit(
        repo,
        "formal-release",
        "runtime_pack_hash_changed",
        actor=actor.strip(),
        former_runtime_pack_hash=current["runtime_pack_hash"],
        runtime_pack_hash=replacement["runtime_pack_hash"],
        reason_code=reason.strip(),
    )
    return replacement
