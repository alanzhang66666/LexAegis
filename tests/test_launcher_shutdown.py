import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM supervisor cleanup; Windows bundle uses Compose")
def test_sigterm_during_startup_reaps_already_started_services(tmp_path):
    probe = tmp_path / "shutdown_probe.py"
    probe.write_text(textwrap.dedent("""
        import os, signal
        from pathlib import Path
        from types import SimpleNamespace
        import httpx
        from lexaegis import launcher, edge_runtime

        original_handler = signal.getsignal(signal.SIGTERM)
        children = []
        class Child:
            def __init__(self):
                self.terminated = False
                self.reaped = False
            def poll(self):
                return None if not self.terminated else 0
            def terminate(self):
                self.terminated = True
            def wait(self, timeout):
                assert self.terminated
                self.reaped = True
        def start(*args, **kwargs):
            if len(children) == 2:
                os.kill(os.getpid(), signal.SIGTERM)
            child = Child()
            children.append(child)
            return child
        launcher.subprocess.Popen = start
        launcher.frontend_location = lambda: Path(__file__)
        edge_runtime.edge_port_open = lambda: True
        httpx.get = lambda *args, **kwargs: SimpleNamespace(is_success=True)
        launcher.run('demo')
        assert len(children) == 2
        assert all(child.terminated and child.reaped for child in children)
        assert signal.getsignal(signal.SIGTERM) == original_handler
    """), encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "LEX_RUN_PROFILE": "demo",
                   "LEX_PROFILE_ROOT": str(tmp_path / "profiles"), "LEX_LOCAL_PASSWORD": "test-only-password",
                   "LEX_GATEWAY_SECRET": "test-only-signing-secret-32-characters"}
    environment.pop("LEX_DATA_DIR", None)
    environment.pop("LEX_GATEWAY_DIR", None)
    result = subprocess.run([sys.executable, str(probe)], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
