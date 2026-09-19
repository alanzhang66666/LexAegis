from lexaegis.service import LEGAL_REVIEW_SCOPE
from tests.conftest import demo_task, post_as


def _review_body(env, task, request_hash, **extra):
    client = env["client"]
    pack = next(item for item in client.get("/api/v1/domains").json() if item["id"] == task["pack_id"])
    conditions = pack.get("manual_review_conditions") or []
    if not conditions:
        conditions = [condition for rule in pack.get("rules", []) for condition in rule.get("conditions", [])]
    case = client.get(f"/api/v1/cases/{task['case_id']}").json()["case"]
    body = {
        "conclusion": "allow_processing",
        "reason": "当前为演示合成材料，复核记录不授予发送权。",
        "reviewed_condition_ids": [conditions[0]["id"]],
        "legal_source_ids": [pack["legal_sources"][0]["id"]],
        "evidence_ids": [task["fact_snapshot"][0]["id"]],
        "acknowledged_risk_notices": True,
        "fact_premise": "当前材料为演示合成样本，未确认真实身份。",
        "authority_judgment": "演示账号仅有工作台复核权限，不包含发送授权。",
        "external_processing_note": "本次不调用外部服务商，不发生跨境传输。",
        "minimization_note": "已按演示规则删除或替换直接标识。",
        "final_basis": "复核仅留痕，不改变 approval_allowed，不授予发送权。",
        "scope_note": LEGAL_REVIEW_SCOPE,
        "material_version": case["revision"],
        "idempotency_key": f"legal-review-test-{task['id']}",
        "request_hash": request_hash,
    }
    body.update(extra)
    return body


def test_legal_review_does_not_grant_dispatch(demo_env):
    env = demo_env
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.json()
    allowed = body["risk"]["approval_allowed"]
    result = post_as(env, "legal_reviewer", f"/api/v1/tasks/{task['id']}/legal-review", json=_review_body(env, task, body["request_hash"]))
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["legal_review"]["conclusion"] == "allow_processing"
    assert payload["legal_review"]["fact_premise"]
    assert payload["legal_review"]["final_basis"]
    assert payload["risk"]["approval_allowed"] == allowed
    assert payload["status"] != "approved" or allowed
    caps = client.get("/api/v1/capabilities").json()
    assert caps["validation"]["formal_dispatch"] == "blocked"


def test_legal_review_rejects_stale_hash(demo_env):
    env = demo_env
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200
    result = post_as(env, "legal_reviewer", f"/api/v1/tasks/{task['id']}/legal-review", json=_review_body(env, task, "0" * 64))
    assert result.status_code >= 400


def test_legal_review_rejects_incomplete_record(demo_env):
    env = demo_env
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200
    body = evaluated.json()
    allowed = body["risk"]["approval_allowed"]
    result = post_as(env, "legal_reviewer",
        f"/api/v1/tasks/{task['id']}/legal-review",
        json=_review_body(env, task, body["request_hash"], fact_premise=""),
    )
    assert result.status_code >= 400
    again = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert again.status_code == 200
    assert again.json()["risk"]["approval_allowed"] == allowed
    caps = client.get("/api/v1/capabilities").json()
    assert caps["validation"]["formal_dispatch"] == "blocked"
