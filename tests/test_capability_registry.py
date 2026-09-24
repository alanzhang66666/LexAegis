"""V2.2 P5: capability registry, binding resolution, SPI surface."""
import pytest

from lexaegis import capability_registry
from lexaegis.spi import spi_for
from .conftest import login_admin
from .test_workflow import formal_material


def _create_task(env, case_id, task_type="fact_summary", transport="local"):
    return env["client"].post(
        f"/api/v1/cases/{case_id}/tasks",
        json={"task_type": task_type, "transport": transport})


def test_seed_registers_capabilities(env):
    with env["app"].state.store.read() as repo:
        records = repo.list("capability")
    task_types = {r["task_type"] for r in records}
    assert {"fact_summary", "timeline", "evidence_inventory",
            "issue_extraction"} <= task_types
    for record in records:
        assert record["capability_id"] == f"R_{record['task_type']}"
        assert record["status"] == "available"


def test_task_carries_capability_and_binding(env):
    case, _document, _fact = formal_material(env)
    result = _create_task(env, case["id"])
    assert result.status_code == 200, result.text
    task = result.json()
    assert task["capability_id"] == "R_fact_summary"
    assert task["capability_binding_id"]
    with env["app"].state.store.read() as repo:
        capability = capability_registry.capability_for_task(repo, "fact_summary")
        assert capability["status"] == "available"


def test_disabled_capability_blocks_task(env):
    case, _document, _fact = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        capability = capability_registry.capability_for_task(repo, "fact_summary")
        capability["status"] = "disabled"
        repo.put("capability", capability)
    result = _create_task(env, case["id"], task_type="fact_summary")
    assert result.status_code == 409
    assert "已禁用" in result.json()["detail"]


def test_unregistered_task_type_still_rejected(env):
    case, _document, _fact = formal_material(env)
    result = _create_task(env, case["id"], task_type="nonexistent_task")
    assert result.status_code == 409


def test_binding_with_dangling_provider_ref_rejected(env):
    case, _document, _fact = formal_material(env)
    with env["app"].state.store.transaction() as repo:
        # corrupt the binding's provider reference -> resolution must fail closed
        manifests = repo.list("domain_package_manifest")
        manifest = next(m for m in manifests
                        if m["cause_id"] == "labor" and "product" not in m["version"])
        ref, binding = next(
            (r, repo.get(r["id"], "domain_package"))
            for r in manifest["package_refs"]["capability_binding"]
            if (repo.get(r["id"], "domain_package").get("content") or {}).get("task_type") == "fact_summary")
        binding = dict(binding)
        binding["content"] = {**binding["content"],
                              "provider_profile": "ghost-provider"}
        from lexaegis.domain_packages import _package_content_hash
        binding["content_hash"] = _package_content_hash(binding)
        repo.put("domain_package", binding)
        # manifest ref must carry the recomputed hash or resolution fails on drift
        ref["content_hash"] = binding["content_hash"]
        manifest["package_refs"] = dict(manifest["package_refs"])
        from lexaegis.domain_packages import _manifest_content_hash
        manifest["content_hash"] = _manifest_content_hash(manifest)
        repo.put("domain_package_manifest", manifest)
    result = _create_task(env, case["id"], task_type="fact_summary")
    assert result.status_code == 409
    assert "服务商档案不存在" in result.json()["detail"]


def test_spi_read_only_surface(env):
    with env["app"].state.store.read() as repo:
        package = next(
            p for p in repo.list("domain_package")
            if p["package_type"] == "cause_pack" and p["cause_id"] == "labor")
    spi = spi_for(package)
    assert spi.package_type == "cause_pack"
    assert spi.fact_fields()
    assert spi.content_hash == package["content_hash"]
    with pytest.raises(TypeError):
        spi.content["fact_fields"] = []
    with pytest.raises(ValueError):
        spi_for({"package_type": "pack"})  # not a domain_package
