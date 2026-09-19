import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
import pytest

from lexaegis.demo import SCENARIOS
from lexaegis.runtime_profile import (
    MARKER,
    bind_runtime,
    dispatch_scope,
    migrate_legacy_runtime,
    profile_config,
    require_case_scope,
    selected_profile,
    synthetic_manifest_hash,
    validate_case_creation,
    validate_transport,
)
from lexaegis.util import digest


def test_profile_default_ports_and_profile_roots(monkeypatch, tmp_path):
    monkeypatch.delenv("LEX_RUN_PROFILE", raising=False)
    monkeypatch.setenv("LEX_PROFILE_ROOT", str(tmp_path))
    config = profile_config()
    assert config["runtime_profile"] == "production"
    assert config["api_port"] == 38765
    assert config["app_dir"] == tmp_path / "production" / "app"
    monkeypatch.setenv("LEX_RUN_PROFILE", "integration")
    config = profile_config()
    assert config["api_port"] == 58765
    assert selected_profile() == "integration"


def test_explicit_storage_roots_are_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_DATA_DIR", str(tmp_path / "custom-app"))
    monkeypatch.setenv("LEX_GATEWAY_DIR", str(tmp_path / "custom-gateway"))
    config = profile_config()
    assert config["app_dir"] == tmp_path / "custom-app"
    assert config["gateway_dir"] == tmp_path / "custom-gateway"


def test_binding_creates_and_enforces_profile_and_storage_role(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    app = tmp_path / "app"
    marker = bind_runtime(app, "app")
    assert marker["runtime_profile"] == "demo"
    assert json.loads((app / MARKER).read_text()) == {
        "version": 1, "runtime_profile": "demo", "role": "app"
    }
    assert bind_runtime(app, "app")["root"] == str(app)
    with pytest.raises(ValueError, match="mismatch"):
        bind_runtime(app, "gateway")
    with pytest.raises(ValueError, match="already fixed"):
        bind_runtime(app, "app", "production")


def test_unmarked_populated_legacy_directory_requires_explicit_migration(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    old = tmp_path / "old"
    old.mkdir()
    (old / "app.sqlite").write_bytes(b"db")
    with pytest.raises(ValueError, match="migrate explicitly"):
        bind_runtime(old, "app")
    migrate_legacy_runtime(old, "app", "production", "production")
    assert json.loads((old / MARKER).read_text())["runtime_profile"] == "production"
    with pytest.raises(ValueError, match="retain its declared"):
        migrate_legacy_runtime(old, "app", "demo", "production")


def test_fresh_runtime_can_be_bound_before_manifest_is_preloaded(monkeypatch, tmp_path):
    from lexaegis.runtime_profile import BINDING_LOCK

    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    root = tmp_path / "app"
    bind_runtime(root, "app")
    (root / "release-build-manifest.json").write_text('{"status":"pending"}')
    assert bind_runtime(root, "app")["runtime_profile"] == "production"
    assert (root / BINDING_LOCK).is_file()


def test_symlink_data_path_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        bind_runtime(alias, "app")


def test_concurrent_profiles_cannot_claim_one_empty_directory(tmp_path):
    target = tmp_path / "shared"
    source = "from lexaegis.runtime_profile import bind_runtime; import sys; bind_runtime(sys.argv[1], 'app')"

    def attempt(profile):
        env = {**os.environ, "LEX_RUN_PROFILE": profile}
        return subprocess.run(
            [sys.executable, "-c", source, str(target)],
            env=env, capture_output=True, text=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("production", "demo")))
    assert sorted(item.returncode for item in results) == [0, 1]
    marker = json.loads((target / MARKER).read_text())
    assert marker["runtime_profile"] in ("production", "demo")


@pytest.mark.parametrize("profile", ["demo", "integration"])
def test_synthetic_profiles_accept_only_bundled_scenarios(monkeypatch, profile):
    monkeypatch.setenv("LEX_RUN_PROFILE", profile)
    validate_case_creation("success")
    require_case_scope({
        "mode": "demo", "scenario": "success", "runtime_profile": profile,
        "data_origin": "bundled_synthetic",
        "synthetic_manifest_hash": digest(SCENARIOS["success"]),
    })
    with pytest.raises(ValueError):
        validate_case_creation(None)
    with pytest.raises(ValueError):
        require_case_scope({"mode": "formal", "scenario": None})


def test_production_rejects_demo_and_mock_transport(monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    validate_case_creation(None)
    with pytest.raises(ValueError):
        validate_case_creation("success")
    with pytest.raises(ValueError):
        require_case_scope({"mode": "demo", "scenario": "success"})
    with pytest.raises(ValueError):
        validate_transport({"mode": "formal"}, "mock")


def test_demo_transport_and_integration_transport_constraints(monkeypatch):
    case = {"mode": "demo", "scenario": "success", "runtime_profile": "demo",
            "data_origin": "bundled_synthetic",
            "synthetic_manifest_hash": digest(SCENARIOS["success"])}
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    validate_transport(case, "mock")
    with pytest.raises(ValueError, match="offline"):
        validate_transport(case, "cloud")
    monkeypatch.setenv("LEX_RUN_PROFILE", "integration")
    validate_transport({**case, "runtime_profile": "integration"}, "cloud")
    with pytest.raises(ValueError):
        validate_transport({**case, "runtime_profile": "integration"}, "mock")


def test_dispatch_scope_requires_profile_and_synthetic_manifest(monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "integration")
    dependencies = {
        "runtime_profile": "integration",
        "data_origin": "bundled_synthetic",
        "synthetic_manifest_hash": digest(SCENARIOS["success"]),
    }
    request = {"mode": "demo", "transport": "cloud", "dependencies": dependencies}
    assert dispatch_scope(request)["allowed"] is True
    assert synthetic_manifest_hash("success") == digest(SCENARIOS["success"])
    with pytest.raises(ValueError, match="does not match"):
        dispatch_scope({**request, "dependencies": {**dependencies, "runtime_profile": "demo"}})
    with pytest.raises(ValueError, match="manifest"):
        dispatch_scope({**request, "dependencies": {**dependencies, "synthetic_manifest_hash": None}})


def test_demo_dispatch_is_never_cloud(monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    with pytest.raises(ValueError, match="offline"):
        dispatch_scope({"mode": "demo", "transport": "cloud", "dependencies": {
            "runtime_profile": "demo", "data_origin": "bundled_synthetic",
            "synthetic_manifest_hash": digest(SCENARIOS["success"]),
        }})


def test_backup_restore_round_trips_controlled_blobs_and_rejects_other_profile(monkeypatch, tmp_path):
    from lexaegis.cli import backup, restore
    from lexaegis.runtime_profile import bind_runtime
    from lexaegis.storage import Store

    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_RELEASE_IMAGE", "lexaegis:test-sha")
    monkeypatch.setenv("LEX_ROUTE_IMAGE", "alpine:test-sha")
    app = tmp_path / "app"
    gateway = tmp_path / "gateway"
    bind_runtime(app, "app")
    bind_runtime(gateway, "gateway")
    Store(app / "app.sqlite")
    Store(gateway / "gateway.sqlite")
    blobs = {
        "files/materials/document.bin": b"source-document-bytes",
        "legal-evidence/receipts/receipt.json": b'{"id":"receipt-1"}',
        "release-evidence/sha256/evidence.bin": b"release-evidence-bytes",
        "api-runtime-identity.json": b'{"build":"test"}',
        "worker-runtime-identity.json": b'{"build":"test"}',
        "release-build-manifest.json": b'{"status":"pending"}',
    }
    for relative, content in blobs.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    archive = tmp_path / "backup.lexbackup"
    backup(app, gateway, archive)
    with zipfile.ZipFile(archive) as saved:
        names = saved.namelist()
        assert "app/legal-evidence/receipts/receipt.json" in names
        assert "app/release-evidence/sha256/evidence.bin" in names
        assert "app/release-build-manifest.json" in names
        backup_manifest = json.loads(saved.read("manifest.json"))
        assert backup_manifest["release_image"] == "lexaegis:test-sha"
        assert backup_manifest["route_image"] == "alpine:test-sha"
        assert not any("secret" in name or "password" in name for name in names)

    restored_app, restored_gateway = tmp_path / "restored-app", tmp_path / "restored-gateway"
    restore(archive, restored_app, restored_gateway)
    for relative, content in blobs.items():
        assert (restored_app / relative).read_bytes() == content

    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    with pytest.raises(ValueError, match="profile"):
        restore(archive, tmp_path / "wrong-app", tmp_path / "wrong-gateway")
