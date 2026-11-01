"""Shadow-only evidence scope diagnostics for the V3 migration.

Adapted from LexAegis PR #5 (5f2b6b8); no return value is a signed proof,
legal determination, permission to reuse evidence, or dispatch authorization.
The exact bindings in formal_release.evaluate_release remain authoritative.
"""
from .util import digest

# These are *diagnostic inputs*, not a complete, legally approved scope.
# G1/G2/G6/G7/G10 are intentionally not proposed for cross-request reuse.
SCOPE_FIELDS = {
    "G3": ("purpose", "recipient", "provider_profile", "target", "model"),
    "G5": ("rules", "runtime_pack"),
    "G8": ("request_hash", "combination", "ledger", "attack_protocols"),
    "G9": ("build_manifest", "deployment_identity"),
}


def _available(value):
    if isinstance(value, dict):
        return bool(value) and all(isinstance(key, str) and key and _available(item)
                                   for key, item in value.items())
    return value is not None and value != "" and value != {} and value != []


def proposed_dependencies(request, *, deployment_identity=None):
    """Return unverified fingerprints; missing inputs never yield a hash.

    G3 additionally hashes standby slot fields when present, but their absence
    is represented explicitly rather than treated as a validated configuration.
    Fingerprints deliberately do not include any raw materials or wire content.
    """
    scope = request.tuple or {}
    values = {
        "purpose": scope.get("purpose"), "recipient": scope.get("recipient"),
        "provider_profile": request.provider_profile_hash,
        "target": request.target, "model": request.model,
        "rules": request.rule_versions, "runtime_pack": request.runtime_pack_hash,
        "request_hash": request.request_hash, "combination": request.combination_input_hash,
        "ledger": request.ledger_version, "attack_protocols": request.attack_protocol_hashes,
        "build_manifest": request.build_manifest_hash, "deployment_identity": deployment_identity,
    }
    results = {}
    for gate_id, fields in SCOPE_FIELDS.items():
        missing = [name for name in fields if not _available(values[name])]
        payload = {name: values[name] for name in fields}
        if gate_id == "G3":
            payload["standby"] = {
                "provider": request.standby_provider_id,
                "profile": request.standby_provider_profile_hash,
                "target": request.standby_target, "model": request.standby_model,
            }
            if any(_available(value) for value in payload["standby"].values()):
                missing.extend("standby_" + name for name, value in payload["standby"].items()
                               if not _available(value))
        results[gate_id] = {
            "dependencies": list(fields), "missing_dependencies": missing,
            "fingerprint": None if missing else digest(payload),
            "validated": False, "authoritative": False,
        }
    return results


def compare_legacy_receipt_bindings(request, receipts):
    """Show exact legacy version differences for same-scope G3/G5 records.

    This comparison intentionally does not inspect signatures, expiry,
    revocation, role, source bytes, applicable law, or consent; it makes no
    claim that any receipt can be reused, even where its versions match.
    """
    expected = {
        "materials": digest(request.material_versions), "rules": digest(request.rule_versions),
        "task": str(request.task_version), "mapping": str(request.mapping_version),
        "ledger": str(request.ledger_version), "combination": request.combination_input_hash,
    }
    if not isinstance(receipts, (list, tuple)):
        raise ValueError("门禁收据列表格式无效")
    output = []
    for raw in receipts:
        if not isinstance(raw, dict) or raw.get("gate_id") not in {"G3", "G5"}:
            continue
        if raw.get("tuple") != request.tuple or raw.get("request_hash") not in (None, request.request_hash):
            continue
        bound = raw.get("bound_versions")
        if not isinstance(bound, dict):
            continue
        changed = sorted(key for key in set(bound) | set(expected) if bound.get(key) != expected.get(key))
        output.append({
            "receipt_id": raw.get("id"), "gate_id": raw["gate_id"],
            "legacy_binding_matches": not changed, "changed_dependencies": changed,
            "validated": False, "authoritative": False,
        })
    return output


def build_scope_diagnostics(request, receipts):
    """Package a no-authority snapshot bound to the current request hash."""
    return {
        "schema_version": 1, "state": "diagnostic_only",
        "request_hash": request.request_hash, "validated": False, "authoritative": False,
        "notice": "仅供版本差异分析，未验证签署、效期或法律适用性，不能用于批准或复用。",
        "dependencies": proposed_dependencies(request),
        "receipt_binding_shadow": compare_legacy_receipt_bindings(request, receipts),
    }
