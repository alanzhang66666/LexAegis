"""V2.2 Domain Package Set (P2): manifest resolution, lifecycle, revocation.

Packages bind the runtime snapshot only; the monolithic pack stays
authoritative for disclosure/rules/gate consumption.
"""
import pytest

from lexaegis import domain_packages, domain_runtime
from .conftest import login_admin
from .test_workflow import formal_material


def _transition(env, path, body):
    login_admin(env)
    return env["client"].post(path, json=body)


def _create_task(env, case_id, task_type="fact_summary", transport="local"):
    result = env["client"].post(
        f"/api/v1/cases/{case_id}/tasks",
        json={"task_type": task_type, "transport": transport},
    )
    assert result.status_code == 200, result.text
    return result.json()


def _labor_manifest(env):
    manifests = env["client"].get("/api/v1/domain-package-manifests").json()
    return next(m for m in manifests if m["cause_id"] == "labor"
                and "product" not in m["version"])


def test_seed_registers_manifest_and_packages(env):
    packages = env["client"].get("/api/v1/domain-packages?cause_id=labor").json()
    types = {p["package_type"] for p in packages}
    assert types == set(domain_packages.PACKAGE_TYPES) - {"capability_binding"} or types >= {
        "cause_pack", "legal_rule_pack", "review_schema", "artifact_schema",
        "minimization_profile", "gate_profile", "domain_acceptance_suite",
    }
    bindings = [p for p in packages if p["package_type"] == "capability_binding"]
    assert len(bindings) >= 4  # labor pack task_ids
    assert all(p["status"] == "validated" for p in packages)
    manifest = _labor_manifest(env)
    assert manifest["status"] == "validated"
    assert manifest["signature"] is None  # nothing signed without a real key
    refs = manifest["package_refs"]
    assert len(refs["cause_pack"]) == 1
    assert len(refs["capability_binding"]) >= 4


def test_task_snapshot_uses_real_package_hashes(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    snapshot = env["client"].get(f"/api/v1/tasks/{task['id']}/runtime-snapshot").json()
    assert snapshot["domain_package_manifest_id"] == _labor_manifest(env)["id"]
    assert task["capability_binding_id"]
    with env["app"].state.store.read() as repo:
        cause = repo.get(snapshot["domain_package_manifest_id"], "domain_package_manifest")
        ref = cause["package_refs"]["cause_pack"][0]
        assert snapshot["cause_pack_hash"] == ref["content_hash"]
        binding = repo.get(task["capability_binding_id"], "domain_package")
        assert binding["content"]["task_type"] == "fact_summary"
        assert snapshot["capability_binding_hash"] == binding["content_hash"]
    # content-addressed dedup still holds
    second = _create_task(env, case["id"])
    assert second["domain_runtime_snapshot_id"] == task["domain_runtime_snapshot_id"]


def test_revoked_package_fails_new_tasks_and_stales_inflight(env):
    case, _document, _fact = formal_material(env)
    task = _create_task(env, case["id"])
    manifest = _labor_manifest(env)
    target = manifest["package_refs"]["gate_profile"][0]
    result = _transition(env, f"/api/v1/domain-packages/{target['id']}/transition",
                         {"status": "revoked", "reason": "test revocation"})
    assert result.status_code == 200, result.text
    blocked = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "fact_summary", "transport": "local"})
    assert blocked.status_code == 409
    assert "package_resolution_failed" in blocked.json()["detail"]
    with env["app"].state.store.read() as repo:
        stored = repo.get(task["id"], "task")
        assert stored["stale"] is True
        steps = [s for s in repo.list("task_step", case["id"])
                 if s["task_id"] == task["id"] and s["step_type"] == "STATE_TRANSITION"]
        assert any(s["actor"] == "system:package_revoked" for s in steps)


def test_platform_api_mismatch_fails_closed(env):
    case, _document, _fact = formal_material(env)
    manifest = _labor_manifest(env)
    target = manifest["package_refs"]["cause_pack"][0]
    with env["app"].state.store.transaction() as repo:
        package = repo.get(target["id"], "domain_package")
        package["platform_api"] = "v9"
        repo.put("domain_package", package)
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "fact_summary", "transport": "local"})
    assert result.status_code == 409
    assert "platform_api_mismatch" in result.json()["detail"]


def test_lifecycle_signing_requires_key_and_publish_requires_signature(env, monkeypatch):
    manifest = _labor_manifest(env)
    target = manifest["package_refs"]["cause_pack"][0]
    monkeypatch.delenv("LEX_PACKAGE_SIGNING_KEY", raising=False)
    unsigned = _transition(env, f"/api/v1/domain-packages/{target['id']}/transition",
                           {"status": "signed"})
    assert unsigned.status_code == 409
    monkeypatch.setenv("LEX_PACKAGE_SIGNING_KEY", "unit-test-signing-key-32-characters")
    signed = _transition(env, f"/api/v1/domain-packages/{target['id']}/transition",
                         {"status": "signed"})
    assert signed.status_code == 200, signed.text
    assert signed.json()["signature"]
    published = _transition(env, f"/api/v1/domain-packages/{target['id']}/transition",
                            {"status": "published"})
    assert published.status_code == 200


def test_deprecated_package_still_resolves(env):
    case, _document, _fact = formal_material(env)
    manifest = _labor_manifest(env)
    target = manifest["package_refs"]["artifact_schema"][0]
    monkey_key = "unit-test-signing-key-32-characters"
    with env["app"].state.store.transaction() as repo:
        package = domain_packages.transition(
            repo, domain_packages.PACKAGE_KIND, target["id"], "signed",
            actor="tester", signing_key=monkey_key)
        domain_packages.transition(
            repo, domain_packages.PACKAGE_KIND, target["id"], "published", actor="tester")
        domain_packages.transition(
            repo, domain_packages.PACKAGE_KIND, target["id"], "deprecated", actor="tester")
    task = _create_task(env, case["id"])
    assert task["domain_runtime_snapshot_id"].startswith("drs_")


def test_cause_without_manifest_falls_back_to_interim_snapshot(env):
    case, _document, _fact = formal_material(env)
    # contract_test domain pack has no validated manifest -> interim sections
    with env["app"].state.store.transaction() as repo:
        packs = [p for p in repo.list("pack") if p.get("domain_id") == "contract_test"]
        if not packs:
            pytest.skip("contract_test pack not seeded in this profile")
        pack = packs[-1]
        snapshot = domain_runtime.resolve_runtime_snapshot(
            repo, {"cause_id": "contract_test"}, pack, "production", "fact_summary")
    assert snapshot["domain_package_manifest_id"] is None
    assert snapshot["capability_binding_id"] is None


def test_manifest_revocation_blocks_resolution(env):
    case, _document, _fact = formal_material(env)
    manifest = _labor_manifest(env)
    monkey_key = "unit-test-signing-key-32-characters"
    with env["app"].state.store.transaction() as repo:
        domain_packages.transition(
            repo, domain_packages.MANIFEST_KIND, manifest["id"], "signed",
            actor="tester", signing_key=monkey_key)
        domain_packages.transition(
            repo, domain_packages.MANIFEST_KIND, manifest["id"], "published", actor="tester")
        domain_packages.transition(
            repo, domain_packages.MANIFEST_KIND, manifest["id"], "revoked", actor="tester")
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "fact_summary", "transport": "local"})
    assert result.status_code == 409
