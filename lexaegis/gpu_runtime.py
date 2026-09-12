"""Serialize GPU stages. Do not rely on Windows shared VRAM."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .edge_runtime import edge_port_open, edge_status, start_edge, stop_edge
from .util import app_dir, exclusive_lock

IDLE_UNLOAD_SECONDS = 300
_STATE = {
    "last_extract_at": 0.0,
    "edge_owned": False,
}
_STATE_LOCK = threading.Lock()


def gpu_lock_path() -> Path:
    return app_dir() / "gpu.lock"


def idle_unload_seconds() -> int:
    raw = os.getenv("LEX_EDGE_IDLE_UNLOAD_SECONDS")
    if raw is None or raw == "":
        return IDLE_UNLOAD_SECONDS
    return max(0, int(raw))


def mark_extract_activity() -> None:
    with _STATE_LOCK:
        _STATE["last_extract_at"] = time.time()


def unload_edge() -> dict:
    result = stop_edge()
    with _STATE_LOCK:
        _STATE["edge_owned"] = False
    return result


def ensure_edge_loaded(wait=30) -> dict:
    status = edge_status()
    if status["listening"]:
        with _STATE_LOCK:
            _STATE["edge_owned"] = True
        mark_extract_activity()
        return {**status, "started": False}
    if not status["binary_present"] or not status["weights_present"]:
        return status
    try:
        report = start_edge(wait=wait)
    except (FileNotFoundError, RuntimeError, TimeoutError):
        return edge_status()
    with _STATE_LOCK:
        _STATE["edge_owned"] = bool(report.get("started") or edge_port_open())
    mark_extract_activity()
    return report


def maybe_idle_unload() -> dict | None:
    seconds = idle_unload_seconds()
    if seconds <= 0:
        return None
    with _STATE_LOCK:
        last = _STATE["last_extract_at"]
        owned = _STATE["edge_owned"]
    if not owned or last <= 0:
        return None
    if time.time() - last < seconds:
        return None
    if not edge_port_open():
        with _STATE_LOCK:
            _STATE["edge_owned"] = False
        return None
    return unload_edge()


def parse_uses_gpu(path: Path) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix in {".mp3", ".m4a", ".wav", ".mp4"}:
        return os.getenv("LEX_WHISPER_ENABLED") == "1"
    if suffix in {".png", ".jpg", ".jpeg", ".pdf"}:
        return os.getenv("LEX_OCR_ENABLED") == "1" and os.getenv("LEX_OCR_PROVIDER", "rapidocr") == "rapidocr"
    return False


@contextmanager
def gpu_stage(kind: str):
    """kind is cpu, ocr, whisper, or extract. OCR/whisper unload the 2B server first."""
    app_dir().mkdir(parents=True, exist_ok=True)
    with exclusive_lock(gpu_lock_path(), error=RuntimeError("GPU 阶段锁被占用")):
        if kind in ("ocr", "whisper"):
            if edge_port_open():
                unload_edge()
            try:
                yield
            finally:
                pass
            return
        if kind == "extract":
            ensure_edge_loaded()
            try:
                yield
            finally:
                mark_extract_activity()
            return
        yield


def parse_in_aux_process(path: Path, document_id: str, version=1) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "lexaegis.gpu_aux", "parse", str(path), document_id, str(version)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "GPU 辅助解析失败").strip()[-500:]
        raise RuntimeError(detail)
    return json.loads(completed.stdout)
