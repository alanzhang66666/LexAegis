"""Local file transcription via FFmpeg + whisper.cpp. No cloud, no remote URLs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Protocol

from .edge_runtime import repo_root


class WhisperProvider(Protocol):
    provider_id: str
    version: str

    def health(self) -> dict: ...
    def transcribe(self, path: Path) -> Iterable[tuple[str, float, float, float | None]]: ...


def default_whisper_bin() -> Path:
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    configured = os.getenv("LEX_WHISPER_BIN")
    if configured:
        return Path(configured)
    artifact = repo_root() / ".artifacts" / "whisper" / name
    if artifact.is_file():
        return artifact
    found = shutil.which("whisper-cli") or shutil.which("whisper-cli.exe")
    return Path(found) if found else artifact


def default_whisper_model() -> Path:
    configured = os.getenv("LEX_WHISPER_MODEL")
    if configured:
        return Path(configured)
    return repo_root() / "models" / "ggml-large-v3-turbo.bin"


def default_ffmpeg_bin() -> Path:
    configured = os.getenv("LEX_FFMPEG_BIN")
    if configured:
        return Path(configured)
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    return Path(found) if found else Path("ffmpeg")


def _local_file(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if str(resolved).startswith(("http://", "https://", "ftp://")):
        raise ValueError("转写只接受本机文件，禁止远程地址")
    if not resolved.is_file():
        raise FileNotFoundError(f"转写输入不存在：{resolved}")
    return resolved


class WhisperCppProvider:
    provider_id = "whisper.cpp"
    version = "large-v3-turbo"

    def health(self):
        enabled = os.getenv("LEX_WHISPER_ENABLED") == "1"
        attested = os.getenv("LEX_WHISPER_MODELS_READY") == "1"
        binary = default_whisper_bin()
        model = default_whisper_model()
        ready = enabled and attested and binary.is_file() and model.is_file()
        return {
            "status": "available" if ready else "unconfigured",
            "provider": self.provider_id,
            "version": self.version,
            "detail": (
                "本机 whisper.cpp 资产已由部署者确认预置"
                if ready
                else "需要本机 whisper.cpp、large-v3-turbo 权重，并设置 LEX_WHISPER_ENABLED=1 与 LEX_WHISPER_MODELS_READY=1"
            ),
            "binary": str(binary),
            "binary_present": binary.is_file(),
            "model": str(model),
            "model_present": model.is_file(),
        }

    def transcribe(self, path: Path):
        if self.health()["status"] != "available":
            raise RuntimeError("本机转写资产未就绪")
        source = _local_file(path)
        wav = _extract_wav(source)
        try:
            yield from _run_whisper_cli(wav)
        finally:
            if wav != source:
                try:
                    wav.unlink(missing_ok=True)
                except OSError:
                    pass


_WHISPER_PROVIDERS: dict[str, WhisperProvider] = {"whisper.cpp": WhisperCppProvider()}


def register_whisper_provider(provider: WhisperProvider) -> None:
    if not provider.provider_id or not provider.version:
        raise ValueError("转写 Provider 必须声明稳定 id 与版本")
    _WHISPER_PROVIDERS[provider.provider_id] = provider


def whisper_capability() -> dict:
    provider_id = os.getenv("LEX_WHISPER_PROVIDER", "whisper.cpp")
    if os.getenv("LEX_WHISPER_ENABLED") != "1":
        return {
            "status": "unconfigured",
            "provider": provider_id,
            "detail": "本机转写未启用；音视频保留空转写块并进入人工校正",
        }
    provider = _WHISPER_PROVIDERS.get(provider_id)
    if provider is None:
        return {
            "status": "failed",
            "provider": provider_id,
            "detail": "配置的本机转写 Provider 未注册",
        }
    try:
        result = dict(provider.health())
    except Exception:
        result = {"status": "failed", "detail": "本机转写 Provider 健康检查失败"}
    result.setdefault("provider", provider.provider_id)
    result.setdefault("version", provider.version)
    return result


def get_whisper_provider() -> WhisperProvider | None:
    capability = whisper_capability()
    if capability["status"] != "available":
        return None
    return _WHISPER_PROVIDERS[capability["provider"]]


def _extract_wav(source: Path) -> Path:
    if source.suffix.lower() == ".wav":
        return source
    ffmpeg = default_ffmpeg_bin()
    if not (ffmpeg.is_file() or shutil.which(str(ffmpeg))):
        raise RuntimeError("未找到本机 FFmpeg，无法抽取音轨")
    handle = tempfile.NamedTemporaryFile(prefix="lex-whisper-", suffix=".wav", delete=False)
    handle.close()
    output = Path(handle.name)
    command = [
        str(ffmpeg), "-y", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(output),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg 抽音轨失败：{type(error).__name__}") from error
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg 未能抽出本机音轨")
    return output


def _run_whisper_cli(wav: Path):
    binary = default_whisper_bin()
    model = default_whisper_model()
    prefix = tempfile.mktemp(prefix="lex-whisper-out-")
    command = [
        str(binary), "-m", str(model), "-f", str(wav),
        "-l", os.getenv("LEX_WHISPER_LANG", "zh"),
        "-oj", "-of", prefix,
        "-t", "1",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"whisper.cpp 执行失败：{type(error).__name__}") from error
    json_path = Path(prefix + ".json")
    try:
        if completed.returncode != 0 or not json_path.is_file():
            raise RuntimeError("whisper.cpp 未写出本机转写结果")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    finally:
        json_path.unlink(missing_ok=True)
    yield from _segments_from_whisper_json(payload)


def _parse_timestamp(value) -> float:
    if isinstance(value, (int, float)):
        raw = float(value)
        return raw / 1000.0 if raw > 1000 else raw
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return 0.0
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0]


def _segments_from_whisper_json(payload):
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("transcription") or payload.get("segments") or []
        if not rows and isinstance(payload.get("result"), dict):
            rows = payload["result"].get("transcription") or []
    if not isinstance(rows, list):
        return
    for item in rows:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        offsets = item.get("offsets") or {}
        stamps = item.get("timestamps") or {}
        start = _parse_timestamp(offsets.get("from", item.get("start", stamps.get("from", 0))))
        end = _parse_timestamp(offsets.get("to", item.get("end", stamps.get("to", start))))
        score = item.get("confidence", item.get("score"))
        yield text, float(start), float(end), None if score is None else float(score)


def format_transcript_locator(start: float, end: float) -> str:
    return f"{start:06.2f}s-{end:06.2f}s"
