import pytest

from lexaegis.attacks import (
    FORMAL_EXECUTOR_VERSION,
    POSITIVE_CONTROL_REQUEST,
    evaluate as evaluate_attack,
    run_formal_suite,
)
from lexaegis.util import digest

from .test_redteam_workflow import install_protocols
from .test_workflow import formal_material, task_state


def evaluated_task(env):
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    return case, task_state(env, case["id"], task["id"])


def test_formal_suite_records_request_bound_runs(env):
    case, task = evaluated_task(env)
    response = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json={})
    assert response.status_code == 200, response.text
    suite = response.json()
    assert suite["conclusion"] == "complete"
    assert suite["request_hash"] == task["request_hash"]
    assert suite["attack_input_hash"] == task["attack_input_hash"]
    assert suite["executor_version"] == FORMAL_EXECUTOR_VERSION
    assert suite["positive_control"]["detected"] is True
    assert len(suite["run_ids"]) == 4
    runs = env["client"].get(f"/api/v1/tasks/{task['id']}/attacks").json()
    bound = [item for item in runs if item.get("suite_id") == suite["id"]]
    assert len(bound) == 4
    assert all(item["executor_version"] == FORMAL_EXECUTOR_VERSION for item in bound)
    assert all(item["request_hash"] == task["request_hash"] for item in bound)
    assert all(item["result_hash"] for item in bound)
    suites = env["client"].get(f"/api/v1/tasks/{task['id']}/attack-suites").json()
    assert [item["id"] for item in suites] == [suite["id"]]


def test_formal_suite_requires_frozen_request(env):
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    response = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json={})
    assert response.status_code in (400, 409)


def test_positive_control_failure_invalidates_whole_suite(env):
    case, task = evaluated_task(env)

    def blind_evaluate(protocol, request, history, auxiliary, labels=None):
        return {"protocol": protocol.get("kind"), "outcome": "uncertain", "score": None,
                "evidence": ["模拟失效评测器"], "query_count": 0, "duration_ms": 1,
                "executor_version": "fake-engine/0.0"}

    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        suite = run_formal_suite(repo, stored, evaluate_fn=blind_evaluate)
    assert suite["conclusion"] == "invalid"
    assert suite["positive_control"]["detected"] is False
    with env["app"].state.store.read() as repo:
        runs = [item for item in repo.list("attack_run", task["id"]) if item.get("suite_id") == suite["id"]]
    assert len(runs) == 4
    assert {item["outcome"] for item in runs} == {"not_run"}
    assert all("阳性对照" in item["evidence"][0] for item in runs)


def test_auxiliary_set_hash_mismatch_rejected(env):
    case, task = evaluated_task(env)
    entries = [{"candidate": "线索人", "clue": "某线索"}]
    body = {"auxiliary_sets": {"identity": [
        {"dataset_id": "aux-1", "dataset_kind": "name_corpus",
         "content_hash": "0" * 64, "entries": entries}
    ]}}
    response = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json=body)
    assert response.status_code in (400, 409, 422)


def test_protocol_drift_blocks_suite(env):
    case, task = evaluated_task(env)
    with env["app"].state.store.transaction() as repo:
        protocol = repo.list("risk_protocol")[0]
        drifted = dict(protocol)
        drifted["content_hash"] = digest({"tampered": True})
        repo.put("risk_protocol", drifted)
    response = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json={})
    assert response.status_code in (400, 409)


def test_run_results_cannot_be_reused_across_request_versions(env):
    case, task = evaluated_task(env)
    first = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json={})
    assert first.status_code == 200
    current = task_state(env, case["id"], task["id"])
    decision = current["decisions"][0]
    env["client"].patch(
        f"/api/v1/tasks/{task['id']}/decisions/{decision['fact_id']}",
        json={"transform": "delete", "necessity": "unnecessary"})
    reevaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    second = env["client"].post(f"/api/v1/tasks/{task['id']}/attack-suites/run", json={})
    assert second.status_code == 200, second.text
    assert second.json()["request_hash"] == reevaluated["request_hash"]
    assert second.json()["request_hash"] != first.json()["request_hash"]
