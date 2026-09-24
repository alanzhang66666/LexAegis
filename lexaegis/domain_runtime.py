"""V2.2 runtime binding objects (P1): domain binding, context version,
runtime snapshot, and task step records.

These are dual-write records layered on the legacy aggregates: the existing
task/pack path remains authoritative. Snapshots are content-addressed and
immutable; each section hash currently derives from a field group of the
monolithic DomainPackV2 until the DomainPackageSet split (P2) lands.
"""
from .contracts import (
    PLATFORM_API_VERSION,
    CaseContextVersion,
    CaseDomainBinding,
    CloudTaskEnvelope,
    DomainRuntimeSnapshot,
    TaskStep,
)
from .util import digest, now, uid


class DomainRuntimeError(ValueError):
    """Fail-closed resolution error. Carries a stable machine code."""


# Interim section mapping over a monolithic DomainPackV2 record. The mapping
# is deterministic: section hash = digest of the listed field values. Replaced
# by per-package content hashes once the DomainPackageSet split lands.
_SNAPSHOT_SECTIONS = {
    "cause_pack_hash": ("fact_fields", "task_field_matrix", "rules", "references", "mapper"),
    "legal_rule_pack_hash": ("legal_sources", "immutable_relations", "disclosure_rules"),
    "capability_binding_hash": ("task_ids", "risk_protocols"),
    "review_schema_hash": (
        "manual_review_conditions", "sensitive_object_rules",
        "not_hard_ban_categories", "conflict_checklist",
    ),
    "artifact_schema_hash": ("reply_templates",),
    "minimization_profile_hash": ("direct_identifier_patterns", "forbidden_terms"),
    "gate_profile_hash": ("risk_weights",),
}


def get_case_binding(repo, case_id):
    """Return the active CaseDomainBinding for a case, or None."""
    return next(
        (b for b in repo.list("case_domain_binding", case_id)
         if b.get("binding_status") == "active"),
        None,
    )


def ensure_case_binding(repo, case, bound_by="system"):
    """Create the CaseDomainBinding once per case; idempotent for legacy cases."""
    existing = get_case_binding(repo, case["id"])
    if existing:
        return existing
    binding = CaseDomainBinding(
        id=uid("binding"),
        case_id=case["id"],
        cause_id=case.get("domain") or "",
        binding_status="active",
        bound_at=now(),
        bound_by=bound_by,
    ).model_dump()
    repo.put("case_domain_binding", binding, case["id"])
    return binding


def bind_case_packs(repo, binding, pack):
    """Pin the resolved pack onto a binding that has not pinned one yet."""
    if binding.get("cause_pack_id"):
        return binding
    binding = dict(binding)
    binding.update(
        cause_pack_id=pack["id"],
        cause_pack_version=pack.get("version"),
        legal_rule_pack_id=pack["id"],
        legal_rule_pack_version=pack.get("version"),
        jurisdiction=pack.get("jurisdiction"),
    )
    repo.put("case_domain_binding", binding, binding["case_id"])
    return binding


def resolve_runtime_snapshot(repo, binding, pack, runtime_environment="", task_type=None):
    """Resolve (or reuse) the immutable DomainRuntimeSnapshot.

    Prefers the DomainPackageManifest for the bound cause (P2): section hashes
    become real per-package content hashes. Falls back to the interim
    section-hash derivation over the monolithic pack when no manifest exists.
    Content-addressed: identical inputs reuse the stored snapshot.
    """
    manifest = None
    cause_id = (binding or {}).get("cause_id")
    if cause_id:
        from . import domain_packages
        manifest = domain_packages.find_manifest(
            repo, cause_id, source_pack_id=pack["id"] if pack else None)
        if manifest is None:
            # A manifest that exists but is draft or revoked must fail closed:
            # silently falling back to the interim path would bypass revocation.
            others = domain_packages.manifests_for(
                repo, cause_id, source_pack_id=pack["id"] if pack else None)
            if others:
                raise DomainRuntimeError(
                    "package_resolution_failed: manifest for this pack exists "
                    f"but is not resolvable (statuses: "
                    f"{sorted({m.get('status') for m in others})})")
    if manifest is not None:
        # The monolithic pack remains the consumption authority; its declared
        # platform API must match even when the snapshot resolves via manifest.
        if pack:
            _check_platform_api(pack.get("platform_api"), f"pack {pack.get('id')}")
        return _snapshot_from_manifest(repo, manifest, pack, runtime_environment, task_type)
    return _snapshot_from_pack(repo, pack, runtime_environment)


def _check_platform_api(declared, owner):
    if declared and declared != PLATFORM_API_VERSION:
        raise DomainRuntimeError(
            f"platform_api_mismatch: {owner} declares {declared}, kernel is {PLATFORM_API_VERSION}"
        )


def _snapshot_from_manifest(repo, manifest, pack, runtime_environment, task_type):
    """Build a snapshot from real package content hashes via a manifest."""
    from . import domain_packages
    _check_platform_api(manifest.get("platform_api_version"), f"manifest {manifest['id']}")
    refs = manifest.get("package_refs") or {}
    sections = {}
    binding_ref = None
    for package_type in (
        "cause_pack", "legal_rule_pack", "review_schema", "artifact_schema",
        "minimization_profile", "gate_profile",
    ):
        ref_list = refs.get(package_type) or []
        if not ref_list:
            raise DomainRuntimeError(
                f"package_resolution_failed: manifest {manifest['id']} lacks {package_type}")
        sections[f"{package_type}_hash"] = _resolve_ref(
            repo, ref_list[0], package_type, manifest["cause_id"])["content_hash"]
    for ref in refs.get("capability_binding") or []:
        package = _resolve_ref(repo, ref, "capability_binding", manifest["cause_id"], bare=True)
        from .spi import spi_for
        if spi_for(package).task_type() == task_type:
            binding_ref = package
            break
    # A task type added to the pack after the manifest was derived has no
    # binding record yet; resolve the cause-level packages and leave the
    # binding unbound rather than failing closed. A binding that exists but is
    # unusable is still rejected inside _resolve_ref.
    sections["capability_binding_hash"] = (
        binding_ref["content_hash"] if binding_ref else None)
    content = {
        **sections,
        "platform_api_version": PLATFORM_API_VERSION,
        "domain_package_manifest_id": manifest["id"],
        "capability_binding_id": binding_ref["id"] if binding_ref else None,
        "pack_id": pack["id"] if pack else None,
        "pack_version": pack.get("version") if pack else None,
        "pack_content_hash": digest(pack) if pack else None,
        "runtime_environment": runtime_environment,
    }
    return _store_snapshot(repo, content)


def _resolve_ref(repo, ref, package_type, cause_id, bare=False):
    """Load and verify a manifest package ref. Fail-closed on any mismatch."""
    try:
        package = repo.get(ref["id"], "domain_package")
    except KeyError:
        raise DomainRuntimeError(
            f"package_resolution_failed: package {ref.get('id')} missing")
    if package.get("status") == "revoked":
        raise DomainRuntimeError(
            f"package_resolution_failed: package {package['id']} is revoked")
    if package.get("status") == "draft":
        raise DomainRuntimeError(
            f"package_resolution_failed: package {package['id']} is still draft")
    _check_platform_api(package.get("platform_api"), f"package {package['id']}")
    compatibility = package.get("compatibility") or {}
    if compatibility and cause_id and cause_id not in compatibility:
        raise DomainRuntimeError(
            f"package_resolution_failed: package {package['id']} is not "
            f"compatible with cause {cause_id}")
    if ref.get("content_hash") and package.get("content_hash") != ref["content_hash"]:
        raise DomainRuntimeError(
            f"package_resolution_failed: package {package['id']} hash drifted "
            "from manifest ref")
    return package


def _snapshot_from_pack(repo, pack, runtime_environment):
    """Interim P1 path: derive seven section hashes from the monolithic pack."""
    if not pack:
        raise DomainRuntimeError("package_resolution_failed: no pack resolved for binding")
    _check_platform_api(pack.get("platform_api"), f"pack {pack.get('id')}")
    sections = {}
    for section, fields in _SNAPSHOT_SECTIONS.items():
        sections[section] = digest({name: pack.get(name) for name in fields})
    content = {
        **sections,
        "platform_api_version": PLATFORM_API_VERSION,
        "pack_id": pack["id"],
        "pack_version": pack.get("version"),
        "pack_content_hash": digest(pack),
        "runtime_environment": runtime_environment,
    }
    return _store_snapshot(repo, content)


def _store_snapshot(repo, content):
    snapshot_id = "drs_" + digest(content)
    for existing in repo.list("domain_runtime_snapshot"):
        if existing["id"] == snapshot_id:
            return existing
    snapshot = DomainRuntimeSnapshot(
        id=snapshot_id, created_at=now(), **content
    ).model_dump()
    repo.put("domain_runtime_snapshot", snapshot)
    return snapshot


def new_context_version(repo, case, snapshot_id, facts, documents):
    """Create a current CaseContextVersion; any prior current one is superseded."""
    version = CaseContextVersion(
        id=uid("ctx"),
        context_version_id=uid("ctxv"),
        case_id=case["id"],
        domain_runtime_snapshot_id=snapshot_id,
        verified_fact_set_hash=digest(facts),
        source_material_set_hash=digest(
            {doc["id"]: doc.get("version") for doc in documents}
        ),
        identity_mapping_version=case.get("mapping_version", 1),
        cumulative_disclosure_state=case.get("ledger_version", 0),
        case_revision=case.get("revision", 1),
        status="current",
        created_at=now(),
    ).model_dump()
    # Link every context still awaiting a successor (current ones, plus those
    # invalidated by a case revision bump before a successor existed).
    for prior in repo.list("case_context_version", case["id"]):
        if prior.get("status") == "superseded" and prior.get("superseded_by"):
            continue
        prior = dict(prior)
        prior["status"] = "superseded"
        prior["superseded_by"] = version["context_version_id"]
        repo.put("case_context_version", prior, case["id"])
    repo.put("case_context_version", version, case["id"])
    return version


def supersede_context_versions(repo, case_id, superseded_by=None):
    """Mark every current context version of the case as superseded."""
    changed = []
    for version in repo.list("case_context_version", case_id):
        if version.get("status") != "current":
            continue
        version = dict(version)
        version["status"] = "superseded"
        version["superseded_by"] = superseded_by
        repo.put("case_context_version", version, case_id)
        changed.append(version["context_version_id"])
    return changed


def record_task_step(repo, task, step_type, to_status, from_status=None, actor=None):
    """Append a TaskStep dual-write record. Steps do not drive state yet."""
    step = TaskStep(
        id=uid("step"),
        task_id=task["id"],
        case_id=task["case_id"],
        step_type=step_type,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        at=now(),
    ).model_dump()
    repo.put("task_step", step, task["case_id"])
    return step


def build_cloud_envelope(repo, task, case, request_hash, facts):
    """Build and store the V2.2 CloudContext envelope for a snapshot-bound
    task. case_ref is an opaque digest of the case id — the raw id never
    crosses the envelope boundary. Returns None for legacy tasks without a
    snapshot/context binding."""
    snapshot_id = task.get("domain_runtime_snapshot_id")
    context_id = task.get("context_version_id")
    if not snapshot_id or not context_id:
        return None
    envelope = CloudTaskEnvelope(
        id="cte_" + digest({
            "task_id": task["id"], "snapshot": snapshot_id,
            "context": context_id, "request_hash": request_hash,
        }),
        task_id=task["id"],
        case_ref="cref_" + digest({"case": case["id"], "cause": case.get("domain")}),
        cause_id=case.get("domain") or "",
        capability_id=f"R_{task['type']}" if task.get("type") else None,
        capability_binding_id=task.get("capability_binding_id"),
        context_version_id=context_id,
        domain_runtime_snapshot_id=snapshot_id,
        request_hash=request_hash,
        contract_version=2,
        facts=list(facts or []),
        created_at=now(),
    ).model_dump()
    repo.put("cloud_task_envelope", envelope, case["id"])
    return envelope
