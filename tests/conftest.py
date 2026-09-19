import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lexaegis.api import create_app
from lexaegis.gateway import create_gateway

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_FILES = (
    EXAMPLES / "synthetic_labor.docx",
    EXAMPLES / "synthetic_scan.pdf",
)


@pytest.fixture(scope="session", autouse=True)
def ensure_examples():
    if all(path.exists() for path in EXAMPLE_FILES):
        return
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "make_examples.py"))
    missing = [str(path) for path in EXAMPLE_FILES if not path.exists()]
    if missing:
        raise RuntimeError("未能生成示例材料: " + ", ".join(missing))


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from _make_env(tmp_path, monkeypatch, "production")


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    yield from _make_env(tmp_path, monkeypatch, "demo")


@pytest.fixture
def integration_env(tmp_path, monkeypatch):
    yield from _make_env(tmp_path, monkeypatch, "integration")


def _make_env(tmp_path, monkeypatch, profile):
    monkeypatch.setenv("LEX_RUN_PROFILE", profile)
    monkeypatch.setenv("LEX_GATEWAY_SECRET", "unit-test-secret-32-characters-long")
    monkeypatch.setenv("LEX_GATEWAY_URL", "http://testserver")
    monkeypatch.delenv("LEX_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_PRIMARY_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_STANDBY_KEY", raising=False)
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    app = create_app(tmp_path / "app", password="unit-test-password")
    gateway = create_gateway(tmp_path / "gateway", secret="unit-test-secret-32-characters-long")
    with TestClient(app) as client, TestClient(gateway) as gate:
        assert client.post("/api/v1/login", json={"password": "unit-test-password"}).status_code == 200
        yield {"client": client, "gate": gate, "app": app, "gateway": gateway,
               "root": tmp_path / "app", "temp": tmp_path, "profile": profile, "users": {}}


def login_as(env, role):
    client = env["client"]
    if role not in env["users"]:
        credentials = {
            "case_operator": ("operator.test", "operator-test-password-123"),
            "technical_reviewer": ("tech.reviewer", "technical-review-password-123"),
            "legal_reviewer": ("legal.reviewer", "legal-review-password-123"),
            "approver": ("approver.test", "approver-test-password-123"),
        }
        username, password = credentials[role]
        login_admin(env)
        response = client.post("/api/v1/users", json={
            "username": username, "display_name": role, "role": role, "password": password,
        })
        assert response.status_code == 200, response.text
        env["users"][role] = (username, password)
    username, password = env["users"][role]
    client.post("/api/v1/logout")
    result = client.post("/api/v1/login", json={"username": username, "password": password})
    assert result.status_code == 200, result.text
    return result.json()


def login_admin(env):
    client = env["client"]
    client.post("/api/v1/logout")
    result = client.post("/api/v1/login", json={"password": "unit-test-password"})
    assert result.status_code == 200, result.text


def post_as(env, role, path, **kwargs):
    login_as(env, role)
    result = env["client"].post(path, **kwargs)
    login_admin(env)
    return result


def demo_task(env, scenario="success", transport="mock"):
    client = env["client"]
    case = client.post("/api/v1/demos", json={"scenario": scenario}).json()
    task = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": transport}).json()
    return case, task


def approve(env, task):
    client = env["client"]
    risk = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert risk.status_code == 200, risk.text
    assert not risk.json()["risk"]["blockers"], risk.text
    request_hash = risk.json()["request_hash"]
    case = client.get(f"/api/v1/cases/{task['case_id']}").json()["case"]
    pack = next(item for item in client.get("/api/v1/domains").json() if item["id"] == task["pack_id"])
    conditions = pack.get("manual_review_conditions") or []
    if not conditions:
        conditions = [condition for rule in pack.get("rules", []) for condition in rule.get("conditions", [])]
    sources = pack.get("legal_sources") or []
    assert conditions and sources, "approval fixture requires registered pack review references"
    review_body = {
        "request_hash": request_hash,
        "material_version": case["revision"],
        "idempotency_key": f"legal-test-{task['id']}",
        "conclusion": "allow_processing",
        "reason": "测试中由具名法学复核人员审阅合成请求。",
        "evidence_ids": [task["fact_snapshot"][0]["id"]],
        "reviewed_condition_ids": [conditions[0]["id"]],
        "legal_source_ids": [sources[0]["id"]],
        "acknowledged_risk_notices": True,
        "scope_note": "仅适用于当前合成请求，不授予发送权。",
        "fact_premise": "材料为仓库内合成案例。",
        "authority_judgment": "测试请求不扩展授权范围。",
        "external_processing_note": "仅审阅本次请求，不发生未授权的外部处理。",
        "minimization_note": "披露内容按当前任务限定。",
        "final_basis": "复核结论与当前请求绑定。",
    }
    login_as(env, "legal_reviewer")
    reviewed = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=review_body)
    assert reviewed.status_code == 200, reviewed.text
    login_as(env, "approver")
    result = client.post(f"/api/v1/tasks/{task['id']}/approve", json={"request_hash": request_hash})
    login_admin(env)
    assert result.status_code == 200, result.text
    return result.json()
