"""V2.2 §8 Support Registry (P3): which causes the product actually supports.

Separate from the Package Registry: a loadable or even validated package does
not make its cause supported. Support gates entry into the product loop
(case/task creation); formal dispatch stays governed by outbound_gate and the
product latch, both unchanged.
"""
from .contracts import SupportedCause, SUPPORT_STATUSES
from .util import now


class SupportRegistryError(ValueError):
    """Fail-closed support registry error."""


SUPPORT_KIND = "supported_cause"

# Statuses that allow a cause to enter the product loop at all.
_USABLE_STATUS = {"supported", "integration_only"}


def support_for(repo, cause_id):
    """The support record for a cause, or None."""
    for record in repo.list(SUPPORT_KIND):
        if record.get("cause_id") == cause_id:
            return record
    return None


def is_supported(repo, cause_id, environment):
    """Whether the cause may enter the product loop in this environment.

    ``supported`` requires the environment to be listed; ``integration_only``
    is usable only under the integration profile. Every other status
    (validation/unsupported/suspended) and absence of a record is unusable.
    """
    record = support_for(repo, cause_id)
    if not record:
        return False
    if record.get("status") == "supported":
        return environment in (record.get("environments") or [])
    if record.get("status") == "integration_only":
        return environment == "integration"
    return False


def assert_supported(repo, cause_id, environment):
    if not is_supported(repo, cause_id, environment):
        raise SupportRegistryError(
            f"案由 {cause_id} 未进入产品支持清单（环境 {environment}）")


def assert_task_supported(repo, cause_id, environment, pack, manifest_id, task_type):
    """Pack version, manifest and capability must all be covered by the
    support record. Fail-closed on any gap."""
    assert_supported(repo, cause_id, environment)
    record = support_for(repo, cause_id)
    pack_ids = record.get("pack_ids") or []
    if pack_ids and pack and pack.get("id") not in pack_ids:
        raise SupportRegistryError(
            f"案由包版本 {pack.get('id')} 未获支持（案由 {cause_id}）")
    manifest_ids = record.get("manifest_ids") or []
    if manifest_ids and manifest_id and manifest_id not in manifest_ids:
        raise SupportRegistryError(
            f"分包清单 {manifest_id} 未获支持（案由 {cause_id}）")
    capabilities = record.get("capabilities") or []
    if capabilities and f"R_{task_type}" not in capabilities:
        raise SupportRegistryError(
            f"能力 R_{task_type} 未获支持（案由 {cause_id}）")


def upsert_support(repo, fields, actor):
    """Register or update a support record. Referenced packs/manifests must
    exist — dangling references are rejected."""
    cause_id = fields.get("cause_id")
    if not cause_id:
        raise SupportRegistryError("缺少 cause_id")
    status = fields.get("status") or "validation"
    if status not in SUPPORT_STATUSES:
        raise SupportRegistryError(f"非法支持状态 {status}")
    for pack_id in fields.get("pack_ids") or []:
        try:
            repo.get(pack_id, "pack")
        except KeyError:
            raise SupportRegistryError(f"引用的案由包不存在: {pack_id}")
    for manifest_id in fields.get("manifest_ids") or []:
        try:
            repo.get(manifest_id, "domain_package_manifest")
        except KeyError:
            raise SupportRegistryError(f"引用的分包清单不存在: {manifest_id}")
    record_id = f"support:{cause_id}"
    existing = repo.list(SUPPORT_KIND)
    current = next((r for r in existing if r.get("id") == record_id), None)
    record = SupportedCause(
        id=record_id,
        cause_id=cause_id,
        status=status,
        environments=list(fields.get("environments") or []),
        pack_ids=list(fields.get("pack_ids") or []),
        manifest_ids=list(fields.get("manifest_ids") or []),
        capabilities=list(fields.get("capabilities") or []),
        jurisdiction=fields.get("jurisdiction"),
        notes=fields.get("notes"),
        version=int((current or {}).get("version", 0)) + 1,
        created_at=(current or {}).get("created_at") or now(),
        updated_at=now(),
        updated_by=actor,
    ).model_dump()
    repo.put(SUPPORT_KIND, record)
    return record


def extend_packs(repo, cause_id, pack_id):
    """Publishing/activating a pack of a supported cause is itself the vetting
    event — extend the allow-list to that version. No-op for unsupported
    causes (they stay unsupported until explicitly registered)."""
    record = support_for(repo, cause_id)
    if not record or record.get("status") != "supported":
        return None
    pack_ids = list(record.get("pack_ids") or [])
    if pack_id in pack_ids:
        return record
    pack_ids.append(pack_id)
    record["pack_ids"] = pack_ids
    record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = now()
    repo.put(SUPPORT_KIND, record)
    return record


def suspend(repo, cause_id, actor):
    """Suspend a supported cause: new work is rejected and in-flight tasks of
    that cause go stale (assert_current then blocks further progress)."""
    record = support_for(repo, cause_id)
    if not record:
        raise SupportRegistryError(f"案由 {cause_id} 无支持记录")
    if record.get("status") == "unsupported":
        raise SupportRegistryError(f"案由 {cause_id} 已是 unsupported")
    record["status"] = "suspended"
    record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = now()
    record["updated_by"] = actor
    repo.put(SUPPORT_KIND, record)
    _propagate_suspension(repo, cause_id)
    return record


def _propagate_suspension(repo, cause_id):
    from . import orchestrator
    case_ids = {
        c["id"] for c in repo.list("case") if c.get("domain") == cause_id
    }
    if not case_ids:
        return
    terminal = {"complete", "failed", "stopped", "rejected", "unknown",
                "stale", "sending", "queued"}
    for task in repo.list("task"):
        if task.get("case_id") not in case_ids or task.get("status") in terminal:
            continue
        task = dict(task)
        orchestrator.transition_task(
            repo, task, "stale", "STATE_TRANSITION",
            stale=True, actor="system:support_suspended")
        repo.put("task", task, task["case_id"])


# --- seeding -----------------------------------------------------------------

def seed_support(repo, supported_causes=("labor",)):
    """Declare the product's supported causes. Only ``labor`` is seeded:
    labor_dispute is the accepted business domain per V2.2; other loaded packs
    (e.g. contract_test) stay loadable-but-unsupported, which is the point of
    separating the two registries. Idempotent."""
    from .runtime_profile import PROFILES
    seeded = 0
    for cause_id in supported_causes:
        if support_for(repo, cause_id) is not None:
            continue
        packs = [p for p in repo.list("pack") if p.get("domain_id") == cause_id]
        manifests = [
            m for m in repo.list("domain_package_manifest")
            if m.get("cause_id") == cause_id
        ]
        task_ids = sorted({t for p in packs for t in (p.get("task_ids") or [])})
        record = SupportedCause(
            id=f"support:{cause_id}",
            cause_id=cause_id,
            status="supported",
            environments=list(PROFILES),
            pack_ids=[p["id"] for p in packs],
            manifest_ids=[m["id"] for m in manifests],
            capabilities=[f"R_{t}" for t in task_ids],
            notes="seed: labor_dispute 为 V2.2 声明的受支持案由；支持≠可外发",
            version=1,
            created_at=now(),
        ).model_dump()
        repo.put(SUPPORT_KIND, record)
        seeded += 1
    return seeded
