"""PR-01b shadow diagnostics: synthetic evidence, no authorization."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from lexaegis.gate_evidence_scope import proposed_dependencies, compare_legacy_receipt_bindings, build_scope_diagnostics
from lexaegis.contracts import GateDecision, GateHit
from lexaegis import release_service
from lexaegis.util import digest


def request(**updates):
    values = dict(tuple={"case_id":"case-a", "purpose":"summary", "recipient":"provider-a"},
        material_versions={"doc":1}, rule_versions={"pack":"rule-a"}, runtime_pack_hash="pack-a",
        task_version=2, mapping_version=3, ledger_version=0, provider_profile_hash="provider-v1",
        target="https://example.invalid/v1", model="model-a", standby_provider_id=None,
        standby_provider_profile_hash=None, standby_target=None, standby_model=None,
        request_hash="request-a", combination_input_hash="combination-a",
        attack_protocol_hashes={"identity":"protocol-a"}, build_manifest_hash="build-a",
        wire_payload={"secret":"raw-case-DO-NOT-EXPOSE"}, prompt="private-prompt-DO-NOT-EXPOSE")
    values.update(updates)
    return SimpleNamespace(**values)


def legacy_versions(req):
    return {"materials":digest(req.material_versions),"rules":digest(req.rule_versions),
        "task":str(req.task_version),"mapping":str(req.mapping_version),
        "ledger":str(req.ledger_version),"combination":req.combination_input_hash}


def receipt(req, **updates):
    value={"id":"r1","gate_id":"G3","tuple":deepcopy(req.tuple),"request_hash":None,
           "bound_versions":legacy_versions(req),"conclusion":"pass"}
    value.update(updates)
    return value


def test_derived_scope_never_exposes_raw_payload_or_asserts_authority():
    obj=build_scope_diagnostics(request(), [])
    assert obj["state"] == "diagnostic_only" and obj["authoritative"] is False and obj["validated"] is False
    assert "DO-NOT-EXPOSE" not in repr(obj)
    assert all(not item["authoritative"] and not item["validated"] for item in obj["dependencies"].values())
    assert obj["dependencies"]["G9"]["fingerprint"] is None
    assert obj["dependencies"]["G9"]["missing_dependencies"] == ["deployment_identity"]


@pytest.mark.parametrize("field,changed,gate", [
    ("provider_profile_hash","provider-v2","G3"), ("target","https://other.invalid","G3"),
    ("model","model-b","G3"),
    ("rule_versions",{"pack":"rule-b"},"G5"), ("runtime_pack_hash","pack-b","G5"),
    ("request_hash","request-b","G8"), ("ledger_version",1,"G8"),
    ("combination_input_hash","combination-b","G8"),
    ("attack_protocol_hashes",{"identity":"protocol-b"},"G8"),
])
def test_critical_inputs_change_diagnostic_fingerprint(field, changed, gate):
    before=proposed_dependencies(request())[gate]["fingerprint"]
    after=proposed_dependencies(request(**{field:changed}))[gate]["fingerprint"]
    assert before is not None and after is not None and before != after


@pytest.mark.parametrize("key", ["purpose", "recipient"])
def test_purpose_and_recipient_change_provider_fingerprint(key):
    original = request()
    scope = dict(original.tuple)
    scope[key] = "changed"
    assert proposed_dependencies(original)["G3"]["fingerprint"] != proposed_dependencies(request(tuple=scope))["G3"]["fingerprint"]


@pytest.mark.parametrize("field,value,gate", [
    ("target","","G3"), ("provider_profile_hash",None,"G3"),
    ("rule_versions",{},"G5"), ("runtime_pack_hash","","G5"),
    ("request_hash","","G8"), ("attack_protocol_hashes",{},"G8"),
])
def test_missing_critical_input_has_no_diagnostic_fingerprint(field,value,gate):
    info=proposed_dependencies(request(**{field:value}))[gate]
    assert info["fingerprint"] is None and info["missing_dependencies"]


def test_standby_slot_is_fully_bound_or_reported_incomplete():
    original=proposed_dependencies(request())["G3"]["fingerprint"]
    partial=proposed_dependencies(request(standby_model="standby-b"))["G3"]
    assert partial["fingerprint"] is None and "standby_provider" in partial["missing_dependencies"]
    complete=proposed_dependencies(request(standby_provider_id="backup",standby_provider_profile_hash="profile-b",
        standby_target="https://backup.invalid",standby_model="standby-b"))["G3"]
    assert complete["fingerprint"] and complete["fingerprint"] != original


@pytest.mark.parametrize("field,gate", [("rule_versions","G5"), ("attack_protocol_hashes","G8")])
def test_nested_empty_version_never_generates_fingerprint(field, gate):
    info=proposed_dependencies(request(**{field:{"missing":""}}))[gate]
    assert info["fingerprint"] is None


def test_irrelevant_fact_change_does_not_claim_authorized_reuse():
    a=proposed_dependencies(request())
    b=proposed_dependencies(request(material_versions={"doc":9},task_version=9))
    assert a["G3"]["fingerprint"] == b["G3"]["fingerprint"]
    assert a["G5"]["fingerprint"] == b["G5"]["fingerprint"]
    assert a["G3"]["validated"] is False


def test_shadow_reports_version_drift_not_reusability():
    req=request(); r=receipt(req); r["bound_versions"]["materials"]="old"
    result=compare_legacy_receipt_bindings(req,[r])[0]
    assert result["changed_dependencies"] == ["materials"]
    assert result["legacy_binding_matches"] is False
    assert result["validated"] is False and result["authoritative"] is False
    assert "scope_migration_candidate" not in result


def test_matching_or_revoked_receipt_never_counts_as_verified():
    req=request(); r=receipt(req,revoked_at="2026-01-01")
    item=compare_legacy_receipt_bindings(req,[r])[0]
    assert item["legacy_binding_matches"] is True
    assert item["validated"] is False and item["authoritative"] is False


@pytest.mark.parametrize("change", [
    {"tuple":{"case_id":"other","purpose":"summary","recipient":"provider-a"}},
    {"tuple":{"case_id":"case-a","purpose":"other","recipient":"provider-a"}},
    {"tuple":{"case_id":"case-a","purpose":"summary","recipient":"other"}},
    {"request_hash":"other-request"}, {"gate_id":"G9"}, {"bound_versions":None},
])
def test_other_scope_and_invalid_bindings_do_not_enter_shadow(change):
    req=request(); assert compare_legacy_receipt_bindings(req,[receipt(req,**change)]) == []


def test_diagnostic_failure_cannot_change_authoritative_decision(monkeypatch):
    monkeypatch.setattr(release_service,"required",lambda _:True)
    frozen=SimpleNamespace(model_dump=lambda **kw:{"request_hash":"request-a"})
    gate=GateDecision(phase="evaluate",request_hash="request-a",approval_eligible=False,
        hits=[GateHit(gate_id="G3",status="pending",message="missing")])
    monkeypatch.setattr(release_service,"evaluate",lambda *a:(frozen,gate))
    monkeypatch.setattr(release_service,"build_scope_diagnostics",lambda *a:(_ for _ in ()).throw(RuntimeError("bad diagnostics")))
    class Repo:
        def list(self,kind): return []
    status=release_service.status(Repo(),{}, {}, {})
    assert status["decision"] == gate.model_dump(mode="json") and status["state"] == "blocked"
    assert status["scope_diagnostics"] == {"schema_version":1,"state":"unavailable","authoritative":False,"validated":False}
    with pytest.raises(ValueError,match="正式放行未满足"):
        release_service.assert_allowed(Repo(),{}, {}, {},"approve")


def test_real_formal_status_shadow_remains_non_authoritative(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    monkeypatch.setenv("LEX_RUN_PROFILE","production")
    spec=importlib.util.spec_from_file_location("formal_helpers",Path(__file__).with_name("test_release_service_integration.py"))
    helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
    store, intake, evidence, context, task, case, frozen, versions=helpers._evaluation_fixture(tmp_path,"v3-shadow")
    try:
        with store.transaction() as repo:
            stale=receipt(frozen,id="test-stale",bound_versions={"rules":"old"})
            repo.put("gate_evidence_receipt",stale,case["id"])
            status=release_service.status(repo,task,case,context)
            assert status["state"] == "blocked" and status["decision"]["approval_eligible"] is False
            assert status["scope_diagnostics"]["authoritative"] is False
            assert status["scope_diagnostics"]["request_hash"] == status["decision"]["request_hash"]
            entries=status["scope_diagnostics"]["receipt_binding_shadow"]
            assert any(item["receipt_id"] == "test-stale" and "rules" in item["changed_dependencies"] for item in entries)
            assert not repo.list("one_time_dispatch_grant")
    finally:store.engine.dispose()
