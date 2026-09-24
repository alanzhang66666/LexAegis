"""V2.2 domain mapper: declarative package-provided mapping in the return
pipeline — real execution, provenance, fail-closed semantics."""
import pytest

from lexaegis import domain_mapper, return_pipeline
from lexaegis.domain_mapper import DomainMapperError
from .conftest import approve, demo_task
from .test_workflow import formal_material, task_state
from .test_orchestrator import _create_task, _evaluate


# --- engine unit tests --------------------------------------------------------

def _claims():
    return {"claims": [
        {"text": "拖欠工资 1000 元", "source_ids": ["f1"], "raw_kind": "工资"},
        {"text": "加班费 200 元", "source_ids": ["f2"]},
    ]}


def test_field_map_value_map_defaults_applied():
    config = {
        "field_map": {"raw_kind": "claim_type"},
        "value_map": {"claim_type": {"工资": "wage_arrears"}},
        "defaults": {"domain": "labor"},
    }
    validated = _claims()
    report = domain_mapper.apply_mapper(config, validated)
    assert report == {"mapped": 2, "claims_key": "claims"}
    first, second = validated["claims"]
    assert first["claim_type"] == "wage_arrears"
    assert "raw_kind" not in first
    assert first["domain"] == "labor"
    # second claim lacks raw_kind -> no rename; defaults still applied
    assert "claim_type" not in second
    assert second["domain"] == "labor"


def test_required_fields_fail_closed():
    config = {"required_fields": ["text", "anchors"]}
    with pytest.raises(DomainMapperError, match="必填字段"):
        domain_mapper.apply_mapper(config, _claims())


def test_unknown_config_key_rejected():
    with pytest.raises(DomainMapperError, match="未知键"):
        domain_mapper.apply_mapper({"bogus_key": {}}, _claims())


def test_missing_claim_list_returns_none():
    assert domain_mapper.apply_mapper({}, {"other": []}) is None
    assert domain_mapper.apply_mapper({}, "not-a-dict") is None


def test_applies_to_task_type_gate():
    assert domain_mapper.applies({}, "anything")
    assert domain_mapper.applies({"applies_to": ["fact_summary"]}, "fact_summary")
    assert not domain_mapper.applies({"applies_to": ["fact_summary"]}, "timeline")


def test_list_shaped_result_maps_directly():
    claims = [{"text": "x", "source_ids": ["f"]}]
    report = domain_mapper.apply_mapper({"defaults": {"domain": "labor"}}, claims)
    assert report["mapped"] == 1
    assert claims[0]["domain"] == "labor"


# --- pipeline integration -----------------------------------------------------

LABOR_V2_PACK = "pack:labor:2.0.0-draft.3"


def _valid_result(task):
    """A claims_v2 payload that survives schema_stage: text drawn verbatim
    from an approved decision's output, source_ids pointing at it."""
    decision = next(d for d in task["decisions"] if d.get("output"))
    return {"claims": [{"text": decision["output"][:200],
                        "source_ids": [decision["fact_id"]]}]}


def _finish(env, case, task_id, result):
    from lexaegis.worker import finish_response
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task_id, "task")
        repo.put("disclosure",
                 {"id": stored["request"]["request_id"], "case_id": case["id"]},
                 case["id"])
        finish_response(repo, stored, {"status": "complete", "result": result})
        stored = repo.get(task_id, "task")
        steps = [s for s in repo.list("task_step") if s["task_id"] == task_id]
    return stored, steps


def _mapper_outcomes(steps):
    return [s["to_status"] for s in steps
            if s["to_status"].startswith("return:domain_mapper:")]


def _labor_task(env, case):
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "fact_summary", "transport": "cloud",
              "pack_id": LABOR_V2_PACK})
    assert result.status_code == 200, result.text
    return result.json()


def test_labor_mapper_executes_in_return_pipeline(env):
    """The seeded labor cause_pack carries a real mapper: claims gain the
    declared default field and the artifact records mapper provenance."""
    case, _document, _fact = formal_material(env)
    task = _labor_task(env, case)
    _evaluate(env, task["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        result = _valid_result(stored)
    finished, steps = _finish(env, case, task["id"], result)
    assert finished["status"] == "complete"
    provenance = finished["artifact"]["domain_mapper"]
    assert provenance["package_id"] == "labor_cause_pack"
    assert provenance["content_hash"]
    assert all(c.get("domain") == "labor" for c in finished["artifact"]["claims"])
    assert _mapper_outcomes(steps) == ["return:domain_mapper:mapped"]


def test_mapper_skipped_when_task_type_not_in_applies_to(env):
    """A bound mapper whose applies_to excludes this task type is skipped —
    the package's own declaration gates execution."""
    case, _document, _fact = formal_material(env)
    task = _labor_task(env, case)
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        snapshot_id = repo.get(task["id"], "task")["domain_runtime_snapshot_id"]
        snapshot = repo.get(snapshot_id, "domain_runtime_snapshot")
        manifest = repo.get(snapshot["domain_package_manifest_id"],
                            "domain_package_manifest")
        cause_ref = manifest["package_refs"]["cause_pack"][0]
        package = repo.get(cause_ref["id"], "domain_package")
        package["content"]["mapper"]["applies_to"] = ["other_task"]
        repo.put("domain_package", package)
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        result = _valid_result(stored)
    finished, steps = _finish(env, case, task["id"], result)
    assert finished["status"] == "complete"
    assert "domain_mapper" not in finished["artifact"]
    assert _mapper_outcomes(steps) == ["return:domain_mapper:skipped"]


def test_mapper_skipped_without_snapshot(env):
    """A legacy task without domain_runtime_snapshot_id skips the stage."""
    case, _document, _fact = formal_material(env)
    task = _labor_task(env, case)
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        stored = repo.get(task["id"], "task")
        del stored["domain_runtime_snapshot_id"]
        repo.put("task", stored, case["id"])
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        result = _valid_result(stored)
    finished, steps = _finish(env, case, task["id"], result)
    assert _mapper_outcomes(steps) == ["return:domain_mapper:skipped"]


def test_mapper_unbound_for_demo_pack(demo_env):
    """The v1 demo pack never produces a manifest — the stage reports
    'unbound' rather than pretending a mapper exists."""
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    from lexaegis.worker import process_one
    assert process_one(env["app"].state.store, env["root"], env["gate"])
    with env["app"].state.store.read() as repo:
        steps = [s for s in repo.list("task_step") if s["task_id"] == task["id"]]
    assert _mapper_outcomes(steps) == ["return:domain_mapper:unbound"]


def test_invalid_mapper_output_fails_closed(env):
    """If a mapper config leaves claims without required fields the result is
    rejected as invalid_cloud_result — never adopted."""
    case, _document, _fact = formal_material(env)
    task = _labor_task(env, case)
    _evaluate(env, task["id"])
    with env["app"].state.store.transaction() as repo:
        snapshot_id = repo.get(task["id"], "task")["domain_runtime_snapshot_id"]
        snapshot = repo.get(snapshot_id, "domain_runtime_snapshot")
        manifest = repo.get(snapshot["domain_package_manifest_id"],
                            "domain_package_manifest")
        cause_ref = manifest["package_refs"]["cause_pack"][0]
        package = repo.get(cause_ref["id"], "domain_package")
        package["content"]["mapper"] = {"required_fields": ["never_present"]}
        package["content_hash"] = cause_ref["content_hash"]
        repo.put("domain_package", package)
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        result = _valid_result(stored)
    finished, steps = _finish(env, case, task["id"], result)
    assert finished["status"] == "failed"
    assert finished["failure_code"] == "invalid_cloud_result"
    assert _mapper_outcomes(steps) == ["return:domain_mapper:failed"]
