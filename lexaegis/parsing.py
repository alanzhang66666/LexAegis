import csv
import hashlib
import importlib.util
import os
import re
import sys
import types
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Protocol
from .contracts import REVIEW_BLOCK_KINDS, DocumentIRV2, SourceAnchor
from .transcribe import format_transcript_locator, get_whisper_provider

UPLOAD_EXTENSIONS = (
    ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".txt",
    ".xlsx", ".csv", ".mp3", ".m4a", ".wav", ".mp4",
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".mp4")
TABLE_EXTENSIONS = (".xlsx", ".csv")
_XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class OCRProvider(Protocol):
    provider_id: str
    version: str

    def health(self) -> dict: ...
    def recognize(self, image) -> Iterable[tuple[str, float, list[float]]]: ...


def _import_paddleocr():
    """Import PaddleOCR without letting PaddleX's optional LangChain shim pull a broken local torch."""
    if "langchain_text_splitters" not in sys.modules:
        try:
            import langchain  # noqa: F401
        except ImportError:
            pass
        else:
            stub = types.ModuleType("langchain_text_splitters")

            class RecursiveCharacterTextSplitter:
                def __init__(self, *args, **kwargs):
                    pass

            stub.RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter
            sys.modules["langchain_text_splitters"] = stub
    from paddleocr import PaddleOCR
    return PaddleOCR


class PaddleOCRProvider:
    provider_id = "paddle"
    version = "3"

    def __init__(self):
        self._engine = None

    def health(self):
        installed = importlib.util.find_spec("paddleocr") is not None
        assets_ready = os.getenv("LEX_OCR_MODELS_READY") == "1"
        return {
            "status": "available" if installed and assets_ready else "unconfigured",
            "provider": self.provider_id,
            "version": self.version,
            "detail": (
                "PaddleOCR 本地模型资产已由部署者确认预置"
                if installed and assets_ready
                else "需要安装 PaddleOCR，并设置 LEX_OCR_MODELS_READY=1 确认模型资产已离线预置"
            ),
        }

    def _create_engine(self):
        # Enabled only after the operator attests that model assets are present;
        # there is deliberately no remote OCR fallback. CPU only so PaddleOCR 3.x
        # cannot auto-select CUDA and compete with llama-server GPU.
        # enable_mkldnn=False avoids the Paddle 3.3.x CPU oneDNN/PIR crash.
        PaddleOCR = _import_paddleocr()
        kwargs = dict(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="ch",
            enable_mkldnn=False,
        )
        try:
            return PaddleOCR(**kwargs, device="cpu")
        except TypeError as error:
            message = str(error)
            if "enable_mkldnn" in message:
                kwargs.pop("enable_mkldnn", None)
                try:
                    return PaddleOCR(**kwargs, device="cpu")
                except TypeError as inner:
                    error = inner
                    message = str(inner)
            if "device" not in message:
                raise
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            return PaddleOCR(**kwargs)

    def recognize(self, image):
        if self.health()["status"] != "available":
            raise RuntimeError("PaddleOCR 本地模型资产未就绪")
        import numpy as np
        if self._engine is None:
            self._engine = self._create_engine()
        for result in self._engine.predict(np.array(image)):
            data = result.json
            data = data.get("res", data)
            for text, score, box in zip(
                data.get("rec_texts", []),
                data.get("rec_scores", []),
                data.get("rec_boxes", []),
            ):
                yield text, float(score), [float(v) for v in box]


class RapidOCRProvider:
    provider_id = "rapidocr"
    version = "onnx"

    def __init__(self):
        self._engine = None

    def health(self):
        installed = importlib.util.find_spec("rapidocr") is not None
        assets_ready = os.getenv("LEX_OCR_MODELS_READY") == "1"
        return {
            "status": "available" if installed and assets_ready else "unconfigured",
            "provider": self.provider_id,
            "version": self.version,
            "detail": (
                "RapidOCR 本地模型资产已由部署者确认预置"
                if installed and assets_ready
                else "需要安装 RapidOCR 与 ONNX Runtime CUDA，并设置 LEX_OCR_MODELS_READY=1 确认模型资产已离线预置"
            ),
        }

    def _model_params(self):
        root = os.getenv("LEX_OCR_MODELS_DIR")
        params = {"EngineConfig.onnxruntime.use_cuda": True}
        if not root:
            return params
        base = Path(root)
        mapping = {
            "Det.model_path": ("det.onnx", "ch_PP-OCRv4_det_infer.onnx"),
            "Rec.model_path": ("rec.onnx", "ch_PP-OCRv4_rec_infer.onnx"),
            "Cls.model_path": ("cls.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx"),
        }
        for key, names in mapping.items():
            for name in names:
                candidate = base / name
                if candidate.is_file():
                    params[key] = str(candidate)
                    break
        return params

    def _create_engine(self):
        if importlib.util.find_spec("rapidocr") is None:
            raise RuntimeError("RapidOCR 未安装")
        from rapidocr import RapidOCR
        params = self._model_params()
        try:
            return RapidOCR(params=params)
        except TypeError:
            try:
                return RapidOCR(use_cuda=True)
            except TypeError:
                return RapidOCR()

    def recognize(self, image):
        if self.health()["status"] != "available":
            raise RuntimeError("RapidOCR 本地模型资产未就绪")
        if self._engine is None:
            self._engine = self._create_engine()
        try:
            import numpy as np
            array = np.array(image)
        except ImportError:
            array = image
        raw = self._engine(array)
        yield from _iter_rapidocr_output(raw)


def _box_to_xyxy(box):
    if box is None:
        return [0.0, 0.0, 1.0, 1.0]
    if len(box) == 4 and all(isinstance(item, (int, float)) for item in box):
        return [float(item) for item in box]
    xs, ys = [], []
    for point in box:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
        elif isinstance(point, (int, float)):
            if len(xs) == len(ys):
                xs.append(float(point))
            else:
                ys.append(float(point))
    if not xs or not ys:
        return [0.0, 0.0, 1.0, 1.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iter_rapidocr_output(raw):
    result = raw[0] if isinstance(raw, tuple) and raw else raw
    if result is None:
        return
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if texts is not None:
        for text, score, box in zip(texts or [], scores or [], boxes or []):
            if text:
                yield str(text), float(score or 0), _box_to_xyxy(box)
        return
    if isinstance(result, dict):
        for text, score, box in zip(
            result.get("rec_texts") or result.get("txts") or [],
            result.get("rec_scores") or result.get("scores") or [],
            result.get("rec_boxes") or result.get("boxes") or [],
        ):
            if text:
                yield str(text), float(score or 0), _box_to_xyxy(box)
        return
    if not isinstance(result, list):
        return
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            if len(item) >= 3 and isinstance(item[1], str):
                box, text, score = item[0], item[1], item[2]
            elif isinstance(item[0], str):
                text, score, box = item[0], item[1], item[2] if len(item) > 2 else [0, 0, 1, 1]
            else:
                continue
            if text:
                yield str(text), float(score or 0), _box_to_xyxy(box)


_OCR_PROVIDERS: dict[str, OCRProvider] = {
    "rapidocr": RapidOCRProvider(),
    "paddle": PaddleOCRProvider(),
}


def register_ocr_provider(provider: OCRProvider) -> None:
    if not provider.provider_id or not provider.version:
        raise ValueError("OCR Provider 必须声明稳定 id 与版本")
    _OCR_PROVIDERS[provider.provider_id] = provider


def ocr_capability() -> dict:
    provider_id = os.getenv("LEX_OCR_PROVIDER", "rapidocr")
    if os.getenv("LEX_OCR_ENABLED") != "1":
        return {
            "status": "unconfigured",
            "provider": provider_id,
            "detail": "本地 OCR 未启用；扫描页保留原图并进入人工转录",
        }
    provider = _OCR_PROVIDERS.get(provider_id)
    if provider is None:
        return {
            "status": "failed",
            "provider": provider_id,
            "detail": "配置的本地 OCR Provider 未注册",
        }
    try:
        result = dict(provider.health())
    except Exception:
        result = {"status": "failed", "detail": "本地 OCR Provider 健康检查失败"}
    result.setdefault("provider", provider.provider_id)
    result.setdefault("version", provider.version)
    return result


def get_ocr_provider() -> OCRProvider | None:
    capability = ocr_capability()
    if capability["status"] != "available":
        return None
    return _OCR_PROVIDERS[capability["provider"]]


_DEFAULT_PROVIDER = object()


def parse(path: Path, document_id: str, version=1, ocr_provider=_DEFAULT_PROVIDER):
    blocks, warnings = [], []
    provider = get_ocr_provider() if ocr_provider is _DEFAULT_PROVIDER else ocr_provider

    def add(kind, content, **kwargs):
        blocks.append(SourceAnchor(id=f"{document_id}:v{version}:b{len(blocks)}", document_id=document_id, document_version=version, kind=kind, text=content, **kwargs))

    if path.suffix.lower() == ".docx":
        import zipfile
        from docx import Document
        from docx.table import Table
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                raise ValueError("DOCX 解压内容超过 100MB 限制")
        doc = Document(path)
        for index, element in enumerate(doc.iter_inner_content()):
            if isinstance(element, Table):
                for r, row in enumerate(element.rows):
                    for c, cell in enumerate(row.cells):
                        if cell.text.strip():
                            add("table", cell.text, locator=f"内容 {index+1} · 表格行 {r+1} 列 {c+1}")
            elif element.text.strip():
                add("paragraph", element.text, locator=f"段落 {index+1}")
        if not blocks:
            warnings.append("未提取到文本，可能包含仅图片内容；请转换为扫描 PDF。")
    elif path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        try:
            if len(pdf) > 200:
                raise ValueError("单份 PDF 上限为 200 页，请拆分材料")
            for p in range(len(pdf)):
                page = pdf[p]
                width, height = page.get_size()
                textpage = page.get_textpage()
                extracted = textpage.get_text_range().strip()
                if len(extracted) >= 10:
                    # Paragraph-level text with character-union position, normalized to top-left.
                    boxes = [textpage.get_charbox(i) for i in range(textpage.count_chars())]
                    bbox = [0, 0, 1, 1]
                    if boxes:
                        bbox = [min(b[0] for b in boxes)/width, 1-max(b[3] for b in boxes)/height, max(b[2] for b in boxes)/width, 1-min(b[1] for b in boxes)/height]
                    add("pdf_text", extracted, page=p+1, bbox=bbox, locator=f"第 {p+1} 页 · 文本区域")
                elif provider is not None:
                    image = page.render(scale=min(2, 2400/max(width, height))).to_pil().convert("RGB")
                    found = False
                    try:
                        for content, score, box in provider.recognize(image):
                            found = True
                            add("ocr", content, page=p+1, bbox=[box[0]/image.width, box[1]/image.height, box[2]/image.width, box[3]/image.height], confidence=score, recognizer=f"{provider.provider_id}@{provider.version}", locator=f"第 {p+1} 页 · OCR")
                    except Exception:
                        warnings.append(f"第 {p+1} 页 OCR 执行失败，请检查离线模型资源")
                    if not found:
                        add("scan", "", page=p+1, bbox=[0, 0, 1, 1], locator=f"第 {p+1} 页 · 待识别")
                else:
                    add("scan", "", page=p+1, bbox=[0, 0, 1, 1], locator=f"第 {p+1} 页 · 扫描页")
                    warnings.append(f"第 {p+1} 页需要本地 OCR，当前未配置；可查看原图并人工转录。")
                textpage.close()
                page.close()
        finally:
            pdf.close()
    elif path.suffix.lower() == ".txt":
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("文本文件须为 UTF-8") from error
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        chunks = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not chunks:
            chunks = [line.strip() for line in text.splitlines() if line.strip()]
        if not chunks and text.strip():
            chunks = [text.strip()]
        if not chunks:
            warnings.append("未提取到文本，文本文件为空。")
        for index, chunk in enumerate(chunks, 1):
            add("paragraph", chunk, locator=f"段落 {index}")
    elif path.suffix.lower() == ".xlsx":
        _parse_xlsx(path, add, warnings)
    elif path.suffix.lower() == ".csv":
        _parse_csv(path, add, warnings)
    elif path.suffix.lower() in AUDIO_EXTENSIONS:
        _parse_media(path, add, warnings)
    elif path.suffix.lower() in IMAGE_EXTENSIONS:
        from PIL import Image
        with Image.open(path) as source:
            image = source.convert("RGB")
            if image.width * image.height > 50_000_000:
                raise ValueError("图片像素超过 5000 万限制")
            if provider is not None:
                found = False
                try:
                    for content, score, box in provider.recognize(image):
                        found = True
                        add("ocr", content, page=1, bbox=[box[0]/image.width, box[1]/image.height, box[2]/image.width, box[3]/image.height], confidence=score, recognizer=f"{provider.provider_id}@{provider.version}", locator="第 1 页 · OCR")
                except Exception:
                    warnings.append("图片 OCR 执行失败，请检查离线模型资源")
                if not found:
                    add("scan", "", page=1, bbox=[0, 0, 1, 1], locator="第 1 页 · 待识别")
            else:
                add("scan", "", page=1, bbox=[0, 0, 1, 1], locator="第 1 页 · 扫描页")
                warnings.append("图片需要本地 OCR，当前未配置；请人工转录。")
    else:
        raise ValueError("仅支持 DOCX、PDF、PNG、JPEG、TXT、XLSX、CSV 与常见音视频")
    needs_review = not blocks or any(block.kind in REVIEW_BLOCK_KINDS and not block.reviewed for block in blocks)
    return DocumentIRV2(document_id=document_id, version=version, blocks=blocks, material_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                        warnings=warnings, needs_review=needs_review, review_status="pending" if needs_review else "reviewed").model_dump()


def _col_letter(index: int) -> str:
    value, letters = index, []
    while value:
        value, rem = divmod(value - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters)) or "A"


def _cell_ref(name: str):
    match = re.match(r"([A-Z]+)(\d+)", (name or "").upper())
    if not match:
        return None, None
    letters, row = match.group(1), int(match.group(2))
    column = 0
    for char in letters:
        column = column * 26 + (ord(char) - 64)
    return column, row


def _xlsx_shared_strings(archive: zipfile.ZipFile):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("m:si", _XLSX_NS):
        texts = [node.text or "" for node in item.findall(".//m:t", _XLSX_NS)]
        values.append("".join(texts))
    return values


def _xlsx_sheets(archive: zipfile.ZipFile):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in archive.namelist():
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root.findall("pr:Relationship", _XLSX_NS):
            target = rel.attrib.get("Target", "")
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            rels[rel.attrib.get("Id", "")] = target
    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", _XLSX_NS):
        name = sheet.attrib.get("name") or f"Sheet{len(sheets) + 1}"
        target = rels.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", ""))
        if target and target in archive.namelist():
            sheets.append((name, target))
    if not sheets:
        for name in archive.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheets.append((Path(name).stem, name))
    return sheets


def _parse_xlsx(path: Path, add, warnings):
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError("XLSX 解压内容超过 100MB 限制")
        strings = _xlsx_shared_strings(archive)
        sheets = _xlsx_sheets(archive)
        if not sheets:
            warnings.append("未提取到工作表。")
            return
        for sheet_name, target in sheets:
            root = ET.fromstring(archive.read(target))
            cells = []
            for cell in root.findall(".//m:c", _XLSX_NS):
                ref = cell.attrib.get("r") or ""
                column, row = _cell_ref(ref)
                if row is None:
                    continue
                kind = cell.attrib.get("t")
                node = cell.find("m:v", _XLSX_NS)
                raw = node.text if node is not None else ""
                if kind == "s" and raw.isdigit() and int(raw) < len(strings):
                    text = strings[int(raw)]
                else:
                    inline = cell.find("m:is", _XLSX_NS)
                    if inline is not None:
                        text = "".join(item.text or "" for item in inline.findall(".//m:t", _XLSX_NS))
                    else:
                        text = raw or ""
                if text.strip():
                    cells.append((row, column or 1, ref or _col_letter(column or 1), text.strip()))
            headers = {}
            for row, column, ref, text in cells:
                if row == 1:
                    headers[column] = text
            for row, column, ref, text in cells:
                col_name = headers.get(column) or _col_letter(column)
                add(
                    "table",
                    text,
                    locator=f"工作表 {sheet_name} · 列 {col_name} · 行 {row}",
                )
            if not cells:
                warnings.append(f"工作表 {sheet_name} 未提取到单元格文本。")


def _parse_csv(path: Path, add, warnings):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV 须为 UTF-8") from error
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        warnings.append("未提取到文本，CSV 为空。")
        return
    headers = [item.strip() or _col_letter(index + 1) for index, item in enumerate(rows[0])]
    started = 2 if any(headers) else 1
    data_rows = rows[1:] if started == 2 else rows
    found = False
    for offset, row in enumerate(data_rows):
        row_number = offset + started
        for index, value in enumerate(row):
            content = (value or "").strip()
            if not content:
                continue
            found = True
            column = headers[index] if index < len(headers) else _col_letter(index + 1)
            add("table", content, locator=f"CSV · 列 {column} · 行 {row_number}")
    if not found:
        warnings.append("未提取到文本，CSV 无有效单元格。")


def _parse_media(path: Path, add, warnings):
    provider = get_whisper_provider()
    if provider is None:
        add("transcript", "", locator="待转写")
        warnings.append("音视频需要本机转写，当前未配置；请人工校正。")
        return
    found = False
    try:
        for text, start, end, score in provider.transcribe(path):
            found = True
            add(
                "transcript",
                text,
                locator=format_transcript_locator(start, end),
                confidence=score,
                recognizer=f"{provider.provider_id}@{provider.version}",
            )
    except Exception:
        warnings.append("音视频转写执行失败，请检查离线模型资源与 FFmpeg")
    if not found:
        add("transcript", "", locator="待转写")
        if not any("转写执行失败" in item for item in warnings):
            warnings.append("转写结果为空，请人工校正。")
