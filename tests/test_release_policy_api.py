from __future__ import annotations

from lexaegis import release_service
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.util import digest
from tests.test_release_service_integration import _manifest, _seed_business_state


def _runtime_identities(manifest):
    value = build_manifest_identity_hash(manifest)
    return [{"process": process, "status": "verified", "runtime_identity_hash": value}
            for process in ("api", "worker", "gateway")]


def test_task_policy_api_enforces_admin_hash_and_derives_bound_fields(env, monkeypatch):
    manifest = _manifest()
    context = {"build_manifest": manifest, "runtime_identities": _runtime_identities(manifest)}
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
    app, client = env["app"], env["client"]
    with app.state.store.transaction() as repo:
        task, case, pack, provider = _seed_business_state(repo, manifest)
        runtime_pack = {
            "id": "runtime-pack-api-test", "status": "published", "scope_kind": "request",
            "published_scope": {"domain": "labor", "purpose": "R_fact_summary", "recipient": provider["id"]},
        }
        repo.put("runtime_pack", runtime_pack)
        activation = {
            "id": "activation-api-test", "pack_id": pack["id"],
            "runtime_pack_id": runtime_pack["id"],
            "artifact_sha256": "sha256:" + "0" * 64,
        }
        repo.put("runtime_pack_activation", activation)

    assert client.post("/api/v1/users", json={
        "username": "technical-policy-test", "display_name": "技术复核员",
        "role": "technical_reviewer", "password": "technical-password-123",
    }).status_code == 200
    client.post("/api/v1/logout")
    assert client.post("/api/v1/login", json={"username": "technical-policy-test",
                                               "password": "technical-password-123"}).status_code == 200
    denied = client.post(f"/api/v1/tasks/{task['id']}/formal-release/policy", json={
        "request_hash": task["request_hash"],
    })
    assert denied.status_code == 403

    client.post("/api/v1/logout")
    assert client.post("/api/v1/login", json={"username": "admin",
                                               "password": "unit-test-password"}).status_code == 200
    stale = client.post(f"/api/v1/tasks/{task['id']}/formal-release/policy", json={
        "request_hash": "0" * 64,
    })
    assert stale.status_code == 409

    mismatched_artifact = client.post(f"/api/v1/tasks/{task['id']}/formal-release/policy", json={
        "request_hash": task["request_hash"],
    })
    assert mismatched_artifact.status_code == 409
    with app.state.store.transaction() as repo:
        activation = repo.get("activation-api-test", "runtime_pack_activation")
        activation["artifact_sha256"] = manifest.runtime_pack_hash
        repo.put("runtime_pack_activation", activation)

    response = client.post(f"/api/v1/tasks/{task['id']}/formal-release/policy", json={
        "request_hash": task["request_hash"],
    })
    assert response.status_code == 200, response.text
    policy = response.json()
    assert policy["scope_kind"] == "request"
    assert policy["bound_request_hash"] == task["request_hash"]
    assert policy["tuple"] == {
        "case_id": case["reference_code"],
        "purpose": "R_fact_summary",
        "recipient": provider["id"],
    }
    assert policy["build_manifest_hash"] == build_manifest_identity_hash(manifest)
    assert policy["allowed_target"] == task["request"]["target"]
    assert policy["allowed_model"] == task["request"]["body"]["model"]
    assert policy["allowed_provider_profile_hash"] == digest(provider)
    assert policy["status"] == "blocked" and policy["maximum_dispatches"] == 1
