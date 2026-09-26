import json

from lexaegis.audit_chain import export_evidence_manifest, verify_audit_chain

from .test_workflow import formal_material


def _chain(env, case_id):
    with env["app"].state.store.read() as repo:
        return repo.list("audit", case_id), verify_audit_chain(repo, case_id)


def test_audit_entries_carry_predecessor_hashes(env):
    case, _, _ = formal_material(env)
    entries, problems = _chain(env, case["id"])
    assert problems == []
    assert len(entries) >= 2
    assert entries[0]["prev_hash"] == ""
    for previous, current in zip(entries, entries[1:]):
        assert current["prev_hash"] == previous["entry_hash"]
        assert current["entry_hash"]


def test_tampered_audit_entry_breaks_chain(env):
    case, _, _ = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        entry = repo.list("audit", case["id"])[-1]
        entry["metadata"]["actor_user_id"] = "forged-actor"
        repo.put("audit", entry, case["id"])
    _, problems = _chain(env, case["id"])
    assert any("entry_hash" in problem for problem in problems)


def test_deleted_audit_entry_breaks_chain(env):
    case, _, _ = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        entries = repo.list("audit", case["id"])
        assert len(entries) >= 2
        repo.delete(entries[0]["id"])
    _, problems = _chain(env, case["id"])
    assert any("prev_hash" in problem for problem in problems)


def test_evidence_manifest_binds_request_and_never_leaks_material(env):
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    evaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    manifest = env["client"].get(f"/api/v1/tasks/{task['id']}/evidence-manifest").json()
    assert manifest["request_hash"] == evaluated["request_hash"]
    assert manifest["manifest_hash"]
    assert manifest["audit_chain_problems"] == []
    assert manifest["audit_chain"]
    blob = json.dumps(manifest, ensure_ascii=False)
    for secret in ("劳动者林甲主张工资12000元", "12000", "工资表证据", "wire_payload", "mapping"):
        assert secret not in blob


def test_manifest_export_is_stable_and_scoped(env):
    case, _, _ = formal_material(env)
    task = env["client"].post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud"}).json()
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    with env["app"].state.store.read() as repo:
        manifest = export_evidence_manifest(repo, task["id"])
    assert manifest["task_id"] == task["id"]
    assert manifest["gate_snapshot"]
    assert all("text" not in json.dumps(hit) for hit in manifest["gate_snapshot"])
