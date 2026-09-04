"""Cross-platform native process launcher."""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from .util import app_dir, restrict_mode


def run():
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
    app_env = {key: value for key, value in base.items() if key != "LEX_CLOUD_API_KEY"}
    gateway_env = {key: value for key, value in base.items() if key not in ("LEX_LOCAL_PASSWORD", "LEX_EDGE_MODEL", "LEX_EDGE_URL")}
    spawn = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    commands = [
        ([sys.executable, "-m", "uvicorn", "lexaegis.gateway:create_gateway", "--factory", "--host", "127.0.0.1", "--port", "8766", "--no-access-log"], gateway_env),
        ([sys.executable, "-m", "uvicorn", "lexaegis.api:create_app", "--factory", "--host", "127.0.0.1", "--port", "8765", "--no-access-log"], app_env),
    ]
    processes = []
    print("LexAegis: http://127.0.0.1:8765")
    print("本地访问口令:", os.environ["LEX_LOCAL_PASSWORD"])
    print("native 模式不具备可验证网络隔离，正式外发保持阻断。")
    try:
        for command, environment in commands:
            processes.append(subprocess.Popen(command, env=environment, **spawn))
        import httpx
        for _ in range(50):
            try:
                if httpx.get("http://127.0.0.1:8765/api/v1/health", timeout=1, trust_env=False).is_success:
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
