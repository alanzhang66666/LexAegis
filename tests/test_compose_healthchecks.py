"""Regression tests for service-specific Compose liveness probes."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError

import pytest
import yaml

from lexaegis.gateway_health import probe


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.demo.yaml"])
def test_compose_process_roles_do_not_inherit_api_probe(filename):
    with (ROOT / filename).open(encoding="utf-8") as source:
        services = yaml.safe_load(source)["services"]
    assert services["gateway"]["healthcheck"]["test"] == ["CMD", "python", "-m", "lexaegis.gateway_health"]
    assert services["worker"]["healthcheck"] == {"disable": True}
    assert "8767" in str(services["redteam"]["healthcheck"]["test"])


def test_gateway_probe_authenticates_running_local_service(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    secret = "synthetic-gateway-health-secret-32"
    env = {**os.environ, "LEX_RUN_PROFILE": "demo", "LEX_GATEWAY_SECRET": secret,
           "LEX_GATEWAY_DIR": str(tmp_path / "gateway"), "LEX_CLOUD_API_KEY": "",
           "LEX_CLOUD_PRIMARY_KEY": "", "LEX_CLOUD_STANDBY_KEY": ""}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "lexaegis.gateway:create_gateway", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                probe(port, secret)
                break
            except (URLError, ConnectionError):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with pytest.raises(HTTPError) as invalid:
            probe(port, "wrong-secret")
        assert invalid.value.code == 403
        with pytest.raises(ValueError):
            probe(port, "")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
