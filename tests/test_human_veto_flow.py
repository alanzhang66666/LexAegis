"""End-to-end API checks for human review, authorization, and send cancellation."""
import pytest
from fastapi.testclient import TestClient

from lexaegis.api import create_app
from lexaegis.worker import process_one


ADMIN_PASSWORD = "unit-test-password"
USERS = {
    "operator": ("operator.one", "operator-password-123", "case_operator"),
    "technical": ("technical.one", "technical-password-123", "technical_reviewer"),
    "legal": ("legal.one", "legal-review-password-123", "legal_reviewer"),
    "approver": ("approver.one", "approver-password-123", "approver"),
}


@pytest.fixture
def veto_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    monkeypatch.setenv("LEX_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("LEX_GATEWAY_SECRET", "unit-test-secret-32-characters-long")
    monkeypatch.setenv("LEX_GATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("LEX_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_PRIMARY_KEY", raising=False)
    monkeypatch.delenv("LEX_CLOUD_STANDBY_KEY", raising=False)
    app = create_app(tmp_path / "app", password=ADMIN_PASSWORD)
    with TestClient(app) as client:
        assert client.post("/api/v1/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
        for username, password, role in USERS.values():
            created = client.post("/api/v1/users", json={
                "username": username, "display_name": username, "role": role, "password": password,
            })
            assert created.status_code == 200, created.text
        yield {"app": app, "client": client, "root": tmp_path / "app"}


def _login(client, username="admin", password=ADMIN_PASSWORD):
    client.post("/api/v1/logout")
    response = client.post("/api/v1/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _role(client, name):
    username, password, _role_name = USERS[name]
    return _login(client, username, password)


def _prepared_task(env, scenario="human_veto"):
    client = env["client"]
    case_response = client.post("/api/v1/demos", json={"scenario": scenario})
    assert case_response.status_code == 200, case_response.text
    case = case_response.json()
    task_response = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "mock"})
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()
    _role(client, "operator")
    result = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert result.status_code == 200, result.text
    return case, result.json()


def _refs(client, task):
    packs = client.get("/api/v1/bootstrap").json()["packs"]
    pack = next(item for item in packs if item["id"] == task["pack_id"])
    assert pack["legal_sources"], "demo review must have a controlled project source"
    assert pack["manual_review_conditions"], "demo review must have a selectable condition"
    return pack["legal_sources"][0]["id"], pack["manual_review_conditions"][0]["id"]


def _legal_body(task, source_id, condition_id, *, conclusion="reject_current_request", key="legal-review-key-01", resolved=(), resolution_reason=""):
    return {
        "request_hash": task["request_hash"],
        "material_version": task["request"]["dependencies"]["case_revision"],
        "idempotency_key": key,
        "conclusion": conclusion,
        "reason": "保留的岗位、园区和活动日期组合可能识别具体主体。",
        "reviewed_condition_ids": [condition_id],
        "legal_source_ids": [source_id],
        "evidence_ids": ["synthetic_public_record"],
        "resolved_issue_ids": list(resolved),
        "resolution_reason": resolution_reason,
        "acknowledged_risk_notices": True,
        "scope_note": "仅适用于当前请求和当前材料版本。",
        "fact_premise": "姓名已令牌化，但补充合成资料与保留线索指向同一主体。",
        "authority_judgment": "当前请求尚未获得发送批准。",
        "external_processing_note": "本次拟使用模拟服务，不发送真实个人信息。",
        "minimization_note": "应移除非必要的岗位、地点及活动日期。",
        "final_basis": "依当前规则包的人工复核事项和合成补充证据作出判断。",
    }


def test_named_technical_and_legal_veto_blocks_and_cannot_be_bypassed(veto_env):
    client = veto_env["client"]
    case, task = _prepared_task(veto_env)
    assert task["risk"]["approval_allowed"] is True
    original_risk_result = task["risk"]["approval_allowed"]
    issue_body = {
        "request_hash": task["request_hash"], "idempotency_key": "technical-issue-key-01",
        "reason": "岗位、园区和活动日期组合可关联到同一人。",
        "evidence_ids": ["synthetic_public_record"],
    }

    # Admin and legal review accounts cannot submit the technical finding.
    _login(client)
    assert client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=issue_body).status_code == 403
    _role(client, "legal")
    assert client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=issue_body).status_code == 403

    _role(client, "technical")
    submitted = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=issue_body)
    assert submitted.status_code == 200, submitted.text
    replay = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=issue_body)
    assert replay.status_code == 200, replay.text
    details = client.get(f"/api/v1/cases/{case['id']}").json()
    paused = next(item for item in details["tasks"] if item["id"] == task["id"])
    assert paused["review_status"] == "blocked"
    assert paused["status"] == "review_blocked"
    assert paused["approval"] is None
    assert paused["risk"]["approval_allowed"] is original_risk_result
    assert len(paused["review_issues"]) == 1
    assert len([event for event in paused["review_events"] if event["event_type"] == "technical_issue_submitted"]) == 1

    source_id, condition_id = _refs(client, task)
    legal_body = _legal_body(task, source_id, condition_id)
    # A technical reviewer cannot issue the legal veto.
    assert client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=legal_body).status_code == 403
    _role(client, "approver")
    assert client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=legal_body).status_code == 403

    _role(client, "legal")
    rejected = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=legal_body)
    assert rejected.status_code == 200, rejected.text
    replay = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=legal_body)
    assert replay.status_code == 200, replay.text
    details = client.get(f"/api/v1/cases/{case['id']}").json()
    rejected_task = next(item for item in details["tasks"] if item["id"] == task["id"])
    assert rejected_task["review_status"] == "rejected"
    assert rejected_task["status"] == "rejected"
    assert rejected_task["approval"] is None
    assert rejected_task["risk"]["approval_allowed"] is original_risk_result
    assert rejected_task["legal_review"]["conclusion"] == "reject_current_request"
    assert len([event for event in rejected_task["review_events"] if event["event_type"] == "legal_review_recorded"]) == 1

    # Neither an old approval nor reevaluation, direct task creation, or a
    # successor task can bypass the still-open case-level veto.
    _role(client, "operator")
    assert client.post(f"/api/v1/tasks/{task['id']}/evaluate").status_code == 409
    _role(client, "approver")
    assert client.post(f"/api/v1/tasks/{task['id']}/approve", json={"request_hash": task["request_hash"]}).status_code == 409
    _role(client, "operator")
    assert client.post(f"/api/v1/tasks/{task['id']}/send").status_code == 409
    for parent in (task["id"], None):
        body = {"transport": "mock", "task_type": "fact_summary"}
        if parent:
            body["parent_task_id"] = parent
        created = client.post(f"/api/v1/cases/{case['id']}/tasks", json=body)
        assert created.status_code == 200, created.text
        next_task = created.json()
        assert next_task["review_status"] == "blocked"
        assert next_task.get("inherited_review_issue_ids")
        reevaluated = client.post(f"/api/v1/tasks/{next_task['id']}/evaluate")
        assert reevaluated.status_code == 200, reevaluated.text
        assert reevaluated.json()["review_status"] == "blocked"
        _role(client, "approver")
        assert client.post(f"/api/v1/tasks/{next_task['id']}/approve", json={"request_hash": reevaluated.json()["request_hash"]}).status_code == 409
        _role(client, "operator")


def test_allow_processing_requires_explicit_resolution_and_still_needs_approver(veto_env):
    client = veto_env["client"]
    _case, task = _prepared_task(veto_env)
    _role(client, "technical")
    issue = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json={
        "request_hash": task["request_hash"], "idempotency_key": "technical-issue-key-02",
        "reason": "复核补充资料中的组合线索。", "evidence_ids": ["synthetic_public_record"],
    })
    assert issue.status_code == 200, issue.text
    task_detail = client.get(f"/api/v1/cases/{task['case_id']}").json()["tasks"][-1]
    issue_id = task_detail["review_issues"][0]["id"]
    source_id, condition_id = _refs(client, task)
    body = _legal_body(task, source_id, condition_id, conclusion="allow_processing", key="legal-resolution-02")
    _role(client, "legal")
    incomplete = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=body)
    assert incomplete.status_code == 409 and "resolved_issue_ids" in incomplete.text
    body.update(resolved_issue_ids=[issue_id], resolution_reason="删除园区、夜班岗位和活动日期后，原识别线索已不再进入请求。")
    allowed = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=body)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["review_status"] == "cleared"
    assert allowed.json()["approval"] is None
    assert allowed.json()["status"] == "review"
    _role(client, "operator")
    assert client.post(f"/api/v1/tasks/{task['id']}/send").status_code == 409
    _role(client, "approver")
    approved = client.post(f"/api/v1/tasks/{task['id']}/approve", json={"request_hash": task["request_hash"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval"]["actor_role"] == "approver"
    assert approved.json()["status"] == "approved"


def test_allow_after_minimization_remains_blocked_and_worker_cancels_running_send(veto_env):
    client = veto_env["client"]
    case, task = _prepared_task(veto_env)
    original_risk_result = task["risk"]["approval_allowed"]
    _role(client, "technical")
    issue = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json={
        "request_hash": task["request_hash"], "idempotency_key": "technical-issue-key-03",
        "reason": "请求含可关联的组合线索。", "evidence_ids": ["synthetic_public_record"],
    })
    assert issue.status_code == 200, issue.text
    source_id, condition_id = _refs(client, task)
    _role(client, "legal")
    body = _legal_body(task, source_id, condition_id, conclusion="allow_after_minimization", key="legal-minimize-03")
    result = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["review_status"] == "blocked"
    assert result.json()["status"] == "review_blocked"
    assert result.json()["risk"]["approval_allowed"] is original_risk_result
    assert result.json()["approval"] is None

    # On a separate cleared demo task, queue a send, emulate the worker's
    # running-before-send window, then ensure the technical pause cancels it.
    _role(client, "operator")
    fresh_case_response = client.post("/api/v1/demos", json={"scenario": "success"})
    fresh_case = fresh_case_response.json()
    fresh_task = client.post(f"/api/v1/cases/{fresh_case['id']}/tasks", json={"transport": "mock"}).json()
    evaluated = client.post(f"/api/v1/tasks/{fresh_task['id']}/evaluate").json()
    source_id, condition_id = _refs(client, evaluated)
    _role(client, "legal")
    body = _legal_body(evaluated, source_id, condition_id, conclusion="allow_processing", key="legal-clear-03")
    body["evidence_ids"] = [evaluated["fact_snapshot"][0]["id"]]
    cleared = client.post(f"/api/v1/tasks/{fresh_task['id']}/legal-review", json=body)
    assert cleared.status_code == 200, cleared.text
    _role(client, "approver")
    approved = client.post(f"/api/v1/tasks/{fresh_task['id']}/approve", json={"request_hash": evaluated["request_hash"]})
    assert approved.status_code == 200, approved.text
    _role(client, "operator")
    queued = client.post(f"/api/v1/tasks/{fresh_task['id']}/send")
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["id"]
    with veto_env["app"].state.store.transaction() as repo:
        job = repo.get(job_id, "job")
        job["status"] = "running"
        repo.put("job", job, job["case_id"])
    _role(client, "technical")
    pause = client.post(f"/api/v1/tasks/{fresh_task['id']}/review-issues", json={
        "request_hash": evaluated["request_hash"], "idempotency_key": "technical-issue-key-04",
        "reason": "发送尚未开始前发现需暂停的线索。", "evidence_ids": [fresh_task["fact_snapshot"][0]["id"]],
    })
    assert pause.status_code == 200, pause.text
    with veto_env["app"].state.store.read() as repo:
        assert repo.get(job_id, "job")["status"] == "cancelled"
        assert repo.get(fresh_task["id"], "task")["status"] == "review_blocked"
    assert process_one(veto_env["app"].state.store, veto_env["root"]) is False

    with veto_env["app"].state.store.transaction() as repo:
        stored = repo.get(fresh_task["id"], "task")
        stored["status"] = "sending"
        repo.put("task", stored, stored["case_id"])
    after_sending = client.post(f"/api/v1/tasks/{fresh_task['id']}/review-issues", json={
        "request_hash": evaluated["request_hash"], "idempotency_key": "technical-issue-key-05",
        "reason": "发送已经开始后的复核。", "evidence_ids": [fresh_task["fact_snapshot"][0]["id"]],
    })
    assert after_sending.status_code == 409
    with veto_env["app"].state.store.read() as repo:
        assert repo.get(fresh_task["id"], "task")["status"] == "sending"
