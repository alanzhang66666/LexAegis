"""V2.2 P6: staged return pipeline + edge autonomy (waiting-cloud)."""
import httpx
import pytest

from lexaegis import return_pipeline
from lexaegis.worker import process_one
from .conftest import approve, demo_task
from .test_workflow import task_state
from .test_orchestrator import _create_task, _evaluate
from .test_workflow import formal_material


def test_return_pipeline_records_stage_steps(demo_env):
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    assert process_one(env["app"].state.store, env["root"], env["gate"])
    finished = task_state(env, case["id"], task["id"])
    assert finished["status"] == "complete"
    assert finished["artifact"]["provenance"] == "simulation"
    with env["app"].state.store.read() as repo:
        steps = [s for s in repo.list("task_step") if s["task_id"] == task["id"]]
    stages = [s["to_status"] for s in steps if s["to_status"].startswith("return:")]
    assert stages[0] == "return:envelope:ok"
    assert stages[-1] == "return:human_decision:pending_human"
    for name in ("schema", "provenance", "identity_relink",
                 "evidence_relink", "review_schema"):
        assert any(s.startswith(f"return:{name}:") for s in stages)


def test_mock_can_never_claim_cloud_provenance():
    assert return_pipeline.provenance_for_transport("mock") == "simulation"
    assert return_pipeline.provenance_for_transport("local") == "local_deterministic"
    assert return_pipeline.provenance_for_transport("cloud") == "cloud"
    with pytest.raises(ValueError):
        return_pipeline.provenance_for_transport("carrier_pigeon")


def test_connect_error_suspends_waiting_cloud(demo_env):
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")

    class RefusedClient:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("refused")
        def get(self, *args, **kwargs):
            raise httpx.ConnectError("refused")

    assert process_one(env["app"].state.store, env["root"], RefusedClient())
    state = task_state(env, case["id"], task["id"])
    # The durable send boundary was provably never crossed: the task is not
    # advanced to unknown/failed and no result is fabricated.
    assert state["status"] == "sending"
    assert not state.get("artifact")
    with env["app"].state.store.read() as repo:
        job = next(j for j in repo.list("job") if j["kind"] == "send")
        assert job["status"] == "pending"
        assert job.get("not_before")
        steps = [s for s in repo.list("task_step") if s["task_id"] == task["id"]]
    assert any(s["to_status"] == return_pipeline.WAITING_CLOUD for s in steps)
    # deferred: not_before keeps the job out of the next sweep
    assert not process_one(env["app"].state.store, env["root"], env["gate"])


def test_read_timeout_still_becomes_unknown(demo_env):
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")

    class TimeoutClient:
        def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("byte lost mid-flight")

    assert process_one(env["app"].state.store, env["root"], TimeoutClient())
    # The request may have crossed the boundary: unknown, never retried.
    assert task_state(env, case["id"], task["id"])["status"] == "unknown"


def test_envelope_hash_mismatch_fails_return(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    from lexaegis.worker import finish_response
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        assert stored.get("cloud_envelope")
        stored["cloud_envelope"]["request_hash"] = "tampered"
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "complete", "result": {}})
        stored = repo.get(task["id"], "task")
        assert stored["status"] == "failed"
        assert stored["failure_code"] == "invalid_cloud_result"
        steps = [s for s in repo.list("task_step") if s["task_id"] == task["id"]]
    assert any(s["to_status"] == "return:envelope:failed" for s in steps)
