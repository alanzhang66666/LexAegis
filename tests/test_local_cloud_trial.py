"""The local trial must keep credentials out of model processes."""
import importlib.util
from pathlib import Path

import pytest


def load_controller():
    path = Path(__file__).parents[1] / "scripts/windows/local-cloud-trial.py"
    spec = importlib.util.spec_from_file_location("local_trial_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("role", ["api", "worker", "gateway", "model"])
def test_trial_process_credentials_are_role_scoped(monkeypatch, role):
    module = load_controller()
    monkeypatch.setenv("LEX_CLOUD_PRIMARY_KEY", "synthetic-primary-key")
    monkeypatch.setenv("LEX_CLOUD_API_KEY", "synthetic-legacy-key")
    monkeypatch.setenv("LEX_LOCAL_PASSWORD", "synthetic-inherited-password")
    env = module.environment({"gateway-secret": "synthetic-signing-key", "local-password": "synthetic-login"}, role)
    assert not any(key.startswith("LEX_CLOUD_") for key in env)
    assert ("LEX_GATEWAY_SECRET" in env) == (role in {"api", "worker", "gateway"})
    assert ("LEX_LOCAL_PASSWORD" in env) == (role == "api")
    if role == "model":
        assert not any(key.startswith("LEX_") for key in env)
    if role == "gateway":
        assert "LEX_DATA_DIR" not in env
        assert "LEX_EDGE_URL" not in env


def test_trial_refuses_occupied_port_without_spawning(tmp_path, monkeypatch):
    module = load_controller()
    monkeypatch.setattr(module, "TRIAL", tmp_path)
    monkeypatch.setattr(module, "STATE", tmp_path / "state.json")
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup/ASSETS.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "occupied", lambda port: True)
    monkeypatch.setattr(module, "credentials", lambda: pytest.fail("must not create credentials or spawn"))
    with pytest.raises(RuntimeError, match="in use"):
        module.start()
