import httpx
import pytest
from fastapi.testclient import TestClient

from lexaegis.attacks import evaluate as evaluate_attack
from lexaegis.redteam import app as redteam_app
from lexaegis.util import digest, sign
from lexaegis.worker import process_one, recover
from .test_workflow import formal_material, task_state


KINDS = ("identity", "candidate_set", "sensitive_inference", "cross_round")


class LocalRedteam:
    def __init__(self):
        self.client = TestClient(redteam_app)

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *args):
        return self.client.__exit__(*args)

    def post(self, url, *, json, timeout):
        return self.client.post(url, json=json)


def frozen_protocol(kind):
    protocol = {
        "id": f"protocol_{kind}_v1",
        "kind": kind,
        "version": "1.0",
        "status": "frozen",
        "attacker_view": ["wire_payload", "disclosed_history"],
        "auxiliary_data": [],
        "query_budget": 3,
        "time_budget_seconds": 5,
        "success_criteria": {"operator": "gte", "metric": "attack_score"},
        "threshold": 0.5,
        "random_seed": 23,
        "content_hash": None,
    }
    protocol["content_hash"] = digest({key: value for key, value in protocol.items() if key != "content_hash"})
    return protocol


def install_protocols(env, task):
    protocols = [frozen_protocol(kind) for kind in KINDS]
    with env["app"].state.store.transaction() as repo:
        pack = repo.get(task["pack_id"], "pack")
        pack["risk_protocols"] = [{"id": item["id"], "version": item["version"]} for item in protocols]
        repo.put("pack", pack)
        for protocol in protocols:
            repo.put("risk_protocol", protocol)
    return protocols


def test_redteam_endpoint_requires_signature_and_frozen_hash(monkeypatch):
    monkeypatch.setenv("LEX_REDTEAM_SECRET", "separate-redteam-secret")
    protocol = frozen_protocol("candidate_set")
    view = {
        "protocol": protocol,
        "request": {"facts": [{"id": "fact_1", "text": "主体于某日履约"}]},
        "disclosed_history": [],
        "auxiliary": [{"candidate_count": 10}],
        "query_budget": 3,
    }
    with TestClient(redteam_app) as client:
        assert client.post("/evaluate", json={"view": view, "signature": "bad"}).status_code == 403
        result = client.post("/evaluate", json={"view": view, "signature": sign(view, "separate-redteam-secret")})
    assert result.status_code == 200
    assert result.json()["outcome"] == "resisted"


def test_formal_attack_job_persists_four_bound_runs(env, monkeypatch):
    monkeypatch.setenv("LEX_REDTEAM_SECRET", "separate-redteam-secret")
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    evaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    auxiliary = {
        "candidate_set": [{"candidate_count": 10}],
        "sensitive_inference": [{"confidence": 0.1}],
    }
    queued = env["client"].post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": auxiliary})
    assert queued.status_code == 200, queued.text
    with LocalRedteam() as redteam:
        assert process_one(env["app"].state.store, env["root"], env["gate"], redteam)
    runs = env["client"].get(f"/api/v1/tasks/{task['id']}/attacks").json()
    assert len(runs) == 4
    assert {item["outcome"] for item in runs} == {"resisted"}
    assert all(item["attack_input_hash"] == evaluated["attack_input_hash"] for item in runs)
    assert all(item["result_hash"] for item in runs)
    reevaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    assert not any("四类冻结攻击" in item for item in reevaluated["risk"]["blockers"])
    assert {item["outcome"] for item in reevaluated["risk"]["attacks"]} == {"resisted"}


def test_changed_disclosure_cannot_reuse_attack_runs(env, monkeypatch):
    monkeypatch.setenv("LEX_REDTEAM_SECRET", "separate-redteam-secret")
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    env["client"].post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": {
        "candidate_set": [{"candidate_count": 10}],
        "sensitive_inference": [{"confidence": 0.1}],
    }})
    with LocalRedteam() as redteam:
        process_one(env["app"].state.store, env["root"], env["gate"], redteam)
    current = task_state(env, case["id"], task["id"])
    decision = current["decisions"][0]
    changed = env["client"].patch(
        f"/api/v1/tasks/{task['id']}/decisions/{decision['fact_id']}",
        json={"transform": "delete", "necessity": "unnecessary"},
    )
    assert changed.status_code == 200
    reevaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    assert {item["outcome"] for item in reevaluated["risk"]["attacks"]} == {"not_run"}


def test_redteam_timeout_is_persisted_as_error(env, monkeypatch):
    class TimeoutClient:
        def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("timeout")

    monkeypatch.setenv("LEX_REDTEAM_SECRET", "separate-redteam-secret")
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    env["client"].post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": {}})
    process_one(env["app"].state.store, env["root"], env["gate"], TimeoutClient())
    runs = env["client"].get(f"/api/v1/tasks/{task['id']}/attacks").json()
    assert len(runs) == 4
    assert {item["outcome"] for item in runs} == {"error"}


def test_recover_marks_interrupted_redteam_runs_error(env):
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    install_protocols(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    job = env["client"].post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": {}}).json()
    with env["app"].state.store.transaction() as repo:
        job["status"] = "running"
        repo.put("job", job, case["id"])
    recover(env["app"].state.store)
    runs = env["client"].get(f"/api/v1/tasks/{task['id']}/attacks").json()
    assert len(runs) == 4
    assert {item["outcome"] for item in runs} == {"error"}


@pytest.mark.parametrize(
    ("protocol", "auxiliary", "outcome"),
    [
        ({"kind": "candidate_set", "threshold": 0.2, "query_budget": 3}, [{"candidate_count": 10}], "resisted"),
        ({"kind": "candidate_set", "threshold": 0.2, "query_budget": 3}, [{"candidate_count": 2}], "succeeded"),
        ({"kind": "candidate_set", "threshold": 0.2, "query_budget": 3}, [], "uncertain"),
        ({"kind": "candidate_set", "threshold": 0.2, "query_budget": 3,
          "success_criteria": {"operator": "invalid"}}, [{"candidate_count": 10}], "error"),
    ],
)
def test_attack_outcomes_are_explicit(protocol, auxiliary, outcome):
    assert evaluate_attack(protocol, {"facts": []}, [], auxiliary)["outcome"] == outcome
