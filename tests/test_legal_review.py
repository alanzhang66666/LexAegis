from lexaegis.service import LEGAL_REVIEW_SCOPE
from tests.conftest import demo_task


def _review_body(**extra):
    body = {
        "conclusion": "allow_processing",
        "reason": "当前为演示合成材料，复核记录不授予发送权。",
        "reviewed_condition_ids": ["rule_necessity_uncertain"],
        "legal_source_ids": ["spc_labor_interp_1"],
        "acknowledged_risk_notices": True,
        "fact_premise": "当前材料为演示合成样本，未确认真实身份。",
        "authority_judgment": "演示账号仅有工作台复核权限，不包含发送授权。",
        "external_processing_note": "本次不调用外部服务商，不发生跨境传输。",
        "minimization_note": "已按演示规则删除或替换直接标识。",
        "final_basis": "复核仅留痕，不改变 approval_allowed，不授予发送权。",
        "scope_note": LEGAL_REVIEW_SCOPE,
    }
    body.update(extra)
    return body


def test_legal_review_does_not_grant_dispatch(env):
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.json()
    allowed = body["risk"]["approval_allowed"]
    result = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=_review_body(request_hash=body["request_hash"]))
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["legal_review"]["conclusion"] == "allow_processing"
    assert payload["legal_review"]["fact_premise"]
    assert payload["legal_review"]["final_basis"]
    assert payload["risk"]["approval_allowed"] == allowed
    assert payload["status"] != "approved" or allowed
    caps = client.get("/api/v1/capabilities").json()
    assert caps["validation"]["formal_dispatch"] == "blocked"


def test_legal_review_rejects_stale_hash(env):
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200
    result = client.post(f"/api/v1/tasks/{task['id']}/legal-review", json=_review_body(request_hash="0" * 64))
    assert result.status_code >= 400


def test_legal_review_rejects_incomplete_record(env):
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200
    body = evaluated.json()
    allowed = body["risk"]["approval_allowed"]
    result = client.post(
        f"/api/v1/tasks/{task['id']}/legal-review",
        json=_review_body(request_hash=body["request_hash"], fact_premise=""),
    )
    assert result.status_code >= 400
    again = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert again.status_code == 200
    assert again.json()["risk"]["approval_allowed"] == allowed
    caps = client.get("/api/v1/capabilities").json()
    assert caps["validation"]["formal_dispatch"] == "blocked"
