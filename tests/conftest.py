import pytest
from fastapi.testclient import TestClient
from lexaegis.api import create_app
from lexaegis.gateway import create_gateway


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_GATEWAY_SECRET", "unit-test-secret-32-characters-long")
    monkeypatch.setenv("LEX_GATEWAY_URL", "http://testserver")
    monkeypatch.delenv("LEX_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    app = create_app(tmp_path/"app", password="unit-test-password")
    gateway = create_gateway(tmp_path/"gateway", secret="unit-test-secret-32-characters-long")
    with TestClient(app) as client, TestClient(gateway) as gate:
        assert client.post("/api/v1/login",json={"password":"unit-test-password"}).status_code == 200
        yield {"client":client,"gate":gate,"app":app,"gateway":gateway,"root":tmp_path/"app","temp":tmp_path}


def demo_task(env, scenario="success", transport="mock"):
    client=env["client"]
    case=client.post("/api/v1/demos",json={"scenario":scenario}).json()
    task=client.post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":transport}).json()
    return case,task


def approve(env, task):
    client=env["client"]
    risk=client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert risk.status_code==200, risk.text
    assert not risk.json()["risk"]["blockers"], risk.text
    result=client.post(f"/api/v1/tasks/{task['id']}/approve",json={"request_hash":risk.json()["request_hash"]})
    assert result.status_code==200,result.text
    return result.json()
