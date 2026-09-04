"""Read-only runtime and isolation diagnostics."""
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

from .launcher import frontend_location
from .util import app_dir


def doctor_report() -> dict:
    root = app_dir()
    checks = {
        "python": {"ok": sys.version_info >= (3, 12), "detail": platform.python_version()},
        "platform": {"ok": sys.platform.startswith(("win", "linux", "darwin")), "detail": f"{platform.system()} {platform.machine()}"},
        "data_directory": {"ok": root.exists() and os.access(root, os.R_OK | os.W_OK), "detail": str(root)},
        "frontend": {"ok": frontend_location() is not None, "detail": str(frontend_location() or "未构建")},
        "deployment_mode": {"ok": os.getenv("LEX_DEPLOYMENT_MODE", "native") in ("native", "isolated"), "detail": os.getenv("LEX_DEPLOYMENT_MODE", "native")},
        "edge_model": {"ok": bool(os.getenv("LEX_EDGE_MODEL")), "detail": "已配置" if os.getenv("LEX_EDGE_MODEL") else "可选，未配置时人工录入事实"},
    }
    return {"ok": all(item["ok"] for key, item in checks.items() if key != "edge_model"), "checks": checks}


def isolation_report(timeout=.4) -> dict:
    mode = os.getenv("LEX_DEPLOYMENT_MODE", "native")
    role = os.getenv("LEX_RUNTIME_ROLE", "")
    isolated_flag = os.getenv("LEX_ISOLATED") == "1"
    outbound_blocked = False
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            outbound_blocked = False
    except OSError:
        outbound_blocked = True
    checks = {
        "isolated_mode": mode == "isolated" and isolated_flag,
        "api_or_worker_role": role in ("api", "worker"),
        "outbound_probe_blocked": outbound_blocked,
        "gateway_secret_not_reported": True,
    }
    return {"ok": all(checks.values()), "checks": checks, "detail": "单次探测只形成部署自检记录，不能替代防火墙审计。"}


def compose_isolation_report() -> dict:
    probes = {
        "api_no_egress": ["docker", "compose", "exec", "-T", "api", "python", "-c", "import socket; s=socket.socket(); s.settimeout(3); assert s.connect_ex(('1.1.1.1',443)) != 0"],
        "worker_no_egress": ["docker", "compose", "exec", "-T", "worker", "python", "-c", "import socket; s=socket.socket(); s.settimeout(3); assert s.connect_ex(('1.1.1.1',443)) != 0"],
        "gateway_no_case_volume": ["docker", "compose", "exec", "-T", "gateway", "python", "-c", "from pathlib import Path; assert not Path('/data/app.sqlite').exists(); assert not Path('/data/files').exists()"],
        "redteam_no_secrets": ["docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "python", "redteam", "-c", "import os; from pathlib import Path; assert not os.getenv('LEX_GATEWAY_SECRET'); assert not Path('/data/app.sqlite').exists()"],
        "benchmark_no_secrets": ["docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "python", "benchmark", "-c", "import os; from pathlib import Path; assert not os.getenv('LEX_GATEWAY_SECRET'); assert not Path('/data/app.sqlite').exists()"],
    }
    checks = {}
    details = {}
    for name, command in probes.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as error:
            return {"ok": False, "checks": checks, "details": {"runtime": str(error)}, "detail": "Docker Compose 不可用，未记录隔离验收。"}
        checks[name] = result.returncode == 0
        details[name] = (result.stderr or result.stdout).strip()[-500:]
    return {"ok": all(checks.values()), "checks": checks, "details": details,
            "detail": "运行态探测不能替代宿主机防火墙、卷权限和镜像供应链审计。"}
