"""Cross-platform native process launcher."""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .util import app_dir, restrict_mode

CLOUD_KEY_ENV = ("LEX_CLOUD_API_KEY", "LEX_CLOUD_PRIMARY_KEY", "LEX_CLOUD_STANDBY_KEY")


def app_process_env(base):
    return {key: value for key, value in base.items() if key not in CLOUD_KEY_ENV}


def service_ports():
    return os.getenv("LEX_API_PORT", "8765"), os.getenv("LEX_GATEWAY_PORT", "8766")


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


def run():
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv
        load_dotenv(env_file)
    if frontend_location() is None:
        raise SystemExit("未找到前端构建产物。源码开发请先执行：cd frontend && pnpm build")
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
    base.update(PYTHONUNBUFFERED="1", LEX_DEPLOYMENT_MODE="native")
    app_env = app_process_env(base)
    gateway_env = {key: value for key, value in base.items() if key not in ("LEX_LOCAL_PASSWORD", "LEX_EDGE_MODEL", "LEX_EDGE_URL")}
    spawn = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    api_port, gateway_port = service_ports()
    gateway_url = align_local_gateway_url(os.getenv("LEX_GATEWAY_URL"), gateway_port)
    if os.getenv("LEX_GATEWAY_URL") != gateway_url:
        os.environ["LEX_GATEWAY_URL"] = gateway_url
        base["LEX_GATEWAY_URL"] = gateway_url
        app_env = app_process_env(base)
    commands = [
        ([sys.executable, "-m", "uvicorn", "lexaegis.gateway:create_gateway", "--factory", "--host", "127.0.0.1", "--port", gateway_port, "--no-access-log"], gateway_env),
        ([sys.executable, "-m", "uvicorn", "lexaegis.api:create_app", "--factory", "--host", "127.0.0.1", "--port", api_port, "--no-access-log"], app_env),
    ]
    processes = []
    print(f"LexAegis: http://127.0.0.1:{api_port}")
    print("本地访问口令:", os.environ["LEX_LOCAL_PASSWORD"])
    print("native 模式不具备可验证网络隔离，正式外发保持阻断。")
    from .edge_runtime import edge_port_open, start_hint
    if not edge_port_open():
        print(start_hint())
    try:
        for command, environment in commands:
            processes.append(subprocess.Popen(command, env=environment, **spawn))
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
        processes.append(subprocess.Popen([sys.executable, "-m", "lexaegis.worker"], env=app_env, **spawn))
        while all(process.poll() is None for process in processes):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def frontend_location() -> Path | None:
    installed = Path(__file__).resolve().parent / "frontend" / "index.html"
    source = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
    return installed if installed.exists() else source if source.exists() else None
