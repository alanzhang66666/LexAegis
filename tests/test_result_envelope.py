"""V2.2 CloudResultEnvelope + HumanDecision contracts.

Cloud results are candidate outputs: the envelope receipt is written
pending_human on a fully-validated return, rejected when the pipeline
refuses it, and never when nothing crossed the wire. The HumanDecision
record is the named adoption that ends candidacy."""
import pytest

from lexaegis.gateway import create_gateway
from lexaegis.util import digest
from lexaegis.worker import finish_response, process_one
from .conftest import approve, demo_task, login_as, post_as
from .test_workflow import task_state


def _complete_demo_task(env):
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    assert process_one(env["app"].state.store, env["root"], env["gate"])
    assert task_state(env, case["id"], task["id"])["status"] == "complete"
    return case, task


def _envelopes(env, task_id):
    with env["app"].state.store.read() as repo:
        return [e for e in repo.list("cloud_result_envelope") if e["task_id"] == task_id]


def test_complete_return_writes_pending_envelope(demo_env):
    case, task = _complete_demo_task(demo_env)
    stored = task_state(demo_env, case["id"], task["id"])
    envelopes = _envelopes(demo_env, task["id"])
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["pipeline_status"] == "pending_human"
    assert envelope["provenance"] == "simulation"
    assert envelope["request_hash"] == stored["request_hash"]
    assert envelope["case_id"] == case["id"]
    assert envelope["result_hash"]
    assert envelope["failure_code"] is None
    listed = demo_env["client"].get(f"/api/v1/tasks/{task['id']}/cloud-result-envelopes")
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [envelope["id"]]


def test_rejected_result_writes_rejected_envelope(env):
    from .test_orchestrator import _create_task, _evaluate
    from .test_workflow import formal_material
    case, _doc, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        stored["cloud_envelope"]["request_hash"] = "tampered"
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "complete", "result": {"claims": []}})
        assert stored["status"] == "failed"
    envelopes = _envelopes(env, task["id"])
    assert len(envelopes) == 1
    assert envelopes[0]["pipeline_status"] == "rejected"
    assert envelopes[0]["failure_code"] == "invalid_cloud_result"
    assert envelopes[0]["result_hash"] == digest({"claims": []})


def test_no_result_writes_no_envelope(demo_env):
    case, task = demo_task(demo_env)
    approve(demo_env, task)
    with demo_env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "unknown"})
    assert _envelopes(demo_env, task["id"]) == []


def test_confirm_writes_human_decision(demo_env):
    case, task = _complete_demo_task(demo_env)
    stored = task_state(demo_env, case["id"], task["id"])
    claims = stored["artifact"]["claims"]
    for claim in claims:
        result = post_as(demo_env, "legal_reviewer",
                         f"/api/v1/tasks/{task['id']}/claims/{claim['id']}/review")
        assert result.status_code == 200, result.text
    confirmed = post_as(demo_env, "approver", f"/api/v1/tasks/{task['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    decisions = demo_env["client"].get(f"/api/v1/tasks/{task['id']}/human-decisions").json()
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["decision"] == "adopted"
    assert decision["actor_role"] == "approver"
    assert decision["request_hash"] == stored["request_hash"]
    artifact = confirmed.json()["artifact"]
    assert decision["artifact_hash"] == digest(artifact)
    with demo_env["app"].state.store.read() as repo:
        event = next(a for a in repo.list("audit")
                     if a["event"] == "artifact.confirmed")
    assert event["metadata"]["human_decision_id"] == decision["id"]


def test_gateway_role_credential_invariants(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", "unit-test-secret-32-characters-long")
    monkeypatch.delenv("LEX_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_PRIMARY_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_STANDBY_KEY", raising=False)
    # edge role may not hold credentials
    monkeypatch.setenv("LEX_GATEWAY_ROLE", "edge")
    monkeypatch.setenv("LEX_CLOUD_PRIMARY_KEY", "edge-must-not-have-this")
    with pytest.raises(ValueError, match="edge"):
        create_gateway(tmp_path / "g1")
    # edge role without credentials starts (claim surface only)
    monkeypatch.delenv("LEX_CLOUD_PRIMARY_KEY")
    create_gateway(tmp_path / "g2")
    # cloud role without credentials fails closed at startup
    monkeypatch.setenv("LEX_GATEWAY_ROLE", "cloud")
    with pytest.raises(ValueError, match="cloud"):
        create_gateway(tmp_path / "g3")
    # unified default tolerates either way
    monkeypatch.setenv("LEX_GATEWAY_ROLE", "unified")
    create_gateway(tmp_path / "g4")
    monkeypatch.delenv("LEX_GATEWAY_ROLE")
    create_gateway(tmp_path / "g5")
