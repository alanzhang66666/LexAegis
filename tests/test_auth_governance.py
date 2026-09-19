from fastapi.testclient import TestClient
from .test_workflow import formal_material


def login(client, username, password):
    return client.post("/api/v1/login", json={"username": username, "password": password})


def provider_payload():
    return {
        "id": "provider_test",
        "name": "合成测试服务商",
        "role": "processor",
        "processing_regions": ["测试区域"],
        "retention": "请求完成后立即删除",
        "training_use": "forbidden",
        "human_access": "controlled",
        "subprocessors": [],
        "subprocessor_status": "none",
        "deletion_mechanism": "合同约定删除接口",
        "contract_reference": "synthetic-contract-ref",
        "impact_assessment_reference": "synthetic-pia-ref",
        "valid_until": "2099-12-31T00:00:00+00:00",
        "allowed_tasks": ["fact_summary"],
        "allowed_domains": ["labor"],
        "allowed_fields": ["entity", "relation", "event", "date", "amount", "evidence"],
        "allowed_transports": ["cloud"],
        "status": "reviewed",
    }


def test_local_accounts_enforce_roles_and_named_audit(env):
    client = env["client"]
    users = client.get("/api/v1/users").json()
    assert len(users) == 1 and users[0]["username"] == "admin"
    assert "password_hash" not in users[0] and "password_salt" not in users[0]
    created = client.post("/api/v1/users", json={
        "username": "operator.one", "display_name": "案件操作员",
        "role": "case_operator", "password": "operator-password-123",
    })
    assert created.status_code == 200, created.text
    client.post("/api/v1/logout")
    assert login(client, "operator.one", "operator-password-123").status_code == 200
    case = client.post("/api/v1/cases", json={"name": "角色权限测试"}).json()
    assert case["id"].startswith("case_")
    assert client.get("/api/v1/users").status_code == 403
    assert client.put("/api/v1/settings", json={
        "cloud_url": "https://api.openai.com/v1", "cloud_model": "",
        "edge_url": "http://localhost:11434/v1", "edge_model": "",
    }).status_code == 403
    detail = client.get("/api/v1/cases/" + case["id"]).json()
    created_event = next(item for item in detail["audit"] if item["event"] == "case.created")
    assert created_event["actor"] == "案件操作员"
    client.post("/api/v1/logout")
    assert login(client, "admin", "unit-test-password").status_code == 200
    assert client.put("/api/v1/users/admin", json={"role": "approver"}).status_code == 409
    disabled = client.put("/api/v1/users/operator.one", json={"status": "disabled"})
    assert disabled.status_code == 200
    client.post("/api/v1/logout")
    assert login(client, "operator.one", "operator-password-123").status_code == 401


def test_local_account_validation_returns_field_errors_instead_of_server_error(env):
    client = env["client"]
    for username, display_name in (("not valid", "测试用户"), ("valid.user", "   ")):
        response = client.post("/api/v1/users", json={
            "username": username, "display_name": display_name,
            "role": "case_operator", "password": "long-enough-password",
        })
        assert response.status_code == 422, response.text
        assert isinstance(response.json()["detail"], list)
    created = client.post("/api/v1/users", json={
        "username": " Upper.User ", "display_name": " 测试用户 ",
        "role": "case_operator", "password": "long-enough-password",
    })
    assert created.status_code == 200, created.text
    assert created.json()["username"] == "upper.user"
    assert created.json()["display_name"] == "测试用户"


def test_provider_lifecycle_requires_complete_profile_and_resets_review(env):
    client = env["client"]
    saved = client.put("/api/v1/providers/provider_test", json=provider_payload())
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "draft" and saved.json()["profile_version"] == 1
    reviewed = client.post("/api/v1/providers/provider_test/review", json={"status": "reviewed"})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "reviewed"
    changed = provider_payload()
    changed["retention"] = "最长保留七日"
    updated = client.put("/api/v1/providers/provider_test", json=changed)
    assert updated.status_code == 200
    assert updated.json()["status"] == "draft"
    assert updated.json()["profile_version"] == reviewed.json()["profile_version"] + 1
    assert client.delete("/api/v1/providers/provider_test").status_code == 200


def test_disabled_session_is_rejected_on_next_request(env):
    client = env["client"]
    client.post("/api/v1/users", json={
        "username": "reviewer.one", "display_name": "复核律师",
        "role": "legal_reviewer", "password": "reviewer-password-123",
    })
    client.post("/api/v1/logout")
    login(client, "reviewer.one", "reviewer-password-123")
    with env["app"].state.store.transaction() as repo:
        user = repo.get("user:reviewer.one", "user")
        user["status"] = "disabled"
        repo.put("user", user)
    assert client.get("/api/v1/bootstrap").status_code == 401


def test_provider_change_invalidates_frozen_task_dependencies(env):
    client=env["client"]
    client.put("/api/v1/providers/provider_test",json=provider_payload())
    settings=client.get("/api/v1/bootstrap").json()["settings"]
    body={key:settings[key] for key in ("cloud_url","cloud_model","edge_url","edge_model","deployment_mode","isolation_verified")}
    body["provider_id"]="provider_test"
    assert client.put("/api/v1/settings",json=body).status_code==200
    case,_,_=formal_material(env)
    task=client.post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"cloud"}).json()
    evaluated=client.post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    changed=provider_payload();changed["retention"]="已变更的留存条件"
    client.put("/api/v1/providers/provider_test",json=changed)
    from tests.conftest import post_as
    result=post_as(env, "approver", f"/api/v1/tasks/{task['id']}/approve",json={"request_hash":evaluated["request_hash"]})
    assert result.status_code==409 and "服务商档案已变化" in result.text
