"""Synthetic PR-01a projection and no-authority regression checks."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from lexaegis.contracts import GateDecision, GateHit
from lexaegis.gate_orchestrator import build_gate_bundle
from lexaegis import release_service


def decision(*gate_ids, eligible=False):
    return GateDecision(phase="evaluate", request_hash="req-a", snapshot_hash="snap-a",
                        approval_eligible=eligible,
                        hits=[GateHit(gate_id=g, status="pending", kind="verification",
                                      reason_code="missing", message=f"{g} missing")
                              for g in gate_ids]).model_dump(mode="json")


def test_four_groups_preserve_legacy_items_and_original_input():
    original = decision("G1", "G2", "G7", "G9", "G10", "G-product")
    before = deepcopy(original)
    bundle = build_gate_bundle(original)
    groups = {group["id"]: group for group in bundle["groups"]}
    assert list(groups) == ["G-L", "G-D", "G-H", "G-S"]
    assert [item["gate_id"] for item in groups["G-L"]["hits"]] == ["G1", "G2"]
    assert [item["gate_id"] for item in groups["G-D"]["hits"]] == ["G2", "G7"]
    assert [item["gate_id"] for item in groups["G-H"]["hits"]] == ["G10"]
    assert [item["gate_id"] for item in groups["G-S"]["hits"]] == ["G9"]
    assert [item["gate_id"] for item in bundle["global_hits"]] == ["G-product"]
    assert bundle["request_hash"] == "req-a" and bundle["snapshot_hash"] == "snap-a"
    assert bundle["authoritative"] is False and "dispatch_allowed" not in bundle
    assert original == before
    bundle["groups"][0]["hits"][0]["message"] = "changed"
    assert original == before


@pytest.mark.parametrize("gate", ["G0", "G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G-product"])
def test_no_legacy_blocker_is_lost_or_marked_ready(gate):
    value = decision(gate, eligible=True)
    result = build_gate_bundle(value)
    seen = result["global_hits"] + [hit for group in result["groups"] for hit in group["hits"]]
    assert any(hit == value["hits"][0] for hit in seen)
    assert result["summary_state"] == "blocked"


def test_no_hits_is_not_per_gate_pass_or_dispatch_authorization():
    result = build_gate_bundle(decision(eligible=True))
    assert result["summary_state"] == "ready_for_approval"
    assert all(g["state"] == "not_individually_verified" for g in result["groups"])
    assert "dispatch_allowed" not in result
    assert build_gate_bundle(decision(eligible=False))["summary_state"] == "blocked"


def test_unknown_gate_stays_visible_and_blocked():
    data = decision(eligible=True)
    data["hits"] = [{"gate_id": "future-gate", "message": "new issue"}]
    result = build_gate_bundle(data)
    assert result["summary_state"] == "blocked"
    assert result["global_hits"] == data["hits"]


@pytest.mark.parametrize("value", [None, {}, {"hits": None}, {"hits": [{}]}, {"hits": ["bad"]}])
def test_malformed_input_is_not_treated_as_valid(value):
    with pytest.raises(ValueError):
        build_gate_bundle(value)


def test_grouped_view_does_not_change_authoritative_status(monkeypatch):
    monkeypatch.setattr(release_service, "required", lambda _: True)
    frozen = SimpleNamespace(model_dump=lambda **kw: {"request_hash": "req-a"})
    original = GateDecision(phase="evaluate", request_hash="req-a", approval_eligible=False,
                            hits=[GateHit(gate_id="G3", status="pending", message="missing")])
    monkeypatch.setattr(release_service, "evaluate", lambda *args: (frozen, original))
    result = release_service.status(None, {}, {}, {})
    assert result["state"] == "blocked"
    assert result["decision"] == original.model_dump(mode="json")
    assert result["gate_bundle"]["authoritative"] is False
    assert result["gate_bundle"]["summary_state"] == "blocked"


def test_forged_display_projection_cannot_grant_authorization(monkeypatch):
    monkeypatch.setattr(release_service, "required", lambda _: True)
    gate = GateDecision(phase="evaluate", request_hash="req-a", approval_eligible=False,
                        hits=[GateHit(gate_id="G3", status="pending", message="missing")])
    monkeypatch.setattr(release_service, "evaluate", lambda *args: (object(), gate))
    monkeypatch.setattr(release_service, "build_gate_bundle", lambda _: {"summary_state": "ready_for_approval"})
    for phase in ("approve", "enqueue", "send"):
        with pytest.raises(ValueError, match="正式放行未满足"):
            release_service.assert_allowed(None, {}, {}, {}, phase)


def test_all_legacy_hit_combinations_are_conservative():
    from itertools import combinations
    gate_ids = ["G0", "G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G-product"]
    for count in range(len(gate_ids) + 1):
        for subset in combinations(gate_ids, count):
            for eligible in (False, True):
                source = decision(*subset, eligible=eligible)
                result = build_gate_bundle(source)
                seen = result["global_hits"] + [hit for group in result["groups"] for hit in group["hits"]]
                assert {item["gate_id"] for item in seen} == set(subset)
                assert (result["summary_state"] == "ready_for_approval") == (eligible and not subset)


def test_status_projects_real_formal_evaluation_without_changing_decision(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    spec = importlib.util.spec_from_file_location("formal_integration_helpers", Path(__file__).with_name("test_release_service_integration.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    store, intake, evidence, context, task, case, frozen, versions = helpers._evaluation_fixture(tmp_path, "v3-projection")
    try:
        with store.transaction() as repo:
            result = release_service.status(repo, task, case, context)
            assert result["state"] == "blocked"
            assert result["decision"]["approval_eligible"] is False
            assert result["decision"]["dispatch_allowed"] is False
            assert result["gate_bundle"] == build_gate_bundle(result["decision"])
            assert result["gate_bundle"]["request_hash"] == result["decision"]["request_hash"]
    finally:
        store.engine.dispose()
