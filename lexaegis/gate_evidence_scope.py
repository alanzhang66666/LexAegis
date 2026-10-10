"""Read-only receipt dependency diagnostics for future evidence reuse.

This module does not validate receipts and MUST NOT be used to authorize
dispatch. The legacy exact bound_versions checks remain authoritative.
"""
from .util import digest

# Proposed minimum dependency sets. A change in a dependency invalidates
# the diagnostic fingerprint. G9 is intentionally excluded because its
# authoritative deployment/build proof has a separate receipt contract.
DEPENDENCIES = {
    "G1": ("materials", "rules"),
    "G2": ("materials", "rules"),
    "G3": ("provider_profile", "purpose", "recipient"),
    "G5": ("rules",),
    "G6": ("request_hash",),
    "G7": ("combination", "ledger", "request_hash"),
    "G8": ("request_hash",),
    "G9": ("deployment_identity", "build_manifest"),
    "G10": ("request_hash",),
}


def proposed_dependencies(request, *, deployment_identity=None):
    """Compute diagnostic hashes using only an already-frozen request.

    No cache, cross-case reuse, trust decision, or bypass is implemented.
    Missing scope values produce None and may not be treated as verified.
    """
    versions = {
        "materials": digest(request.material_versions),
        "rules": digest(request.rule_versions),
        "combination": request.combination_input_hash,
        "ledger": str(request.ledger_version),
        "provider_profile": request.provider_profile_hash,
        "purpose": request.tuple.get("purpose"),
        "recipient": request.tuple.get("recipient"),
        "request_hash": request.request_hash,
        "deployment_identity": deployment_identity,
        "build_manifest": request.build_manifest_hash,
    }
    return {
        gate_id: {
            "dependencies": list(keys),
            "fingerprint": digest({k: versions[k] for k in keys})
            if all(versions.get(k) is not None for k in keys) else None,
            "authoritative": False,
        }
        for gate_id, keys in DEPENDENCIES.items()
    }


def compare_legacy_receipt_bindings(request, receipts):
    """Audit why an otherwise present G3/G5 receipt misses legacy binding.

    This is a *shadow-only* comparison, not evidence verification: conclusions,
    signatures, artifact bytes, expiry, revocation, role separation and legal
    scope are deliberately NOT evaluated here. Never use it to authorize.
    """
    expected = {
        "materials": digest(request.material_versions),
        "rules": digest(request.rule_versions),
        "task": str(request.task_version),
        "mapping": str(request.mapping_version),
        "ledger": str(request.ledger_version),
        "combination": request.combination_input_hash,
    }
    output = []
    for raw in receipts:
        gate = raw.get("gate_id")
        if gate not in {"G3", "G5"}:
            continue
        if raw.get("tuple") != request.tuple:
            continue
        if raw.get("request_hash") not in (None, request.request_hash):
            continue
        bound = raw.get("bound_versions")
        if not isinstance(bound, dict):
            continue
        changed = sorted(k for k in set(bound) | set(expected)
                         if bound.get(k) != expected.get(k))
        output.append({
            "receipt_id": raw.get("id"),
            "gate_id": gate,
            "legacy_binding_matches": not changed,
            "changed_dependencies": changed,
            "scope_migration_candidate": (
                bool(changed)
                and all(key not in {"rules"} for key in changed)
                and raw.get("request_hash") is None
            ),
            "validated": False,
            "authoritative": False,
        })
    return output
