"""Data lifecycle: retention policy, case erasure, provider deletion requests.

Fail-closed by default: an object class without a configured retention day is
never auto-purged. PIPIA and processing records keep the statutory floor
(three years) whenever a limit is configured. The gateway ledger is never
touched — the provider-side copies are tracked as deletion requests because
this system cannot delete what the provider holds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .util import audit, now, uid

RETENTION_FIELDS = (
    "originals",        # uploaded source files under files/
    "mapping",          # case.mapping / mapping_entries / fact local values
    "frozen_payloads",  # disclosure ledger wire bodies (tombstone keeps hash)
    "audit",            # audit event bodies (tombstone keeps id/at/actor/event)
    "backups",          # *.bak / backup archives beside the store
    "pia_records",      # PIPIA / processing-record receipts
)

# PIPL art.55-56: impact-assessment and processing records kept at least
# three years. A configured limit below the floor is rejected outright.
PIA_MIN_DAYS = 3 * 365

CASE_SCOPED_KINDS = ("document", "fact", "task", "job", "disclosure")


def _parse_at(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp
    except (TypeError, ValueError):
        return None


def validate_policy(policy: dict) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("保留策略必须是对象")
    unknown = set(policy) - set(RETENTION_FIELDS)
    if unknown:
        raise ValueError("未知保留对象：" + "、".join(sorted(unknown)))
    cleaned = {}
    for field in RETENTION_FIELDS:
        days = policy.get(field)
        if days is None:
            cleaned[field] = None
            continue
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ValueError(f"{field} 的保留天数必须是正整数或 null")
        if field == "pia_records" and days < PIA_MIN_DAYS:
            raise ValueError("影响评估与处理记录依法至少保存三年，不能配置更短期限")
        cleaned[field] = days
    return cleaned


def resolve_policy(settings: dict | None) -> dict:
    raw = (settings or {}).get("retention")
    if raw is None:
        return {field: None for field in RETENTION_FIELDS}
    return validate_policy(raw)


def _expired(created_at: str | None, days: int, at) -> bool:
    stamp = _parse_at(created_at)
    if stamp is None:
        return False
    return stamp <= at - timedelta(days=days)


def _tombstone(repo, kind, record, fields):
    body = {key: record.get(key) for key in fields}
    body["purged_at"] = now()
    repo.put(kind, body, record.get("case_id") or "")


def sweep(store, root: Path, *, at=None) -> dict:
    """One-shot retention sweep; only purges classes the policy configures."""
    at = at or datetime.now(timezone.utc)
    root = Path(root)
    report = {"at": at.isoformat(), "policy": None, "purged": [], "skipped": []}
    with store.transaction() as repo:
        settings = repo.get("settings")
        policy = resolve_policy(settings)
        report["policy"] = policy
        for case in repo.list("case"):
            case_id = case["id"]
            if case.get("erased_at"):
                report["skipped"].append({"case_id": case_id, "reason": "already_erased"})
                continue
            if policy["originals"] is not None:
                for doc in repo.list("document", case_id):
                    if doc.get("purged_at") or not _expired(doc.get("created_at") or case.get("created_at"),
                                                           policy["originals"], at):
                        continue
                    path = root / "files" / (doc.get("path") or "")
                    if doc.get("path") and path.is_file():
                        path.unlink()
                    doc["purged_at"] = now()
                    doc["path"] = None
                    repo.put("document", doc, case_id)
                    report["purged"].append({"kind": "original", "id": doc["id"]})
            if policy["mapping"] is not None and _expired(case.get("created_at"), policy["mapping"], at):
                if case.get("mapping") or case.get("mapping_entries"):
                    case["mapping"] = {}
                    case["mapping_entries"] = []
                    case["mapping_purged_at"] = now()
                    repo.put("case", case)
                    report["purged"].append({"kind": "mapping", "id": case_id})
            if policy["frozen_payloads"] is not None:
                for record in repo.list("disclosure", case_id):
                    if record.get("purged_at") or not _expired(record.get("at") or record.get("created_at"),
                                                              policy["frozen_payloads"], at):
                        continue
                    _tombstone(repo, "disclosure", record,
                               ("id", "case_id", "request_hash", "ledger_version", "at"))
                    report["purged"].append({"kind": "frozen_payload", "id": record["id"]})
            if policy["audit"] is not None:
                for record in repo.list("audit", case_id):
                    if record.get("purged_at") or not _expired(record.get("at"), policy["audit"], at):
                        continue
                    _tombstone(repo, "audit", record, ("id", "at", "actor", "event"))
                    report["purged"].append({"kind": "audit", "id": record["id"]})
        if policy["backups"] is not None:
            for path in sorted(root.glob("*.bak")) + sorted(root.glob("*.zip")):
                stamp = _parse_at(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
                if stamp and _expired(stamp.isoformat(), policy["backups"], at):
                    path.unlink()
                    report["purged"].append({"kind": "backup", "id": path.name})
        if report["purged"]:
            audit(repo, "", "data.retention_swept", count=len(report["purged"]))
    return report


def erase_case(store, root: Path, case_id: str, *, actor: str, basis: str) -> dict:
    """Erase a case's personal content; keep a hash tombstone and audit trail.

    Refuses while any task is queued or sending — erasure must not hide an
    in-flight dispatch. The gateway ledger and audit events survive; the
    provider-side copies move to ``provider_deletion_request`` tracking.
    """
    if not (basis or "").strip():
        raise ValueError("删除必须给出处理依据")
    root = Path(root)
    with store.transaction() as repo:
        case = repo.get(case_id, "case")
        inflight = [t["id"] for t in repo.list("task", case_id)
                    if t.get("status") in {"queued", "sending"}]
        if inflight:
            raise ValueError("案件存在在途发送任务，不能删除")
        stats = {"files": 0, "records": 0}
        for doc in repo.list("document", case_id):
            path = root / "files" / (doc.get("path") or "")
            if doc.get("path") and path.is_file():
                path.unlink()
                stats["files"] += 1
        for kind in CASE_SCOPED_KINDS:
            for record in repo.list(kind, case_id):
                repo.delete(record["id"])
                stats["records"] += 1
        for kind in ("case_binding", "domain_runtime_snapshot", "domain_runtime_context",
                     "domain_context_version"):
            try:
                records = repo.list(kind)
            except Exception:
                continue
            for record in records:
                if record.get("case_id") == case_id:
                    repo.delete(record["id"])
        tombstone = {
            "id": case["id"], "name": case.get("name", "")[:120],
            "domain": case.get("domain"), "mode": case.get("mode"),
            "created_at": case.get("created_at"),
            "erased_at": now(), "erased_by": actor, "erase_basis": basis.strip(),
            "erased": True,
        }
        repo.put("case", tombstone)
        audit(repo, case_id, "case.erased", actor=actor, basis=basis.strip(),
              files_removed=stats["files"], records_removed=stats["records"])
    return {"case_id": case_id, "erased": True, **stats}


def record_provider_deletion(repo, *, provider_profile_id: str, actor: str,
                             request_hash: str | None = None, note: str = "") -> dict:
    provider = repo.get(provider_profile_id, "provider")
    record = {
        "id": uid("pdr"), "provider_profile_id": provider["id"],
        "provider_name": provider.get("name"),
        "request_hash": request_hash or None,
        "status": "pending", "requested_at": now(), "actor": actor,
        "acknowledged_at": None, "note": (note or "")[:500],
    }
    repo.put("provider_deletion_request", record)
    return record


def ack_provider_deletion(repo, request_id: str, *, actor: str) -> dict:
    record = repo.get(request_id, "provider_deletion_request")
    if record.get("status") != "pending":
        raise ValueError("该删除请求已确认或已撤销")
    record.update(status="acknowledged", acknowledged_at=now(), acknowledged_by=actor)
    repo.put("provider_deletion_request", record)
    return record
