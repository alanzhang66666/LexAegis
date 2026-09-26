"""Cross-platform native process launcher."""
import ipaddress
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .util import app_dir, restrict_mode

CLOUD_KEY_ENV = ("LEX_CLOUD_API_KEY", "LEX_CLOUD_PRIMARY_KEY", "LEX_CLOUD_STANDBY_KEY")
DEFAULT_BIND_HOST = "127.0.0.1"
# The gateway holds the cloud credentials; only the in-container worker may reach it.
GATEWAY_BIND_HOST = "127.0.0.1"


def app_process_env(base):
    return {key: value for key, value in base.items() if key not in CLOUD_KEY_ENV}


def service_ports():
    from .runtime_profile import profile_config
    config = profile_config()
    return str(config["api_port"]), str(config["gateway_port"])


def api_bind_host():
    """Workbench bind address. Container images set 0.0.0.0; native stays on loopback."""
    raw = (os.getenv("LEX_BIND_HOST") or DEFAULT_BIND_HOST).strip()
    if not raw:
        return DEFAULT_BIND_HOST
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        raise SystemExit(
            f"LEX_BIND_HOST 必须是 IP 字面量（收到 {raw!r}）。"
            f"本机运行用 {DEFAULT_BIND_HOST}；容器内用 0.0.0.0 并只发布到宿主机回环口。"
        )
    return raw


def bind_host_is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


_LAUNCHER_ROLES = ("gateway", "api", "worker")


def launcher_roles() -> tuple[str, ...]:
    """Roles this launcher supervises; isolated deployments split them across services."""
    raw = os.getenv("LEX_LAUNCHER_ROLES", ",".join(_LAUNCHER_ROLES))
    roles = tuple(role.strip() for role in raw.split(",") if role.strip())
    unknown = [role for role in roles if role not in _LAUNCHER_ROLES]
    if unknown:
        raise ValueError(f"unknown launcher roles: {unknown}")
    return roles


def service_commands(api_port, gateway_port, bind_host):
    """Gateway is never published. Only the API honours LEX_BIND_HOST."""
    return [
        [sys.executable, "-m", "uvicorn", "lexaegis.gateway:create_gateway", "--factory",
         "--host", GATEWAY_BIND_HOST, "--port", str(gateway_port), "--no-access-log"],
        [sys.executable, "-m", "uvicorn", "lexaegis.api:create_app", "--factory",
         "--host", str(bind_host), "--port", str(api_port), "--no-access-log"],
    ]


def _is_loopback_host(host):
    return bool(host) and host.lower() in {"127.0.0.1", "localhost", "::1"}


def align_local_gateway_url(url, gateway_port):
    port = str(gateway_port)
    if not url:
        return f"http://127.0.0.1:{port}"
    parsed = urlparse(url)
    host = parsed.hostname
    if not _is_loopback_host(host):
        return url
    current = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    if str(current) == port:
        return url
    hostname = host
    netloc = f"[{hostname}]:{port}" if ":" in hostname else f"{hostname}:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def run(profile=None):
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv
        load_dotenv(env_file)
    if frontend_location() is None:
        raise SystemExit("未找到前端构建产物。源码开发请先执行：cd frontend && pnpm build")
    from .runtime_profile import bind_runtime, profile_config
    config = profile_config(profile)
    os.environ["LEX_DATA_DIR"] = str(config["app_dir"])
    os.environ["LEX_GATEWAY_DIR"] = str(config["gateway_dir"])
    os.environ["LEX_API_PORT"] = str(config["api_port"])
    os.environ["LEX_GATEWAY_PORT"] = str(config["gateway_port"])
    roles = launcher_roles()
    bind_runtime(config["app_dir"], "app", config["runtime_profile"])
    if "gateway" in roles:
        bind_runtime(config["gateway_dir"], "gateway", config["runtime_profile"])
    root = app_dir()
    root.mkdir(parents=True, exist_ok=True)
    restrict_mode(root, 0o700)
    for env_name, filename in (("LEX_LOCAL_PASSWORD", "local-password"), ("LEX_GATEWAY_SECRET", "gateway-secret")):
        if not os.getenv(env_name):
            path = root / filename
            if not path.exists():
                path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
                restrict_mode(path, 0o600)
            os.environ[env_name] = path.read_text(encoding="utf-8").strip()
    base = os.environ.copy()
    base.update(PYTHONUNBUFFERED="1",
                LEX_DEPLOYMENT_MODE=os.environ.get("LEX_DEPLOYMENT_MODE") or "native",
                LEX_RUN_PROFILE=config["runtime_profile"])
    app_env = app_process_env(base)
    gateway_env = {key: value for key, value in base.items() if key not in ("LEX_LOCAL_PASSWORD", "LEX_EDGE_MODEL", "LEX_EDGE_URL")}
    if config["runtime_profile"] == "demo":
        gateway_env = app_process_env(gateway_env)
    spawn = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    api_port, gateway_port = service_ports()
    gateway_url = align_local_gateway_url(os.getenv("LEX_GATEWAY_URL"), gateway_port)
    if os.getenv("LEX_GATEWAY_URL") != gateway_url:
        os.environ["LEX_GATEWAY_URL"] = gateway_url
        base["LEX_GATEWAY_URL"] = gateway_url
        app_env = app_process_env(base)
    bind_host = api_bind_host()
    gateway_command, api_command = service_commands(api_port, gateway_port, bind_host)
    command_by_role = {"gateway": (gateway_command, gateway_env), "api": (api_command, app_env)}
    commands = [command_by_role[role] for role in ("gateway", "api") if role in roles]
    processes = []
    print(f"LexAegis ({config['runtime_profile']}): http://127.0.0.1:{api_port}")
    print("本地访问口令:", os.environ["LEX_LOCAL_PASSWORD"])
    if base["LEX_DEPLOYMENT_MODE"] == "native":
        print("native 模式不具备可验证网络隔离；仅 Compose demo 配置提供无出口演示隔离。")
    if not bind_host_is_loopback(bind_host):
        print(f"工作台已绑定 {bind_host}：请只发布到宿主机回环口"
              f"（docker run -p 127.0.0.1:{api_port}:{api_port}），不要暴露到局域网。")
        print(f"宿主机端口若不是 {api_port}，须同步设置 LEX_API_PORT，否则写操作会被跨站校验拒绝。")
    from .edge_runtime import edge_port_open, start_hint
    if not edge_port_open():
        print(start_hint())
    # Development/test supervisors stop the launcher with SIGTERM. Translate
    # it to the same cleanup path as Ctrl+C so detached service groups do not
    # keep their ports and inherited output pipes open after the parent exits.
    def stop_requested(_signum, _frame):
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, stop_requested)
    try:
        for command, environment in commands:
            processes.append(subprocess.Popen(command, env=environment, **spawn))
        if "api" in roles:
            import httpx
            for _ in range(50):
                try:
                    if httpx.get(f"http://127.0.0.1:{api_port}/api/v1/health", timeout=1, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError("API 启动失败")
        if "worker" in roles:
            processes.append(subprocess.Popen([sys.executable, "-m", "lexaegis.worker"], env=app_env, **spawn))
        while all(process.poll() is None for process in processes):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        signal.signal(signal.SIGTERM, previous_sigterm)


def frontend_location() -> Path | None:
    installed = Path(__file__).resolve().parent / "frontend" / "index.html"
    source = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
    return installed if installed.exists() else source if source.exists() else None
