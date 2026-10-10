"""Diagnostics only: dependency fingerprints never authorize external sending."""
from types import SimpleNamespace

from lexaegis.gate_evidence_scope import proposed_dependencies, compare_legacy_receipt_bindings


def _request(**updates):
    values = dict(material_versions={"d": 1}, rule_versions={"pack": "v1"},
                  combination_input_hash="combo", ledger_version=1,
                  provider_profile_hash="provider-v1",
                  tuple={"purpose": "summary", "recipient": "cloud-a"},
                  request_hash="request-a", build_manifest_hash="build-a")
    values.update(updates)
    return SimpleNamespace(**values)


def test_provider_and_pack_proof_not_bound_to_unrelated_task_changes():
    baseline = proposed_dependencies(_request())
    altered = proposed_dependencies(_request(material_versions={"d": 2},
                                             ledger_version=2, request_hash="request-b"))
    assert baseline["G3"]["fingerprint"] == altered["G3"]["fingerprint"]
    assert baseline["G5"]["fingerprint"] == altered["G5"]["fingerprint"]
    assert baseline["G7"]["fingerprint"] != altered["G7"]["fingerprint"]


def test_critical_changes_invalidate_appropriate_proposed_scopes():
    baseline = proposed_dependencies(_request())
    other_provider = proposed_dependencies(_request(provider_profile_hash="provider-v2"))
    other_rules = proposed_dependencies(_request(rule_versions={"pack": "v2"}))
    other_build = proposed_dependencies(_request(build_manifest_hash="build-b"))
    assert baseline["G3"]["fingerprint"] != other_provider["G3"]["fingerprint"]
    assert baseline["G5"]["fingerprint"] != other_rules["G5"]["fingerprint"]
    assert baseline["G9"]["fingerprint"] != other_build["G9"]["fingerprint"]


def test_missing_environment_identity_is_not_verified():
    results = proposed_dependencies(_request())
    assert results["G9"]["fingerprint"] is None
    assert all(item["authoritative"] is False for item in results.values())
    assert proposed_dependencies(_request(), deployment_identity="dep-a")["G9"]["fingerprint"]


def test_shadow_identifies_non_rule_drift_without_authorizing():
    request = _request(task_version=2, mapping_version=3)
    receipt = {"id": "receipt-a", "gate_id": "G5", "tuple": request.tuple,
               "request_hash": None, "bound_versions": {
                   "materials": "old", "rules": proposed_dependencies(request)["G5"]["fingerprint"],
                   "task": "1", "mapping": "2", "ledger": "1",
                   "combination": "combo"}}
    # Use the real rules hash to isolate unrelated version drift.
    from lexaegis.util import digest
    receipt["bound_versions"]["rules"] = digest(request.rule_versions)
    result = compare_legacy_receipt_bindings(request, [receipt])
    assert len(result) == 1
    assert result[0]["scope_migration_candidate"] is True
    assert result[0]["legacy_binding_matches"] is False
    assert result[0]["validated"] is False
    assert result[0]["authoritative"] is False


def test_shadow_rejects_changed_rules_and_cross_scope():
    request = _request(task_version=2, mapping_version=3)
    from lexaegis.util import digest
    baseline = {
        "id": "receipt-b", "gate_id": "G5", "tuple": request.tuple,
        "request_hash": None, "bound_versions": {
            "materials": digest(request.material_versions), "rules": "stale",
            "task": "2", "mapping": "3", "ledger": "1", "combination": "combo"}}
    result = compare_legacy_receipt_bindings(request, [baseline])
    assert result[0]["scope_migration_candidate"] is False
    wrong_scope = dict(baseline, tuple={"purpose": "other", "recipient": "cloud-a"})
    assert compare_legacy_receipt_bindings(request, [wrong_scope]) == []
