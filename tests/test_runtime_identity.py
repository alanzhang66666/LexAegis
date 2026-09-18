import json

from fastapi.testclient import TestClient

from lexaegis.api import create_app
from lexaegis.contracts import ReleaseBuildManifest
from lexaegis.gateway import create_gateway
from lexaegis.outbound_gate import product_dispatch_state
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.runtime_identity import runtime_identity
from lexaegis.util import sign
from lexaegis.worker import WORKER_RUNTIME_IDENTITY_FILE, expose_runtime_identity


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _verified_manifest() -> ReleaseBuildManifest:
    return ReleaseBuildManifest(
        id="build_fixture",
        source_commit="1" * 40,
        worktree_clean=True,
        source_tree_hash=SHA_A,
        documentation_hash=SHA_A,
        frontend_dist_hash=SHA_A,
        wheel_hash=SHA_A,
        lockfile_hashes={"frontend/pnpm-lock.yaml": SHA_A, "requirements.lock": SHA_B},
        runtime_pack_hash=SHA_B,
        container_image_digests={"api": SHA_A, "gateway": SHA_B, "worker": SHA_A},
        migration_revision="0003_formal_release_uniques",
        validation_results_hash=SHA_B,
        status="verified",
        created_at="2026-09-14T00:00:00Z",
        verified_by="release-automation",
    )


def test_api_worker_and_gateway_expose_the_same_frozen_manifest_identity(tmp_path):
    manifest = _verified_manifest()
    expected_hash = build_manifest_identity_hash(manifest)
    secret = "unit-test-gateway-signing-secret"

    api = create_app(tmp_path / "app", password="unit-test-password", build_manifest=manifest)
    gateway = create_gateway(tmp_path / "gateway", secret=secret, build_manifest=manifest)
    worker_identity = expose_runtime_identity(tmp_path / "app", manifest)

    with TestClient(api) as api_client, TestClient(gateway) as gateway_client:
        api_identity = api_client.get("/api/v1/health").json()["runtime_identity"]
        signature = sign({"op": "health"}, secret)
        gateway_identity = gateway_client.get(
            "/health", headers={"X-Gateway-Signature": signature}
        ).json()["runtime_identity"]

    assert {api_identity["runtime_identity_hash"], worker_identity["runtime_identity_hash"],
            gateway_identity["runtime_identity_hash"]} == {expected_hash}
    assert api_identity == {
        "process": "api",
        "status": "verified",
        "runtime_identity_hash": expected_hash,
    }
    assert worker_identity == {
        "process": "worker",
        "status": "verified",
        "runtime_identity_hash": expected_hash,
    }
    assert gateway_identity == {
        "process": "gateway",
        "status": "verified",
        "runtime_identity_hash": expected_hash,
    }
    assert json.loads((tmp_path / "app" / WORKER_RUNTIME_IDENTITY_FILE).read_text(encoding="utf-8")) == worker_identity
    assert product_dispatch_state() == "blocked"


def test_runtime_identity_uses_only_canonical_manifest_identity_fields():
    manifest = _verified_manifest()
    same_build_different_metadata = manifest.model_copy(
        update={
            "id": "build_other_record",
            "created_at": "2026-09-14T00:30:00Z",
            "verified_by": "another-release-operator",
        }
    )

    assert build_manifest_identity_hash(same_build_different_metadata) == build_manifest_identity_hash(manifest)


def test_invalid_manifest_is_fail_closed_without_echoing_protected_content():
    marker_values = {
        "api_key": "secret-key-marker",
        "case_text": "case-body-marker",
        "mapping": {"real-name-marker": "token"},
        "request": {"complete-request-marker": True},
        "provider_error": "provider-error-body-marker",
    }
    invalid_manifest = {**_verified_manifest().model_dump(), **marker_values}

    public = runtime_identity("api", invalid_manifest).public()
    serialized = json.dumps(public, sort_keys=True)

    assert public == {"process": "api", "status": "invalid", "runtime_identity_hash": ""}
    assert all(marker not in serialized for marker in (
        "secret-key-marker",
        "case-body-marker",
        "real-name-marker",
        "complete-request-marker",
        "provider-error-body-marker",
    ))


def test_missing_manifest_is_unconfigured_and_has_no_claimed_identity(monkeypatch):
    monkeypatch.delenv("LEX_RELEASE_BUILD_MANIFEST_PATH", raising=False)

    assert runtime_identity("worker").public() == {
        "process": "worker",
        "status": "unconfigured",
        "runtime_identity_hash": "",
    }
