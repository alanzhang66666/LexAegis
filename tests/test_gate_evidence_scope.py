"""Diagnostics only: dependency fingerprints never authorize external sending."""
from types import SimpleNamespace

from lexaegis.gate_evidence_scope import proposed_dependencies


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
