"""V2.2 P4: orchestrator funnel, cloud task envelope, request-hash deps."""
import pytest

from lexaegis import domain_runtime, orchestrator
from lexaegis.util import digest, sign
from .conftest import login_admin, login_as
from .test_workflow import formal_material

GATEWAY_SECRET = "unit-test-secret-32-characters-long"


def _create_task(env, case_id, task_type="fact_summary", transport="cloud"):
    result = env["client"].post(
        f"/api/v1/cases/{case_id}/tasks",
        json={"task_type": task_type, "transport": transport})
    assert result.status_code == 200, result.text
    return result.json()


def _evaluate(env, task_id):
    result = env["client"].post(f"/api/v1/tasks/{task_id}/evaluate")
    assert result.status_code == 200, result.text
    return result.json()


def test_evaluate_builds_cloud_envelope_for_snapshot_bound_task(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    evaluated = _evaluate(env, task["id"])
    stored = None
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
    envelope = stored["cloud_envelope"]
    assert envelope["task_id"] == task["id"]
    assert envelope["cause_id"] == "labor"
    assert envelope["domain_runtime_snapshot_id"] == stored["domain_runtime_snapshot_id"]
    assert envelope["context_version_id"] == stored["context_version_id"]
    # opaque case reference — raw case id must not cross the envelope boundary
    assert envelope["case_ref"].startswith("cref_")
    assert envelope["case_ref"] != case["id"]
    assert envelope["request_hash"] == stored["request_hash"]
    assert envelope["facts"] == stored["request"]["wire_payload"]["facts"]
    deps = stored["request"]["dependencies"]
    assert deps["cloud_task_envelope_id"] == envelope["id"]
    assert deps["capability_binding_hash"]
    assert deps["context_version_id"] == stored["context_version_id"]
    assert "provider_profile_hash" in deps


def test_envelope_stored_as_observable_record(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    _evaluate(env, task["id"])
    with env["app"].state.store.read() as repo:
        records = repo.list("cloud_task_envelope", case["id"])
    assert len(records) == 1
    assert records[0]["request_hash"]


def test_gateway_rejects_snapshot_bound_cloud_request_without_envelope(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
    request = dict(stored["request"])
    assert request["transport"] == "cloud"
    assert request["dependencies"].get("domain_runtime_snapshot_id")
    request["target"] = "https://api.openai.com/v1/chat/completions"
    content = {"request": request, "approval": {}}
    envelope = {**content, "signature": sign(content, GATEWAY_SECRET)}
    result = env["gate"].post("/dispatch", json=envelope)
    assert result.status_code == 403
    assert "envelope" in result.json()["detail"].lower()


def test_gateway_rejects_drifted_or_incomplete_envelope(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
    request = dict(stored["request"])
    request["target"] = "https://api.openai.com/v1/chat/completions"
    # incomplete envelope: missing facts/request_hash
    broken = {"task_id": task["id"], "case_ref": "cref_x"}
    content = {"request": request, "approval": {}, "cloud_envelope": broken}
    envelope = {**content, "signature": sign(content, GATEWAY_SECRET)}
    assert env["gate"].post("/dispatch", json=envelope).status_code == 403
    # drifted facts (request_hash refreshed so the facts check is what trips)
    drifted = dict(stored["cloud_envelope"])
    drifted["request_hash"] = digest(request)
    drifted["facts"] = [{"id": "x", "text": "drifted", "field": "event"}]
    content = {"request": request, "approval": {}, "cloud_envelope": drifted}
    envelope = {**content, "signature": sign(content, GATEWAY_SECRET)}
    result = env["gate"].post("/dispatch", json=envelope)
    assert result.status_code == 403


def test_orchestrator_derives_status_from_steps(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    _evaluate(env, task["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        derived = orchestrator.derive_status(repo, task["id"], case["id"])
        assert derived == stored["status"]
        assert orchestrator.consistent(repo, stored)


def test_transition_task_funnel_records_step_atomically(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        orchestrator.transition_task(repo, stored, "blocked", "CONTROL", actor="tester")
        repo.put("task", stored, case["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        assert stored["status"] == "blocked"
        steps = [s for s in repo.list("task_step", case["id"])
                 if s["task_id"] == task["id"]]
        assert steps[-1]["to_status"] == "blocked"
        assert steps[-1]["from_status"] == "draft"
        assert orchestrator.consistent(repo, stored)


def test_authority_flag_rejects_drifted_task(env, monkeypatch):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        stored["status"] = "approved"  # drift: no matching step
        repo.put("task", stored, case["id"])
    monkeypatch.setenv(orchestrator.AUTHORITY_ENV, "1")
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        with pytest.raises(domain_runtime.DomainRuntimeError):
            orchestrator.assert_consistent(repo, stored)


def test_validation_and_cloud_steps_are_observations(env, monkeypatch):
    """Pipeline stage labels and the waiting-cloud marker must never feed
    derive_status — only real status-bearing steps count."""
    monkeypatch.setenv(orchestrator.AUTHORITY_ENV, "1")
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        status_before = stored["status"]
        domain_runtime.record_task_step(
            repo, stored, "VALIDATION", "return:hash:ok")
        domain_runtime.record_task_step(
            repo, stored, "CLOUD", "waiting-cloud")
    with env["app"].state.store.read() as repo:
        derived = orchestrator.derive_status(repo, task["id"], case["id"])
        assert derived == status_before
        stored = repo.get(task["id"], "task")
        orchestrator.assert_consistent(repo, stored)


def test_authority_mode_rejects_drift_at_dispatch_gate(env, monkeypatch):
    """A status write that bypassed the funnel is caught at the shared
    approve/enqueue/send gate once the authority flag is on."""
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="local")
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        stored["status"] = "approved"  # drift: no matching step
        repo.put("task", stored, case["id"])
    monkeypatch.setenv(orchestrator.AUTHORITY_ENV, "1")
    login_as(env, "approver")
    result = env["client"].post(
        f"/api/v1/tasks/{task['id']}/approve",
        json={"request_hash": task["request_hash"] or "x"})
    assert result.status_code == 409
    assert "orchestrator_inconsistent" in result.text


def test_authority_mode_normal_workflow_stays_consistent(demo_env, monkeypatch):
    """With every write funneled, the approve+enqueue path keeps working
    under the authority flag — the flag adds checks, not behavior changes."""
    env = demo_env
    monkeypatch.setenv(orchestrator.AUTHORITY_ENV, "1")
    from .conftest import approve as approve_helper, demo_task
    case, task = demo_task(env, transport="mock")
    approve_helper(env, task)
    sent = env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    assert sent.status_code == 200, sent.text
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        assert stored["status"] == "queued"
        assert orchestrator.consistent(repo, stored)


def test_invalid_cloud_result_marks_failure_code(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    from lexaegis.worker import finish_response
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "complete", "result": {"bogus": 1}})
        stored = repo.get(task["id"], "task")
        assert stored["status"] == "failed"
        assert stored["failure_code"] == "invalid_cloud_result"


def test_failed_before_send_marks_failure_code(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"], transport="cloud")
    _evaluate(env, task["id"])
    from lexaegis.worker import finish_response
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "rejected"})
        stored = repo.get(task["id"], "task")
        assert stored["status"] == "failed"
        assert stored["failure_code"] == "failed_before_send"
