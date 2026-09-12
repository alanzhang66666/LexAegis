import importlib.machinery
import importlib.util
import os
import struct
import sys
import types
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from lexaegis import gpu_runtime
from lexaegis.gpu_runtime import gpu_stage, parse_uses_gpu
from lexaegis.parsing import RapidOCRProvider, ocr_capability, parse
from lexaegis.transcribe import register_whisper_provider, whisper_capability
from lexaegis.worker import process_one


def _write_xlsx(path: Path, rows, sheet="工资表"):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    office_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    strings = []
    for row in rows:
        strings.extend(row)
    sst = "".join(f"<si><t>{item}</t></si>" for item in strings)
    sheet_rows = []
    index = 0
    for r, row in enumerate(rows, 1):
        parts = []
        for c, _value in enumerate(row, 1):
            ref = f"{chr(64 + c)}{r}"
            parts.append(f'<c r="{ref}" t="s"><v>{index}</v></c>')
            index += 1
        sheet_rows.append(f'<row r="{r}">{"".join(parts)}</row>')
    sheet_xml = f'<worksheet xmlns="{ns}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    workbook = (
        f'<workbook xmlns="{ns}" xmlns:r="{office_rel}">'
        f'<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        f'<Relationships xmlns="{rel_ns}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    root_rels = (
        f'<Relationships xmlns="{rel_ns}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    sst_xml = f'<sst xmlns="{ns}" count="{len(strings)}" uniqueCount="{len(strings)}">{sst}</sst>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", sst_xml)


def _silent_wav(path: Path, samples=1600):
    data = b"\x00\x00" * samples
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16, b"data", len(data),
    )
    path.write_bytes(header + data)


class FakeRapidOCREngine:
    def __init__(self, **kwargs):
        FakeRapidOCREngine.kwargs = kwargs

    def __call__(self, array):
        return [[[ [10, 5], [90, 5], [90, 25], [10, 25] ], "Rapid 模拟文本", 0.88]]


class FakeWhisper:
    provider_id = "fake-whisper"
    version = "1"

    def health(self):
        return {"status": "available", "detail": "test-only"}

    def transcribe(self, path):
        yield "模拟转写工资12000元", 0.0, 1.5, 0.91


def test_xlsx_cells_have_sheet_column_row_locators(tmp_path):
    path = tmp_path / "工资.xlsx"
    _write_xlsx(path, [["姓名", "金额"], ["林甲", "12000元"]])
    result = parse(path, "doc_xlsx")
    texts = [block["text"] for block in result["blocks"]]
    assert "林甲" in texts
    assert "12000元" in texts
    assert all(block["kind"] == "table" for block in result["blocks"])
    target = next(block for block in result["blocks"] if block["text"] == "12000元")
    assert "工资表" in target["locator"]
    assert "金额" in target["locator"]
    assert "行 2" in target["locator"]
    assert result["needs_review"] is False


def test_csv_uses_header_column_and_row_locator(tmp_path):
    path = tmp_path / "工资.csv"
    path.write_text("姓名,金额\n林甲,12000元\n", encoding="utf-8")
    result = parse(path, "doc_csv")
    target = next(block for block in result["blocks"] if block["text"] == "12000元")
    assert target["kind"] == "table"
    assert "金额" in target["locator"]
    assert "行 2" in target["locator"]
    assert result["needs_review"] is False


def test_default_ocr_provider_is_rapidocr(monkeypatch):
    monkeypatch.delenv("LEX_OCR_PROVIDER", raising=False)
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    assert ocr_capability()["provider"] == "rapidocr"


def test_rapidocr_fake_module_yields_ocr_block(tmp_path, monkeypatch):
    module = types.ModuleType("rapidocr")
    module.__spec__ = importlib.machinery.ModuleSpec("rapidocr", loader=None)
    module.RapidOCR = FakeRapidOCREngine
    monkeypatch.setitem(sys.modules, "rapidocr", module)
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "1")
    image = Image.new("RGB", (100, 50), "white")
    rows = list(RapidOCRProvider().recognize(image))
    assert rows[0][0] == "Rapid 模拟文本"
    assert rows[0][1] == 0.88
    path = tmp_path / "scan.png"
    image.save(path)
    result = parse(path, "doc_rapid", ocr_provider=RapidOCRProvider())
    assert result["blocks"][0]["kind"] == "ocr"
    assert result["needs_review"] is True


def test_rapidocr_failure_falls_back_to_scan(tmp_path):
    class Broken(RapidOCRProvider):
        def health(self):
            return {"status": "available", "provider": "rapidocr", "version": "onnx"}

        def recognize(self, image):
            raise RuntimeError("offline model corrupt")

    path = tmp_path / "scan.jpg"
    Image.new("RGB", (80, 40), "white").save(path)
    result = parse(path, "doc_broken_rapid", ocr_provider=Broken())
    assert result["blocks"][0]["kind"] == "scan"
    assert result["needs_review"]
    assert any("OCR 执行失败" in warning for warning in result["warnings"])


def test_whisper_fake_writes_transcript_locator(tmp_path, monkeypatch):
    register_whisper_provider(FakeWhisper())
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "1")
    monkeypatch.setenv("LEX_WHISPER_PROVIDER", "fake-whisper")
    path = tmp_path / "clip.wav"
    _silent_wav(path)
    result = parse(path, "doc_audio")
    block = result["blocks"][0]
    assert block["kind"] == "transcript"
    assert "12000" in block["text"]
    assert "s-" in block["locator"]
    assert block["recognizer"] == "fake-whisper@1"
    assert result["needs_review"] is True


def test_whisper_failure_leaves_pending_transcript(tmp_path, monkeypatch):
    class BrokenWhisper(FakeWhisper):
        def transcribe(self, path):
            raise RuntimeError("no weights")

    register_whisper_provider(BrokenWhisper())
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "1")
    monkeypatch.setenv("LEX_WHISPER_PROVIDER", "fake-whisper")
    path = tmp_path / "clip.wav"
    _silent_wav(path)
    result = parse(path, "doc_audio_fail")
    assert result["blocks"][0]["kind"] == "transcript"
    assert result["blocks"][0]["text"] == ""
    assert result["needs_review"] is True
    assert any("转写执行失败" in warning for warning in result["warnings"])


def test_unconfigured_audio_is_pending_transcript(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "0")
    path = tmp_path / "clip.wav"
    _silent_wav(path)
    result = parse(path, "doc_audio_off")
    assert result["blocks"][0]["kind"] == "transcript"
    assert result["blocks"][0]["text"] == ""
    assert result["needs_review"] is True


def test_empty_transcript_cannot_confirm(env, tmp_path):
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "空白转写不可确认"}).json()
    wav = tmp_path / "clip.wav"
    _silent_wav(wav)
    uploaded = client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")},
    )
    assert uploaded.status_code == 200, uploaded.text
    process_one(env["app"].state.store, env["root"], env["gate"])
    doc = client.get(f"/api/v1/cases/{case['id']}").json()["documents"][0]
    block = doc["ir"]["blocks"][0]
    assert block["kind"] == "transcript"
    result = client.put(
        f"/api/v1/cases/{case['id']}/documents/{doc['id']}/confirmation",
        json={"block_id": block["id"]},
    )
    assert result.status_code == 409
    assert "转录" in result.text


def test_transcript_confirm_after_text(env, tmp_path):
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "转写确认"}).json()
    wav = tmp_path / "clip.wav"
    _silent_wav(wav)
    client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")},
    )
    process_one(env["app"].state.store, env["root"], env["gate"])
    doc = client.get(f"/api/v1/cases/{case['id']}").json()["documents"][0]
    block = doc["ir"]["blocks"][0]
    corrected = client.put(
        f"/api/v1/cases/{case['id']}/documents/{doc['id']}/correction",
        json={"block_id": block["id"], "text": "合成转写：工资12000元"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["ir"]["needs_review"] is False


def test_gpu_stage_ocr_unloads_edge(monkeypatch):
    calls = []
    monkeypatch.setattr(gpu_runtime, "edge_port_open", lambda timeout=0.4: True)
    monkeypatch.setattr(gpu_runtime, "unload_edge", lambda: calls.append("unload") or {"stopped": True})
    monkeypatch.setattr(gpu_runtime, "ensure_edge_loaded", lambda wait=30: calls.append("load") or {})
    with gpu_stage("ocr"):
        calls.append("ocr")
    assert calls == ["unload", "ocr"]


def test_parse_uses_gpu_only_when_aux_enabled(monkeypatch, tmp_path):
    image = tmp_path / "a.png"
    audio = tmp_path / "a.wav"
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "0")
    assert parse_uses_gpu(image) is False
    assert parse_uses_gpu(audio) is False
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "rapidocr")
    assert parse_uses_gpu(image) is True
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "1")
    assert parse_uses_gpu(audio) is True


def test_live_rapidocr_scan_smoke(monkeypatch):
    if importlib.util.find_spec("rapidocr") is None:
        pytest.skip("rapidocr 未安装；不在此环境 pip install")
    if os.environ.get("LEX_OCR_MODELS_READY") != "1":
        pytest.skip("环境未声明 LEX_OCR_MODELS_READY=1；跳过真实 RapidOCR 冒烟以免触发下载")
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "rapidocr")
    result = parse(Path(__file__).resolve().parent.parent / "examples" / "synthetic_scan.pdf", "live_rapid")
    ocr_blocks = [block for block in result["blocks"] if block["kind"] == "ocr"]
    assert ocr_blocks
    assert result["needs_review"] is True


def test_live_whisper_audio_smoke(monkeypatch, tmp_path):
    from lexaegis.transcribe import default_whisper_bin, default_whisper_model

    if not default_whisper_bin().is_file() or not default_whisper_model().is_file():
        pytest.skip("whisper.cpp 或 large-v3-turbo 未预置；不在此环境安装")
    if os.environ.get("LEX_WHISPER_MODELS_READY") != "1":
        pytest.skip("环境未声明 LEX_WHISPER_MODELS_READY=1；跳过真实转写冒烟")
    monkeypatch.setenv("LEX_WHISPER_ENABLED", "1")
    path = tmp_path / "clip.wav"
    _silent_wav(path)
    result = parse(path, "live_whisper")
    assert result["blocks"][0]["kind"] == "transcript"
    assert result["needs_review"] is True
    assert whisper_capability()["status"] in {"available", "unconfigured", "failed"}
