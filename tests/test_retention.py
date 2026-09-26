"""Data lifecycle: retention policy, case erasure, provider deletion requests."""
from datetime import datetime, timedelta, timezone

from tests.conftest import login_admin


def _formal_case(env):
    response = env["client"].post("/api/v1/cases", json={"name": "删除测试案件", "domain": "labor"})
    assert response.status_code == 200, response.text
    return response.json()


def _upload(env, case_id, name="note.txt", data=b"sensitive body"):
    response = env["client"].post(
        f"/api/v1/cases/{case_id}/documents",
        files={"file": (name, data, "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()["payload"]["document_id"]


def test_policy_defaults_to_fail_closed(env):
    policy = env["client"].get("/api/v1/retention/policy").json()
    assert all(value is None for value in policy.values())
    assert set(policy) == {"originals", "mapping", "frozen_payloads", "audit", "backups", "pia_records"}


def test_pia_records_floor_three_years(env):
    bad = env["client"].put("/api/v1/retention/policy",
                            json={"policy": {"pia_records": 365}})
    assert bad.status_code == 400
    ok = env["client"].put("/api/v1/retention/policy",
                           json={"policy": {"pia_records": 3 * 365, "originals": 30}})
    assert ok.status_code == 200
    assert ok.json()["pia_records"] == 1095
    assert ok.json()["originals"] == 30
    assert ok.json()["audit"] is None


def test_unknown_field_rejected(env):
    result = env["client"].put("/api/v1/retention/policy",
                               json={"policy": {"secrets": 1}})
    assert result.status_code == 400


def test_sweep_purges_only_configured_classes(env):
    case = _formal_case(env)
    doc_id = _upload(env, case["id"])
    env["client"].put("/api/v1/retention/policy", json={"policy": {"originals": 1}})
    # 伪造材料的创建时间到 40 天前，触发 originals 到期
    store = env["app"].state.store
    root = env["root"]
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with store.transaction() as repo:
        case_body = repo.get(case["id"], "case")
        case_body["created_at"] = old
        repo.put("case", case_body)
        doc = repo.get(doc_id, "document")
        assert (root / "files" / doc["path"]).is_file()
    report = env["client"].post("/api/v1/retention/sweep").json()
    assert {item["kind"] for item in report["purged"]} == {"original"}
    with store.read() as repo:
        doc = repo.get(doc_id, "document")
        assert doc["path"] is None and doc["purged_at"]
        # 未配置的类不动：mapping 与 audit 保留
        assert repo.list("audit", case["id"])


def test_sweep_without_policy_does_nothing(env):
    case = _formal_case(env)
    _upload(env, case["id"])
    report = env["client"].post("/api/v1/retention/sweep").json()
    assert report["purged"] == []


def test_erase_case_removes_personal_content_keeps_tombstone(env):
    case = _formal_case(env)
    doc_id = _upload(env, case["id"])
    store = env["app"].state.store
    root = env["root"]
    with store.read() as repo:
        path = root / "files" / repo.get(doc_id, "document")["path"]
        assert path.is_file()
    result = env["client"].request("DELETE", f"/api/v1/cases/{case['id']}",
                                   json={"confirm_id": case["id"], "basis": "测试删除依据"})
    assert result.status_code == 200, result.text
    assert not path.exists()
    with store.read() as repo:
        tomb = repo.get(case["id"], "case")
        assert tomb["erased"] is True and tomb["erase_basis"] == "测试删除依据"
        assert repo.list("document", case["id"]) == []
        assert repo.list("fact", case["id"]) == []
        assert any(a["event"] == "case.erased" for a in repo.list("audit", case["id"]))


def test_erase_requires_confirm_and_basis(env):
    case = _formal_case(env)
    bad = env["client"].request("DELETE", f"/api/v1/cases/{case['id']}",
                                json={"confirm_id": "wrong", "basis": "x"})
    assert bad.status_code == 400
    bad2 = env["client"].request("DELETE", f"/api/v1/cases/{case['id']}",
                                 json={"confirm_id": case["id"], "basis": ""})
    assert bad2.status_code in (400, 409)


def test_erase_refuses_inflight_dispatch(env):
    case = _formal_case(env)
    store = env["app"].state.store
    with store.transaction() as repo:
        repo.put("task", {"id": "t_inflight", "case_id": case["id"], "status": "queued"}, case["id"])
    result = env["client"].request("DELETE", f"/api/v1/cases/{case['id']}",
                                   json={"confirm_id": case["id"], "basis": "测试"})
    assert result.status_code == 409


def test_provider_deletion_request_lifecycle(env):
    client = env["client"]
    response = client.put("/api/v1/providers/prov_test", json={
        "id": "prov_test", "name": "测试服务商", "endpoint": "https://api.example.com/v1",
        "model": "m",
    })
    assert response.status_code == 200, response.text
    profile = response.json()
    request = client.post("/api/v1/provider-deletion-requests", json={
        "provider_profile_id": profile["id"], "note": "删除LA测试请求侧副本",
    })
    assert request.status_code == 200, request.text
    record = request.json()
    assert record["status"] == "pending"
    listed = client.get("/api/v1/provider-deletion-requests").json()
    assert listed[0]["id"] == record["id"]
    acked = client.post(f"/api/v1/provider-deletion-requests/{record['id']}/ack").json()
    assert acked["status"] == "acknowledged"
    again = client.post(f"/api/v1/provider-deletion-requests/{record['id']}/ack")
    assert again.status_code == 409
