"""V2.2 §8 Support Registry (P3): loadable != supported.

Support gates entry into the product loop (case/task creation); it never
grants dispatch — outbound stays fail-closed through the existing gates.
"""
import pytest

from lexaegis import support_registry
from .conftest import login_admin, login_as
from .test_workflow import formal_material


def _create_task(env, case_id, task_type="fact_summary", transport="local"):
    return env["client"].post(
        f"/api/v1/cases/{case_id}/tasks",
        json={"task_type": task_type, "transport": transport})


def _labor_support(env):
    records = env["client"].get("/api/v1/supported-causes").json()
    return next(r for r in records if r["cause_id"] == "labor")


def test_seed_declares_labor_supported(env):
    record = _labor_support(env)
    assert record["status"] == "supported"
    assert set(record["environments"]) == {"production", "demo", "integration"}
    assert record["pack_ids"] and record["manifest_ids"]
    assert "R_fact_summary" in record["capabilities"]
    # contract_test pack is loadable but must NOT be supported
    assert not any(r["cause_id"] == "contract_test"
                   for r in env["client"].get("/api/v1/supported-causes").json())


def test_loadable_but_unsupported_cause_cannot_create_case(env):
    result = env["client"].post(
        "/api/v1/cases", json={"name": "未支持案由", "domain": "contract_test"})
    assert result.status_code == 409
    assert "未进入产品支持清单" in result.json()["detail"]


def test_upsert_rejects_dangling_pack_reference(env):
    login_admin(env)
    result = env["client"].post("/api/v1/supported-causes", json={
        "cause_id": "new_cause", "status": "validation",
        "environments": ["production"], "pack_ids": ["pack:ghost:0.0.0"],
    })
    assert result.status_code == 409
    assert "不存在" in result.json()["detail"]


def test_pack_version_not_in_support_record_blocks_task(env):
    case, _document, _fact = formal_material(env)
    record = _labor_support(env)
    # narrow support to a pack that is not the selected one
    login_admin(env)
    result = env["client"].post("/api/v1/supported-causes", json={
        "cause_id": "labor", "status": "supported",
        "environments": record["environments"],
        "pack_ids": [p for p in record["pack_ids"] if "draft.3" not in p],
        "manifest_ids": record["manifest_ids"],
        "capabilities": record["capabilities"],
    })
    assert result.status_code == 200, result.text
    blocked = _create_task(env, case["id"])
    assert blocked.status_code == 409
    assert "未获支持" in blocked.json()["detail"]


def test_capability_not_in_support_record_blocks_task(env):
    case, _document, _fact = formal_material(env)
    record = _labor_support(env)
    login_admin(env)
    env["client"].post("/api/v1/supported-causes", json={
        "cause_id": "labor", "status": "supported",
        "environments": record["environments"],
        "pack_ids": record["pack_ids"],
        "manifest_ids": record["manifest_ids"],
        "capabilities": ["R_timeline"],  # fact_summary no longer supported
    })
    blocked = _create_task(env, case["id"], task_type="fact_summary")
    assert blocked.status_code == 409
    assert "R_fact_summary" in blocked.json()["detail"]
    allowed = _create_task(env, case["id"], task_type="timeline")
    assert allowed.status_code == 200, allowed.text


def test_suspend_stales_inflight_and_blocks_new(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    assert task.status_code == 200, task.text
    task = task.json()
    login_admin(env)
    suspended = env["client"].post(
        "/api/v1/supported-causes/labor/transition", json={"status": "suspended"})
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    blocked = _create_task(env, case["id"])
    assert blocked.status_code == 409
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        assert stored["stale"] is True
        steps = [s for s in repo.list("task_step", case["id"])
                 if s["task_id"] == task["id"] and s["step_type"] == "STATE_TRANSITION"]
        assert any(s["actor"] == "system:support_suspended" for s in steps)


def test_integration_only_cause_rejected_in_production(env):
    case_pack = None
    with env["app"].state.store.read() as repo:
        packs = [p for p in repo.list("pack") if p.get("domain_id") == "contract_test"]
        if not packs:
            pytest.skip("contract_test pack not seeded in this profile")
        case_pack = packs[-1]
    login_admin(env)
    result = env["client"].post("/api/v1/supported-causes", json={
        "cause_id": "contract_test", "status": "integration_only",
        "environments": ["integration"],
        "pack_ids": [case_pack["id"]],
        "capabilities": ["R_fact_summary"],
    })
    assert result.status_code == 200, result.text
    blocked = env["client"].post(
        "/api/v1/cases", json={"name": "集成限定案由", "domain": "contract_test"})
    assert blocked.status_code == 409


def test_support_endpoints_require_admin(env):
    login_as(env, "case_operator")
    denied = env["client"].post("/api/v1/supported-causes", json={
        "cause_id": "x", "status": "supported", "environments": ["production"]})
    assert denied.status_code == 403
    denied = env["client"].post(
        "/api/v1/supported-causes/labor/transition", json={"status": "suspended"})
    assert denied.status_code == 403
    login_admin(env)
    listed = env["client"].get("/api/v1/supported-causes")
    assert listed.status_code == 200
