"""V2.2 runtime binding objects (P1): dual-write binding/context/snapshot/step.

The legacy task path stays authoritative; these tests pin the new records'
shape, snapshot determinism, and no-silent-drift behavior.
"""
import pytest

from lexaegis import domain_runtime
from .test_workflow import formal_material


def _create_task(env, case_id, task_type="fact_summary", transport="local"):
    result = env["client"].post(
        f"/api/v1/cases/{case_id}/tasks",
        json={"task_type": task_type, "transport": transport},
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_case_creation_writes_domain_binding(env):
    case, _document, _fact = formal_material(env)
    result = env["client"].get(f"/api/v1/cases/{case['id']}/domain-binding")
    assert result.status_code == 200
    bindings = result.json()
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["case_id"] == case["id"]
    assert binding["cause_id"] == "labor"
    assert binding["binding_status"] == "active"
    assert binding["bound_by"] == "local-lawyer"


def test_task_binds_snapshot_and_context_version(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    assert task["domain_runtime_snapshot_id"].startswith("drs_")
    assert task["context_version_id"]

    snapshot = env["client"].get(f"/api/v1/tasks/{task['id']}/runtime-snapshot").json()
    assert snapshot["platform_api_version"] == "v2"
    for key in ("cause_pack_hash", "legal_rule_pack_hash", "capability_binding_hash",
                "review_schema_hash", "artifact_schema_hash",
                "minimization_profile_hash", "gate_profile_hash"):
        assert len(snapshot[key]) == 64
    assert snapshot["pack_id"] == task["pack_id"]

    binding = env["client"].get(f"/api/v1/cases/{case['id']}/domain-binding").json()[0]
    assert binding["cause_pack_id"] == task["pack_id"]
    assert binding["cause_pack_version"] == snapshot["pack_version"]

    contexts = env["client"].get(f"/api/v1/cases/{case['id']}/context-versions").json()
    assert len(contexts) == 1
    assert contexts[0]["status"] == "current"
    assert contexts[0]["domain_runtime_snapshot_id"] == snapshot["id"]


def test_snapshot_is_content_addressed_and_deduplicated(env):
    case, _document, _fact = formal_material(env)
    first = _create_task(env, case["id"])
    second = _create_task(env, case["id"])
    assert first["domain_runtime_snapshot_id"] == second["domain_runtime_snapshot_id"]
    # P2: capability_binding is resolved per task_type, so a different
    # task_type produces a different content-addressed snapshot.
    other = _create_task(env, case["id"], task_type="timeline")
    assert other["domain_runtime_snapshot_id"] != first["domain_runtime_snapshot_id"]
    with env["app"].state.store.read() as repo:
        assert len(repo.list("domain_runtime_snapshot")) == 2


def test_pack_content_change_yields_new_snapshot_without_rewriting_old(env):
    case, _document, _fact = formal_material(env)
    first = _create_task(env, case["id"])
    with env["app"].state.store.transaction() as repo:
        pack = repo.get(first["pack_id"], "pack")
        pack["version"] = pack["version"] + "+t0"
        pack["forbidden_terms"] = list(pack.get("forbidden_terms") or []) + ["测试禁词"]
        repo.put("pack", pack)
    second = _create_task(env, case["id"])
    assert second["domain_runtime_snapshot_id"] != first["domain_runtime_snapshot_id"]
    with env["app"].state.store.read() as repo:
        old_task = repo.get(first["id"], "task")
    assert old_task["domain_runtime_snapshot_id"] == first["domain_runtime_snapshot_id"]


def test_case_revision_supersedes_context_version(env):
    case, document, _fact = formal_material(env)
    first = _create_task(env, case["id"])
    block = document["ir"]["blocks"][0]
    env["client"].post(f"/api/v1/cases/{case['id']}/facts", json={
        "field": "event", "value": block["text"] + "（补充）",
        "source_ids": [block["id"]], "confirmed": True,
    })
    second = _create_task(env, case["id"])
    assert second["context_version_id"] != first["context_version_id"]
    contexts = env["client"].get(f"/api/v1/cases/{case['id']}/context-versions").json()
    by_id = {c["context_version_id"]: c for c in contexts}
    assert by_id[first["context_version_id"]]["status"] == "superseded"
    assert by_id[first["context_version_id"]]["superseded_by"] == second["context_version_id"]
    assert by_id[second["context_version_id"]]["status"] == "current"


def test_evaluate_binds_snapshot_into_request_hash(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    evaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    dependencies = evaluated["request"]["dependencies"]
    assert dependencies["domain_runtime_snapshot_id"] == task["domain_runtime_snapshot_id"]
    assert len(dependencies["domain_runtime_snapshot_hash"]) == 64


def test_legacy_task_without_snapshot_keeps_request_hash_formula(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        stored.pop("domain_runtime_snapshot_id", None)
        repo.put("task", stored, case["id"])
    evaluated = env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    dependencies = evaluated["request"]["dependencies"]
    assert "domain_runtime_snapshot_id" not in dependencies
    assert "domain_runtime_snapshot_hash" not in dependencies


def test_platform_api_mismatch_fails_closed(env):
    case, _document, _fact = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        for pack in repo.list("pack"):
            pack["platform_api"] = "v3"
            repo.put("pack", pack)
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "fact_summary", "transport": "local"},
    )
    assert result.status_code == 409
    assert "platform_api_mismatch" in result.json()["detail"]


def test_missing_pack_fails_closed(env):
    case, _document, _fact = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        for pack in repo.list("pack"):
            repo.delete(pack["id"])
    with pytest.raises(domain_runtime.DomainRuntimeError, match="package_resolution_failed"):
        with env["app"].state.store.transaction() as repo:
            domain_runtime.resolve_runtime_snapshot(repo, {}, None)


def test_task_steps_record_lifecycle_transitions(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    with env["app"].state.store.read() as repo:
        steps = [s for s in repo.list("task_step", case["id"]) if s["task_id"] == task["id"]]
    step_types = [s["step_type"] for s in steps]
    assert "STATE_TRANSITION" in step_types
    assert "CONTROL" in step_types
    control = next(s for s in steps if s["step_type"] == "CONTROL")
    assert control["to_status"] in ("review", "blocked", "review_blocked")
