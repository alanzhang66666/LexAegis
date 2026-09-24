"""HTTP publication creates a usable, scoped pack but never a send grant."""
import hashlib
import json
import pytest

from .conftest import login_admin, login_as
from .test_runtime_pack import SOURCE_PACK, RISK_WEIGHTS
from .test_workflow import formal_material

BASE = "/api/v1/formal-release/runtime-packs"


def prepare(env):
    source = json.loads(SOURCE_PACK.read_text(encoding="utf-8"))
    source["version"] = "2.1.0-product-draft"
    response = env["client"].post(BASE, json={
        "source_pack": source, "import_report": {"status": "pending_review"},
        "scope_kind": "request",
    })
    assert response.status_code == 200, response.text
    return response.json()


def review_body(env, case_id):
    response = env["client"].post("/api/v1/formal-release/evidence",
        params={"template_kind": "法05"},
        files={"file": ("synthetic-law05.txt", b"synthetic test review; not a real approval", "text/plain")})
    assert response.status_code == 200, response.text
    return {
        "review_record": "TEST-LAW05-CUS-001", "law_05_evidence_id": response.json()["id"],
        "published_scope": {"case_id": case_id, "purpose": "R_fact_summary", "recipient": "primary"},
        "risk_weights": RISK_WEIGHTS, "references": ["synthetic-review-only"],
        "dispatch_allowed": True,
    }


def published(env, case_id):
    draft = prepare(env)
    body = review_body(env, case_id)
    login_as(env, "legal_reviewer")
    result = env["client"].post(f"{BASE}/{draft['id']}/review", json=body)
    assert result.status_code == 200, result.text
    result = env["client"].post(f"{BASE}/{draft['id']}/publish")
    assert result.status_code == 200, result.text
    login_admin(env)
    with env["app"].state.store.transaction() as repo:
        settings = repo.get("settings")
        settings["cloud_primary"]["provider_id"] = "primary"
        repo.put("settings", settings)
    return result.json()


def test_production_runtime_pack_has_real_role_boundary_and_controlled_evidence(env):
    draft = prepare(env)
    assert draft["status"] == "draft" and not draft["dispatch_allowed"]
    body = review_body(env, "CUS-001")
    client = env["client"]
    assert client.post(f"{BASE}/{draft['id']}/review", json=body).status_code == 403
    login_as(env, "technical_reviewer")
    assert client.post(f"{BASE}/{draft['id']}/review", json=body).status_code == 403
    login_as(env, "legal_reviewer")
    missing = {**body, "law_05_evidence_id": "nonexistent"}
    assert client.post(f"{BASE}/{draft['id']}/review", json=missing).status_code in {404, 409}
    assert client.post(f"{BASE}/{draft['id']}/review", json={**body, "dispatch_allowed": False}).status_code == 409
    with env["app"].state.store.read() as repo:
        assert repo.get(draft["id"], "runtime_pack")["status"] == "draft"
        assert not repo.list("runtime_pack_activation")
        assert not repo.list("one_time_dispatch_grant")


def test_published_pack_is_usable_only_in_exact_case_and_export_matches_build_hash(env):
    case, _, _ = formal_material(env)
    value = published(env, case["id"])
    client = env["client"]
    active = value["active_pack"]
    result = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud", "pack_id": active["id"]})
    assert result.status_code == 200, result.text
    assert result.json()["pack_id"] == active["id"]
    other, _, _ = formal_material(env)
    assert client.post(f"/api/v1/cases/{other['id']}/tasks",
        json={"transport": "cloud", "pack_id": active["id"]}).status_code == 409
    exported = client.get(f"{BASE}/{value['runtime_pack']['id']}/export")
    assert exported.status_code == 200
    with env["app"].state.store.read() as repo:
        activation = repo.get(f"activation:{active['id']}", "runtime_pack_activation")
        assert activation["artifact_sha256"] == "sha256:" + hashlib.sha256(exported.content).hexdigest()
        assert not repo.list("formal_release_policy")
        assert not repo.list("one_time_dispatch_grant")
    assert client.post(f"/api/v1/tasks/{result.json()['id']}/send").status_code == 409


def test_retiring_active_pack_cancels_queued_task_preserving_rejected_history(env):
    case, _, _ = formal_material(env)
    value = published(env, case["id"])
    client = env["client"]
    task = client.post(f"/api/v1/cases/{case['id']}/tasks",
        json={"transport": "cloud", "pack_id": value["active_pack"]["id"]}).json()
    with env["app"].state.store.transaction() as repo:
        task.update(status="queued", approval={"request_hash": "old"})
        repo.put("task", task, case["id"])
        repo.put("job", {"id": "job:test-send", "kind": "send", "status": "pending",
                         "payload": {"task_id": task["id"]}, "case_id": case["id"]}, case["id"])
        rejected = {**task, "id": "task:rejected", "status": "rejected", "approval": None}
        repo.put("task", rejected, case["id"])
    login_as(env, "legal_reviewer")
    retired = client.post(f"{BASE}/{value['runtime_pack']['id']}/retire", json={"reason": "测试发现规则需修订"})
    assert retired.status_code == 200, retired.text
    with env["app"].state.store.read() as repo:
        current = repo.get(task["id"], "task")
        assert current["stale"] and current["approval"] is None
        assert repo.get("job:test-send", "job")["status"] == "cancelled"
        assert repo.get(rejected["id"], "task")["status"] == "rejected"
        assert repo.get(value["active_pack"]["id"], "pack")["status"] == "retired"


@pytest.mark.parametrize("environment", ["demo_env", "integration_env"])
def test_runtime_publication_routes_are_absent_from_demo_and_integration(request, environment):
    env = request.getfixturevalue(environment)
    assert env["client"].get(BASE).status_code == 404


def test_product_case_reference_is_not_limited_to_pilot(env):
    client = env["client"]
    result = client.post("/api/v1/cases", json={"name": "常规案件", "reference_code": "CUS-002"})
    assert result.status_code == 200, result.text
    assert result.json()["reference_code"] == "CUS-002"
    assert client.post("/api/v1/cases", json={"name": "重复编号", "reference_code": "CUS-002"}).status_code == 409


def test_reusable_rules_work_for_two_cases_but_not_another_recipient(env):
    first, _, _ = formal_material(env)
    second, _, _ = formal_material(env)
    draft = prepare(env)
    body = review_body(env, first["id"])
    body["published_scope"] = {"domain": "labor", "purpose": "R_fact_summary", "recipient": "primary"}
    login_as(env, "legal_reviewer")
    client = env["client"]
    assert client.post(f"{BASE}/{draft['id']}/review", json=body).status_code == 200
    response = client.post(f"{BASE}/{draft['id']}/publish")
    assert response.status_code == 200, response.text
    active = response.json()["active_pack"]
    login_admin(env)
    with env["app"].state.store.transaction() as repo:
        settings = repo.get("settings")
        settings["cloud_primary"]["provider_id"] = "primary"
        repo.put("settings", settings)
    for case in (first, second):
        result = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud", "pack_id": active["id"]})
        assert result.status_code == 200, result.text
        assert result.json()["pack_id"] == active["id"]
    with env["app"].state.store.transaction() as repo:
        settings = repo.get("settings")
        settings["cloud_primary"]["provider_id"] = "different-provider"
        repo.put("settings", settings)
    assert client.post(f"/api/v1/cases/{first['id']}/tasks",
        json={"transport": "cloud", "pack_id": active["id"]}).status_code == 409
