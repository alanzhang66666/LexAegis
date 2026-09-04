"""Launch built UI, API, single worker and gateway. No automatic cloud calls."""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if (ROOT / ".env").exists():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
if not (ROOT / "frontend/dist/index.html").exists():
    raise SystemExit("请先执行前端构建：cd frontend && pnpm build")

# Import after chdir so package resolution matches the repo root.
sys.path.insert(0, str(ROOT))
from lexaegis.util import restrict_mode

data = Path(os.getenv("LEX_DATA_DIR", ".data/app"))
data.mkdir(parents=True, exist_ok=True)
restrict_mode(data, 0o700)
for env_name, filename in [("LEX_LOCAL_PASSWORD", "local-password"), ("LEX_GATEWAY_SECRET", "gateway-secret")]:
    if not os.getenv(env_name):
        path = data / filename
        if not path.exists():
            path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
            restrict_mode(path, 0o600)
        os.environ[env_name] = path.read_text(encoding="utf-8").strip()
base = os.environ.copy()
base["PYTHONUNBUFFERED"] = "1"
app_env = {k: v for k, v in base.items() if k != "LEX_CLOUD_API_KEY"}
gateway_env = {k: v for k, v in base.items() if k not in ("LEX_LOCAL_PASSWORD", "LEX_EDGE_MODEL", "LEX_EDGE_URL")}
processes = []
spawn_kwargs = {}
if os.name == "nt":
    spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
print("\nLexAegis: http://127.0.0.1:8765", flush=True)
print("本地访问口令:", os.environ["LEX_LOCAL_PASSWORD"], flush=True)
print("本机开发模式：未验证操作系统级网络隔离。真实案件外发保持阻断。\n", flush=True)
try:
    for args, env in [
        (["-m", "uvicorn", "lexaegis.gateway:create_gateway", "--factory", "--host", "127.0.0.1", "--port", "8766", "--no-access-log"], gateway_env),
        (["-m", "uvicorn", "lexaegis.api:create_app", "--factory", "--host", "127.0.0.1", "--port", "8765", "--no-access-log"], app_env),
    ]:
        processes.append(subprocess.Popen([sys.executable, *args], env=env, **spawn_kwargs))
    # Initialize the API database before starting the worker.
    import httpx
    for _ in range(50):
        try:
            if httpx.get("http://127.0.0.1:8765/api/v1/health", timeout=1, trust_env=False).is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    else:
        raise RuntimeError("API 启动失败")
    processes.append(subprocess.Popen([sys.executable, "-m", "lexaegis.worker"], env=app_env, **spawn_kwargs))
    while all(p.poll() is None for p in processes):
        time.sleep(0.5)
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
