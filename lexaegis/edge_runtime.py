"""Local llama-server probe and optional start. Does not download weights."""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CTX_SIZE = 32768
DEFAULT_BATCH_SIZE = 2048
DEFAULT_UBATCH_SIZE = 512
DEFAULT_PARALLEL = 1
_OOM_MARKERS = (
    "out of memory",
    "outofmemory",
    "cuda malloc",
    "failed to allocate",
    "ggml_gallocr",
    "insufficient memory",
    "vram",
)
_FLASH_MARKERS = ("flash attn", "flash-attn", "flash_attn")


def edge_listen_address():
    parsed = urlparse(os.getenv("LEX_EDGE_URL", "http://127.0.0.1:8080/v1"))
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        port = parsed.port
    else:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def edge_port_open(timeout=0.4) -> bool:
    host, port = edge_listen_address()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_llama_bin() -> Path:
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    configured = os.getenv("LEX_EDGE_BIN")
    if configured:
        return Path(configured)
    return repo_root() / ".artifacts" / "llama-server" / name


def default_gguf() -> Path:
    configured = os.getenv("LEX_EDGE_GGUF")
    if configured:
        return Path(configured)
    return repo_root() / "models" / "MiniCPM5-2B-Q4_K_M.gguf"


def edge_pid_path() -> Path:
    configured = os.getenv("LEX_EDGE_PID_FILE")
    if configured:
        return Path(configured)
    return repo_root() / ".artifacts" / "llama-server" / "llama-server.pid"


def _int_env(name, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _flash_attn_flag():
    raw = (os.getenv("LEX_EDGE_FLASH_ATTN") or "on").strip().lower()
    if raw in ("0", "off", "false", "no"):
        return "off"
    return "on"


def start_command(ctx_size=None, ubatch_size=None, flash_attn=None):
    host, port = edge_listen_address()
    alias = os.getenv("LEX_EDGE_MODEL") or "edge-small"
    ctx = ctx_size if ctx_size is not None else _int_env("LEX_EDGE_CTX_SIZE", DEFAULT_CTX_SIZE)
    batch = _int_env("LEX_EDGE_BATCH_SIZE", DEFAULT_BATCH_SIZE)
    ubatch = ubatch_size if ubatch_size is not None else _int_env("LEX_EDGE_UBATCH_SIZE", DEFAULT_UBATCH_SIZE)
    parallel = _int_env("LEX_EDGE_PARALLEL", DEFAULT_PARALLEL)
    flash = flash_attn if flash_attn is not None else _flash_attn_flag()
    return [
        str(default_llama_bin()),
        "--model", str(default_gguf()),
        "--host", host,
        "--port", str(port),
        "--alias", alias,
        "--jinja",
        "--ctx-size", str(ctx),
        "--batch-size", str(batch),
        "--ubatch-size", str(ubatch),
        "--parallel", str(parallel),
        "--cache-type-k", "f16",
        "--cache-type-v", "f16",
        "--n-gpu-layers", os.getenv("LEX_EDGE_N_GPU_LAYERS", "99"),
        "--flash-attn", flash,
    ]


def start_hint() -> str:
    host, port = edge_listen_address()
    return (
        f"边侧未在 {host}:{port} 监听。正式案抽取可先运行 `lexaegis edge --start`，"
        f"或手动执行：{' '.join(start_command())}"
    )


def edge_status() -> dict:
    host, port = edge_listen_address()
    listening = edge_port_open()
    binary = default_llama_bin()
    weights = default_gguf()
    return {
        "status": "available" if listening else "unconfigured",
        "listening": listening,
        "host": host,
        "port": port,
        "binary": str(binary),
        "binary_present": binary.is_file(),
        "weights": str(weights),
        "weights_present": weights.is_file(),
        "hint": None if listening else start_hint(),
    }


def _read_stderr_tail(path: Path, limit=4000) -> str:
    try:
        data = Path(path).read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace").strip()


def _edge_spawn_error(prefix: str, stderr_path: Path) -> str:
    detail = _read_stderr_tail(stderr_path)
    return f"{prefix}：{detail}" if detail else prefix


def _stop_edge_process(process, timeout=3):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _write_pid(pid: int) -> None:
    path = edge_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _read_pid() -> int | None:
    path = edge_pid_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int, force=False) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        subprocess.run(args, capture_output=True, timeout=8)
        return
    try:
        os.kill(pid, 9 if force else 15)
    except OSError:
        pass


def _clear_pid(pid=None) -> None:
    path = edge_pid_path()
    if pid is not None:
        current = _read_pid()
        if current is not None and current != pid:
            return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _stderr_looks_like_oom(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _OOM_MARKERS)


def _stderr_looks_like_flash(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _FLASH_MARKERS) and any(
        token in lowered for token in ("unknown", "invalid", "unsupported", "not support", "error")
    )


def _fallback_attempts():
    ctx = _int_env("LEX_EDGE_CTX_SIZE", DEFAULT_CTX_SIZE)
    ubatch = _int_env("LEX_EDGE_UBATCH_SIZE", DEFAULT_UBATCH_SIZE)
    flash = _flash_attn_flag()
    attempts = [(ctx, ubatch, flash)]
    reduced_batch = ubatch
    while reduced_batch > 128:
        reduced_batch = max(128, reduced_batch // 2)
        attempts.append((ctx, reduced_batch, flash))
        if reduced_batch == 128:
            break
    reduced_ctx = ctx
    while reduced_ctx > 8192:
        reduced_ctx = max(8192, reduced_ctx // 2)
        attempts.append((reduced_ctx, 128 if ubatch >= 128 else ubatch, flash))
        if reduced_ctx == 8192:
            break
    seen = []
    for item in attempts:
        if item not in seen:
            seen.append(item)
    return seen


def _spawn_once(command, wait):
    spawn = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    stderr_file = tempfile.NamedTemporaryFile(prefix="lex-edge-", suffix=".stderr", delete=False)
    stderr_path = Path(stderr_file.name)
    process = None
    started = False
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr_file, **spawn)
        stderr_file.close()
        deadline = time.time() + wait
        while time.time() < deadline:
            if edge_port_open():
                started = True
                _write_pid(process.pid)
                return {**edge_status(), "started": True, "pid": process.pid, "command": command}
            if process.poll() is not None:
                raise RuntimeError(_edge_spawn_error("llama-server 已退出；请检查权重、CUDA 与端口", stderr_path))
            time.sleep(0.4)
        raise TimeoutError(_edge_spawn_error("llama-server 已拉起但端口尚未就绪", stderr_path))
    finally:
        if not stderr_file.closed:
            stderr_file.close()
        if process is not None and not started:
            _stop_edge_process(process)
        if not started:
            try:
                stderr_path.unlink(missing_ok=True)
            except OSError:
                pass


def start_edge(wait=30):
    status = edge_status()
    if status["listening"]:
        return {**status, "started": False, "detail": "边侧已在监听，未再次启动"}
    if not status["binary_present"]:
        raise FileNotFoundError(f"未找到 llama-server：{status['binary']}")
    if not status["weights_present"]:
        raise FileNotFoundError(f"未找到边侧权重：{status['weights']}")
    last_error = None
    flash = _flash_attn_flag()
    tried_flash_off = flash == "off"
    first = True
    for ctx, ubatch, attn in _fallback_attempts():
        command = start_command() if first else start_command(ctx_size=ctx, ubatch_size=ubatch, flash_attn=attn)
        first = False
        try:
            return _spawn_once(command, wait)
        except RuntimeError as error:
            last_error = error
            detail = str(error)
            if _stderr_looks_like_flash(detail) and not tried_flash_off:
                tried_flash_off = True
                try:
                    return _spawn_once(start_command(ctx_size=ctx, ubatch_size=ubatch, flash_attn="off"), wait)
                except RuntimeError as inner:
                    last_error = inner
                    detail = str(inner)
            if not _stderr_looks_like_oom(detail):
                raise
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("llama-server 启动失败")


def stop_edge(timeout=8) -> dict:
    pid = _read_pid()
    listening = edge_port_open()
    if pid is None and not listening:
        return {"stopped": False, "detail": "边侧未在监听"}
    if pid is not None and _pid_alive(pid):
        _terminate_pid(pid, force=False)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _pid_alive(pid) and not edge_port_open():
                _clear_pid(pid)
                return {"stopped": True, "pid": pid}
            time.sleep(0.2)
        _terminate_pid(pid, force=True)
        time.sleep(0.2)
        _clear_pid(pid)
        return {"stopped": True, "pid": pid, "detail": "已强制结束边侧进程"}
    if not edge_port_open():
        _clear_pid(pid)
        return {"stopped": True, "pid": pid, "detail": "边侧进程已退出"}
    return {"stopped": False, "detail": "边侧仍在监听，但没有本进程记录的 PID，未强杀外部进程"}
