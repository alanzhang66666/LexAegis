from __future__ import annotations

from lexaegis import release_service
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.util import digest
from tests.conftest import login_as
from tests.test_release_service_integration import _manifest, _seed_business_state
from tests.test_workflow import formal_material


def _context(manifest):
    identity = build_manifest_identity_hash(manifest)
    return {"build_manifest": manifest,
            "runtime_identities": [{"process": item, "status": "verified",
                                    "runtime_identity_hash": identity}
                                   for item in ("api", "worker", "gateway")]}


def test_request_preview_persists_without_release_build_and_cannot_be_approved(env, monkeypatch):
    """Missing release evidence blocks dispatch, not inspection of the proposed body."""
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: {
        "build_manifest": None, "runtime_identities": [],
    })
    case, _document, _fact = formal_material(env)
    client = env["client"]
    created = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"})
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    response = client.post(f"/api/v1/tasks/{task_id}/evaluate")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["request_hash"] == digest(preview["request"])
    assert preview["product_release"]["state"] == "blocked"
    assert preview["approval"] is None
    detail = client.get(f"/api/v1/cases/{case['id']}").json()
    persisted = next(item for item in detail["tasks"] if item["id"] == task_id)
    assert persisted["request_hash"] == preview["request_hash"]
    assert persisted["request"] == preview["request"]
    assert client.get(f"/api/v1/tasks/{task_id}/formal-release/intake-context").status_code == 409
    login_as(env, "approver")
    assert client.post(f"/api/v1/tasks/{task_id}/approve", json={
        "request_hash": preview["request_hash"],
    }).status_code == 409
    with env["app"].state.store.read() as repo:
        assert not repo.list("one_time_dispatch_grant")


def test_intake_context_is_current_read_only_and_describes_gates(env, monkeypatch):
    manifest = _manifest()
    context = _context(manifest)
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
    app, client = env["app"], env["client"]
    with app.state.store.transaction() as repo:
        task, case, _pack, _provider = _seed_business_state(repo, manifest)
        task_before = repo.get(task["id"], "task")
        snapshots_before = repo.list("gate_snapshot")
        policies_before = repo.list("formal_release_policy")
        grants_before = repo.list("one_time_dispatch_grant")
        expected_rule_version = digest({"rules-v1": digest(repo.get("rules-v1", "pack"))})

    login_as(env, "technical_reviewer")
    with app.state.store.read() as repo:
        audit_count = len(repo.list("audit"))
    response = client.get(f"/api/v1/tasks/{task['id']}/formal-release/intake-context")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task["id"]
    assert body["request_hash"] == task["request_hash"]
    assert body["tuple"] == {"case_id": "LA-001", "purpose": "R_fact_summary",
                             "recipient": "D_DeepSeek_official_API"}
    assert body["build_manifest_hash"] == build_manifest_identity_hash(manifest)
    assert body["actor"]["role"] == "technical_reviewer"
    assert body["g2_authorization_statement"] == (
        "本次 LA-001、R_fact_summary 子目的、D_DeepSeek_official_API 接收方可用。")
    assert body["facts"] == [{"id": "fact-1", "field": "event", "text": "合成事实",
                              "source_ids": ["document-e2e:v1:b1"]}]
    assert body["bound_versions"] == {
        "materials": digest({"document-e2e": 1}),
        "rules": expected_rule_version,
        "task": "1", "mapping": "1", "ledger": "0",
        "combination": task["request"]["dependencies"]["combination_input_hash"],
    }
    g3 = next(item for item in body["gates"] if item["gate_id"] == "G3")
    assert g3["required_template_kinds"] == ["法03", "法04"]
    assert next(item for item in g3["templates"] if item["template_kind"] == "技01")["required_for_gate"] is False
    assert body["isolation"] == {"attester_role": "technical_reviewer",
                                 "legal_confirmation_role": "legal_reviewer",
                                 "confirmation_gate_id": "G8"}

    with app.state.store.read() as repo:
        assert repo.get(task["id"], "task") == task_before
        assert len(repo.list("audit")) == audit_count
        assert repo.list("gate_snapshot") == snapshots_before
        assert repo.list("formal_release_policy") == policies_before
        assert repo.list("one_time_dispatch_grant") == grants_before


def test_intake_context_fails_closed_without_current_verified_build_or_for_stale_request(env, monkeypatch):
    manifest = _manifest()
    context = _context(manifest)
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
    app, client = env["app"], env["client"]
    with app.state.store.transaction() as repo:
        task, _case, _pack, _provider = _seed_business_state(repo, manifest)
    login_as(env, "legal_reviewer")
    stale = {"build_manifest": manifest, "runtime_identities": context["runtime_identities"]}
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: stale)
    with app.state.store.transaction() as repo:
        current = repo.get(task["id"], "task")
        current["request_hash"] = "sha256:" + "0" * 64
        repo.put("task", current, current["case_id"])
    before = len(client.get("/api/v1/formal-release").json()["policies"])
    response = client.get(f"/api/v1/tasks/{task['id']}/formal-release/intake-context")
    assert response.status_code == 409
    assert len(client.get("/api/v1/formal-release").json()["policies"]) == before

    client.post("/api/v1/logout")
    assert client.get(f"/api/v1/tasks/{task['id']}/formal-release/intake-context").status_code == 401
    login_as(env, "legal_reviewer")

    with app.state.store.transaction() as repo:
        current = repo.get(task["id"], "task")
        current["request_hash"] = digest(current["request"])
        repo.put("task", current, current["case_id"])
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: {
        "build_manifest": None, "runtime_identities": [],
    })
    response = client.get(f"/api/v1/tasks/{task['id']}/formal-release/intake-context")
    assert response.status_code == 409
