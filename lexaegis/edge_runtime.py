"""Local llama-server probe and optional start. Does not download weights."""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


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


def start_command():
    host, port = edge_listen_address()
    alias = os.getenv("LEX_EDGE_MODEL") or "edge-small"
    return [
        str(default_llama_bin()),
        "--model", str(default_gguf()),
        "--host", host,
        "--port", str(port),
        "--alias", alias,
        "--reasoning-budget", "0",
        "--reasoning", "off",
        "--jinja",
        "--ctx-size", "8192",
        "--n-gpu-layers", os.getenv("LEX_EDGE_N_GPU_LAYERS", "99"),
        "--flash-attn", "on",
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


def start_edge(wait=30):
    status = edge_status()
    if status["listening"]:
        return {**status, "started": False, "detail": "边侧已在监听，未再次启动"}
    if not status["binary_present"]:
        raise FileNotFoundError(f"未找到 llama-server：{status['binary']}")
    if not status["weights_present"]:
        raise FileNotFoundError(f"未找到边侧权重：{status['weights']}")
    command = start_command()
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
