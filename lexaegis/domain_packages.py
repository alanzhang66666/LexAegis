"""V2.2 Domain Package Set (P2): typed packages, manifest, lifecycle, revocation.

Packages are versioned, content-hashed records resolved by the domain runtime
into immutable snapshots. The monolithic DomainPackV2 stays authoritative for
disclosure/rules/gate consumption; packages currently bind the runtime only.
"""
import hmac
import os
from .contracts import (
    PLATFORM_API_VERSION,
    PACKAGE_TYPES,
    DomainPackage,
    DomainPackageManifest,
)
from .util import digest, now, sign, uid


class DomainPackageError(ValueError):
    """Fail-closed package lifecycle/resolution error."""


PACKAGE_KIND = "domain_package"
MANIFEST_KIND = "domain_package_manifest"

_TRANSITIONS = {
    "draft": {"validated", "revoked"},
    "validated": {"signed", "revoked"},
    "signed": {"published", "revoked"},
    "published": {"deprecated", "revoked"},
    "deprecated": {"revoked"},
}

_RESOLVABLE_STATUS = {"published": 0, "signed": 1, "validated": 2, "deprecated": 3}

_SIGNING_KEY_ENV = "LEX_PACKAGE_SIGNING_KEY"


# --- split a monolithic DomainPackV2 record into the V2.2 package set --------

def _binding_execution(task_id):
    try:
        from .task_engine import registered_tasks
        definition = registered_tasks().get(task_id) or {}
        return {
            "capability_id": f"R_{task_id}",
            "execution": definition.get("execution_type"),
            "task_definition_version": definition.get("version"),
        }
    except Exception:
        return {"capability_id": f"R_{task_id}", "execution": None}


def split_monolithic_pack(pack):
    """Deterministically split a DomainPackV2 record into package contents.

    Field groups mirror the interim snapshot sections so a manifest snapshot
    and an interim snapshot for the same pack carry the same meaning.
    """
    domain = pack.get("domain_id") or pack["id"]
    version = pack.get("version") or "0"
    provenance = {
        "source": "monolithic_pack_split",
        "source_pack_id": pack["id"],
        "source_pack_version": version,
        "source_pack_hash": digest(pack),
    }
    shared = {"cause_id": domain, "version": version, "provenance": provenance}
    sections = {
        "cause_pack": {
            "package_id": f"{domain}_cause_pack",
            "content": {
                "fact_schema": pack.get("fact_fields") or [],
                "task_templates": pack.get("task_field_matrix") or [],
                "rules": pack.get("rules") or [],
                "references": pack.get("references") or [],
                "mapper": pack.get("mapper") or {},
            },
        },
        "legal_rule_pack": {
            "package_id": f"{domain}_legal_rules",
            "content": {
                "sources": pack.get("legal_sources") or [],
                "immutable_relations": pack.get("immutable_relations") or [],
                "rules": pack.get("disclosure_rules") or [],
            },
            "effective_from": pack.get("effective_from"),
            "effective_to": pack.get("effective_until"),
        },
        "review_schema": {
            "package_id": f"{domain}_review_schema",
            "content": {
                "manual_review_conditions": pack.get("manual_review_conditions") or [],
                "sensitive_object_rules": pack.get("sensitive_object_rules") or [],
                "not_hard_ban_categories": pack.get("not_hard_ban_categories") or [],
                "conflict_checklist": pack.get("conflict_checklist") or [],
            },
        },
        "artifact_schema": {
            "package_id": f"{domain}_artifact_schema",
            "content": {"reply_templates": pack.get("reply_templates") or []},
        },
        "minimization_profile": {
            "package_id": f"{domain}_minimization",
            "content": {
                "direct_identifier_patterns": pack.get("direct_identifier_patterns") or [],
                "forbidden_terms": pack.get("forbidden_terms") or [],
            },
        },
        "gate_profile": {
            "package_id": f"{domain}_gate_profile",
            "content": {"risk_weights": pack.get("risk_weights") or {}},
        },
        "domain_acceptance_suite": {
            "package_id": f"{domain}_acceptance",
            "content": {"synthetic_cases": pack.get("synthetic_cases") or []},
        },
    }
    packages = []
    for package_type, spec in sections.items():
        packages.append({
            **shared,
            "package_type": package_type,
            "package_id": spec["package_id"],
            "platform_api": PLATFORM_API_VERSION,
            "jurisdiction": pack.get("jurisdiction"),
            "effective_from": spec.get("effective_from"),
            "effective_to": spec.get("effective_to"),
            "content": spec["content"],
        })
    for task_id in pack.get("task_ids") or []:
        packages.append({
            **shared,
            "package_type": "capability_binding",
            "package_id": f"{domain}_cap_{task_id}",
            "platform_api": PLATFORM_API_VERSION,
            "content": {
                "binding_id": f"{domain}_{task_id}_v1",
                "task_type": task_id,
                **_binding_execution(task_id),
                "provider_profile": None,
                "risk_protocols": pack.get("risk_protocols") or [],
            },
        })
    return packages


def _package_content_hash(body):
    return digest({
        "package_type": body["package_type"],
        "package_id": body["package_id"],
        "cause_id": body.get("cause_id"),
        "version": body["version"],
        "platform_api": body.get("platform_api"),
        "compatibility": body.get("compatibility") or {},
        "jurisdiction": body.get("jurisdiction"),
        "effective_from": body.get("effective_from"),
        "effective_to": body.get("effective_to"),
        "content": body.get("content") or {},
    })


def _manifest_content_hash(body):
    return digest({
        "cause_id": body["cause_id"],
        "version": body["version"],
        "package_refs": body.get("package_refs") or {},
        "platform_api_version": body.get("platform_api_version"),
    })


def build_manifest(cause_id, version, packages, platform_api_version=PLATFORM_API_VERSION):
    refs = {}
    for package in packages:
        refs.setdefault(package["package_type"], []).append({
            "package_id": package["package_id"],
            "version": package["version"],
            "id": package["id"],
            "content_hash": package["content_hash"],
        })
    return {
        "id": f"dpm:{cause_id}:{version}",
        "cause_id": cause_id,
        "version": version,
        "status": "draft",
        "package_refs": refs,
        "platform_api_version": platform_api_version,
        "created_at": now(),
    }


def register_package(repo, body):
    record = DomainPackage(
        id=body.get("id") or f"dpkg:{body['package_id']}:{body['version']}",
        status=body.get("status") or "draft",
        publisher=body.get("publisher"),
        supersedes=body.get("supersedes"),
        compatibility=body.get("compatibility") or {},
        provenance=body.get("provenance") or {},
        content=body.get("content") or {},
        content_hash=body.get("content_hash") or _package_content_hash(body),
        created_at=body.get("created_at") or now(),
        **{k: body.get(k) for k in (
            "package_type", "package_id", "cause_id", "version", "platform_api",
            "jurisdiction", "effective_from", "effective_to",
        )},
    ).model_dump()
    existing = None
    try:
        existing = repo.get(record["id"], PACKAGE_KIND)
    except KeyError:
        pass
    if existing is not None:
        if existing != record and existing.get("content_hash") != record["content_hash"]:
            raise DomainPackageError("同版本不可覆盖，请发布新版本")
        return existing
    return repo.put(PACKAGE_KIND, record)


def register_manifest(repo, manifest):
    record = DomainPackageManifest(
        **{**manifest, "content_hash": manifest.get("content_hash") or _manifest_content_hash(manifest)}
    ).model_dump()
    try:
        existing = repo.get(record["id"], MANIFEST_KIND)
        if existing.get("content_hash") != record["content_hash"]:
            raise DomainPackageError("同版本 manifest 不可覆盖，请发布新版本")
        return existing
    except KeyError:
        pass
    return repo.put(MANIFEST_KIND, record)


# --- lifecycle -----------------------------------------------------------------

def _signable_payload(record):
    return {
        "id": record["id"],
        "version": record["version"],
        "content_hash": record["content_hash"],
        "platform_api": record.get("platform_api") or record.get("platform_api_version"),
    }


def transition(repo, kind, ident, target, actor, signing_key=None):
    """Move a package or manifest along the V2.2 lifecycle. Fail-closed."""
    record = repo.get(ident, kind)
    current = record.get("status")
    if target not in _TRANSITIONS.get(current, set()):
        raise DomainPackageError(f"包生命周期转换无效：{current} -> {target}")
    record = dict(record)
    if target == "signed":
        key = signing_key or os.getenv(_SIGNING_KEY_ENV)
        if not key:
            raise DomainPackageError("签名需要签名密钥（LEX_PACKAGE_SIGNING_KEY 或显式传入）")
        record.update(
            signature=sign(_signable_payload(record), key),
            signed_by=actor,
            signed_at=now(),
        )
    elif target == "published" and not record.get("signature"):
        raise DomainPackageError("发布前必须先签名")
    elif target == "revoked":
        record.update(revoked_at=now(), revoked_by=actor)
    elif target == "deprecated":
        record.update(deprecated_at=now())
    record["status"] = target
    repo.put(kind, record)
    if target == "revoked":
        _propagate_revocation(repo, kind, record)
    return record


def _propagate_revocation(repo, kind, record):
    """Revocation: mark in-flight tasks whose snapshot resolves through this
    record as stale (assert_current then blocks further progress)."""
    from . import orchestrator
    manifest_ids = set()
    if kind == MANIFEST_KIND:
        manifest_ids.add(record["id"])
    else:
        for manifest in repo.list(MANIFEST_KIND):
            refs = manifest.get("package_refs") or {}
            if any(ref.get("id") == record["id"] for items in refs.values() for ref in items):
                manifest_ids.add(manifest["id"])
    if not manifest_ids:
        return
    snapshot_ids = {
        s["id"] for s in repo.list("domain_runtime_snapshot")
        if s.get("domain_package_manifest_id") in manifest_ids
    }
    if not snapshot_ids:
        return
    terminal = {"complete", "failed", "stopped", "rejected", "unknown", "stale", "sending", "queued"}
    for task in repo.list("task"):
        if task.get("domain_runtime_snapshot_id") in snapshot_ids and task.get("status") not in terminal:
            task = dict(task)
            orchestrator.transition_task(
                repo, task, "stale", "STATE_TRANSITION",
                stale=True, actor="system:package_revoked")
            repo.put("task", task, task["case_id"])


def manifests_for(repo, cause_id, source_pack_id=None):
    """All manifests for a cause (any status), optionally pinned to the
    monolithic pack they were split from."""
    candidates = [
        m for m in repo.list(MANIFEST_KIND)
        if m.get("cause_id") == cause_id
    ]
    if source_pack_id:
        candidates = [
            m for m in candidates
            if (m.get("provenance") or {}).get("source_pack_id") == source_pack_id
        ]
    return candidates


def find_manifest(repo, cause_id, source_pack_id=None):
    """Best resolvable manifest for a cause, or None. Draft/revoked skipped.

    When ``source_pack_id`` is given, manifests whose provenance points at a
    different source pack are excluded — the package set must describe the
    monolithic pack actually selected for the task.
    """
    candidates = [
        m for m in manifests_for(repo, cause_id, source_pack_id)
        if m.get("status") in _RESOLVABLE_STATUS
    ]
    if not candidates:
        return None
    best_rank = min(_RESOLVABLE_STATUS[m["status"]] for m in candidates)
    pool = [m for m in candidates if _RESOLVABLE_STATUS[m["status"]] == best_rank]
    return max(pool, key=lambda m: str(m.get("version") or ""))


# --- seeding --------------------------------------------------------------------

def seed_domain_packages(repo, validate_for=("labor",)):
    """Split every schema-2 non-retired pack into draft packages + manifest.

    Manifests for causes in ``validate_for`` are advanced to ``validated`` so
    the resolver can use them; nothing is signed or published without real
    evidence (repo packs stay drafts, dispatch stays blocked).
    """
    seeded = {"packages": 0, "manifests": 0}
    for pack in repo.list("pack"):
        if pack.get("schema_version") != 2 or pack.get("status") == "retired":
            continue
        cause_id = pack.get("domain_id") or pack["id"]
        manifest_id = f"dpm:{cause_id}:{pack.get('version')}"
        try:
            repo.get(manifest_id, MANIFEST_KIND)
            continue
        except KeyError:
            pass
        packages = []
        for body in split_monolithic_pack(pack):
            packages.append(register_package(repo, body))
        manifest = build_manifest(cause_id, pack.get("version"), packages)
        manifest["provenance"] = (packages[0] or {}).get("provenance") or {}
        register_manifest(repo, manifest)
        seeded["packages"] += len(packages)
        seeded["manifests"] += 1
        if cause_id in (validate_for or ()):
            for package in packages:
                transition(repo, PACKAGE_KIND, package["id"], "validated", actor="system:seed")
            transition(repo, MANIFEST_KIND, manifest_id, "validated", actor="system:seed")
    return seeded


# --- package distribution bundle (cloud -> edge delivery, P7 link) ---------

BUNDLE_SCHEMA = "lexaegis.package_bundle/v1"


def export_bundle(repo, manifest_id, signing_key=None):
    """Serialize a manifest and every package it references into a portable
    bundle. Refuses to export on content drift — a stale ref means the store
    no longer matches what was approved."""
    manifest = repo.get(manifest_id, MANIFEST_KIND)
    packages = []
    for refs in (manifest.get("package_refs") or {}).values():
        for ref in refs:
            package = repo.get(ref["id"], PACKAGE_KIND)
            if package.get("content_hash") != ref.get("content_hash"):
                raise DomainPackageError(
                    f"包 {ref['id']} 内容哈希漂移，拒绝导出")
            packages.append(package)
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "manifest": manifest,
        "packages": packages,
        "exported_at": now(),
    }
    bundle["bundle_hash"] = digest({
        "manifest_hash": manifest.get("content_hash"),
        "package_hashes": sorted(p.get("content_hash") for p in packages),
    })
    key = signing_key or os.getenv(_SIGNING_KEY_ENV)
    if key:
        bundle["signature"] = sign(
            {"bundle_hash": bundle["bundle_hash"], "manifest_id": manifest["id"]},
            key)
    return bundle


def verify_signature(record, key):
    """True only when the record carries an HMAC signature made with ``key``."""
    signature = record.get("signature")
    if not signature or not key:
        return False
    return hmac.compare_digest(signature, sign(_signable_payload(record), key))


def import_bundle(repo, bundle, signing_key=None, actor="system"):
    """Fail-closed import of an exported bundle.

    Structure, content hashes, manifest refs and platform_api are always
    verified. A record's lifecycle status is preserved only when its embedded
    signature verifies against ``signing_key`` (or LEX_PACKAGE_SIGNING_KEY);
    otherwise it is imported as ``draft``. ``published`` is never imported —
    publishing stays a local, separately evidenced decision."""
    if (bundle or {}).get("schema") != BUNDLE_SCHEMA:
        raise DomainPackageError("未知的包下发 bundle 结构")
    manifest = bundle.get("manifest") or {}
    packages = bundle.get("packages") or []
    if not manifest.get("id") or not packages:
        raise DomainPackageError("bundle 缺少 manifest 或包内容")
    expected = digest({
        "manifest_hash": manifest.get("content_hash"),
        "package_hashes": sorted(p.get("content_hash") for p in packages),
    })
    if bundle.get("bundle_hash") != expected:
        raise DomainPackageError("bundle_hash 与内容不符")
    key = signing_key or os.getenv(_SIGNING_KEY_ENV)
    bundle_signature = bundle.get("signature")
    if bundle_signature:
        expected_sig = sign(
            {"bundle_hash": bundle["bundle_hash"], "manifest_id": manifest["id"]}, key or "")
        if not key or not hmac.compare_digest(bundle_signature, expected_sig):
            raise DomainPackageError("bundle 签名无法验证")

    by_id = {p["id"]: p for p in packages}
    for package in packages:
        if package.get("package_type") not in PACKAGE_TYPES:
            raise DomainPackageError(f"未知 package_type: {package.get('package_type')}")
        if package.get("platform_api") != PLATFORM_API_VERSION:
            raise DomainPackageError(
                f"包 {package['id']} platform_api 与内核不符: {package.get('platform_api')}")
        if package.get("content_hash") != _package_content_hash(package):
            raise DomainPackageError(f"包 {package['id']} 内容哈希漂移")
    for refs in (manifest.get("package_refs") or {}).values():
        for ref in refs:
            package = by_id.get(ref.get("id"))
            if package is None:
                raise DomainPackageError(f"manifest 引用缺失的包: {ref.get('id')}")
            if package.get("content_hash") != ref.get("content_hash"):
                raise DomainPackageError(f"manifest 引用哈希不符: {ref.get('id')}")
    if manifest.get("platform_api_version") != PLATFORM_API_VERSION:
        raise DomainPackageError("manifest platform_api 与内核不符")
    if manifest.get("content_hash") != _manifest_content_hash(manifest):
        raise DomainPackageError("manifest 内容哈希漂移")

    imported = {"packages": 0, "manifest": manifest["id"], "downgraded": []}
    for package in packages:
        record = dict(package)
        status = record.get("status") or "draft"
        if status not in {"signed", "validated", "deprecated"} or not verify_signature(record, key):
            if status != "draft":
                imported["downgraded"].append(record["id"])
            record["status"] = "draft"
            record.pop("signature", None)
        register_package(repo, record)
        imported["packages"] += 1
    manifest_record = dict(manifest)
    m_status = manifest_record.get("status") or "draft"
    if m_status not in {"signed", "validated", "deprecated"} or not verify_signature(manifest_record, key):
        if m_status != "draft":
            imported["downgraded"].append(manifest_record["id"])
        manifest_record["status"] = "draft"
        manifest_record.pop("signature", None)
    register_manifest(repo, manifest_record)
    return imported

