from lexaegis.service import authorize_dispatch
from lexaegis.worker import process_one
from .conftest import approve, demo_task
from .test_auth_governance import provider_payload
from .test_workflow import task_state


def _cloud_settings(client, standby=None, primary_provider=None):
    settings = client.get("/api/v1/bootstrap").json()["settings"]
    body = {key: settings[key] for key in (
        "cloud_url", "cloud_model", "edge_url", "edge_model", "deployment_mode", "isolation_verified",
    )}
    body["cloud_url"] = "https://api.openai.com/v1"
    body["cloud_model"] = "test-model"
    body["cloud_primary"] = {
        "url": "https://api.openai.com/v1", "model": "test-model", "provider_id": primary_provider,
    }
    body["cloud_standby"] = standby or {"url": "", "model": "", "provider_id": None}
    body["provider_id"] = primary_provider
    assert client.put("/api/v1/settings", json=body).status_code == 200


def test_unreviewed_standby_is_not_an_approved_target(env):
    client = env["client"]
    payload = provider_payload()
    payload["id"] = "provider_standby"
    assert client.put("/api/v1/providers/provider_standby", json=payload).status_code == 200
    _cloud_settings(client, standby={
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-flash",
        "provider_id": "provider_standby",
    })
    _case, task = demo_task(env, transport="cloud")
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    dual = evaluated["request"]["dependencies"]["dual_slot"]
    assert dual["primary"]["model"] == "test-model"
    assert "standby" not in dual
    assert "未纳入批准目标" in evaluated["request"]["dependencies"]["standby_note"]
    assert all(item.get("slot") != "standby" for item in evaluated["request"]["dependencies"]["authorized_recipients"])


def test_reviewed_standby_is_bound_into_approved_targets(env):
    client = env["client"]
    payload = provider_payload()
    payload["id"] = "provider_standby"
    payload["endpoint"] = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload["model"] = "qwen3.8-flash"
    assert client.put("/api/v1/providers/provider_standby", json=payload).status_code == 200
    assert client.post("/api/v1/providers/provider_standby/review", json={"status": "reviewed"}).status_code == 200
    _cloud_settings(client, standby={
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-flash",
        "provider_id": "provider_standby",
    })
    _case, task = demo_task(env, transport="cloud")
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    dual = evaluated["request"]["dependencies"]["dual_slot"]
    assert dual["standby"]["model"] == "qwen3.8-flash"
    assert dual["standby"]["provider_id"] == "provider_standby"
    assert evaluated["request"]["dependencies"]["standby_provider_hash"]
    assert any(item.get("slot") == "standby" for item in evaluated["request"]["dependencies"]["authorized_recipients"])


def test_queued_send_is_rejected_after_pack_retirement(env):
    case, task = demo_task(env)
    task = approve(env, task)
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/send").status_code == 200
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        pack = repo.get(stored["pack_id"], "pack")
        pack["status"] = "retired"
        repo.put("pack", pack)
        try:
            authorize_dispatch(repo, stored, phase="send")
            raised = False
        except Exception as error:
            raised = True
            assert "退役" in str(error)
        assert raised

    class ForbiddenGateway:
        def post(self, *args, **kwargs):
            raise AssertionError("queued send must not leave local after retirement")

        def get(self, *args, **kwargs):
            raise AssertionError("queued send must not query gateway after retirement")

    assert process_one(env["app"].state.store, env["root"], ForbiddenGateway())
    finished = task_state(env, case["id"], task["id"])
    assert finished["status"] == "failed"
    assert "退役" in (finished.get("error") or "")
