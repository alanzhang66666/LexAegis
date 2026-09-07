import importlib.util
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable, Protocol
from .contracts import DocumentIRV2, SourceAnchor


class OCRProvider(Protocol):
    provider_id: str
    version: str

    def health(self) -> dict: ...
    def recognize(self, image) -> Iterable[tuple[str, float, list[float]]]: ...


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

    def recognize(self, image):
        if self.health()["status"] != "available":
            raise RuntimeError("PaddleOCR 本地模型资产未就绪")
        import numpy as np
        if self._engine is None:
            from paddleocr import PaddleOCR
            # This provider is enabled only after the operator attests that model
            # assets are present; there is deliberately no remote OCR fallback.
            self._engine = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang="ch",
            )
        for result in self._engine.predict(np.array(image)):
            data = result.json
            data = data.get("res", data)
            for text, score, box in zip(
                data.get("rec_texts", []),
                data.get("rec_scores", []),
                data.get("rec_boxes", []),
            ):
                yield text, float(score), [float(v) for v in box]


_OCR_PROVIDERS: dict[str, OCRProvider] = {"paddle": PaddleOCRProvider()}


def register_ocr_provider(provider: OCRProvider) -> None:
    if not provider.provider_id or not provider.version:
        raise ValueError("OCR Provider 必须声明稳定 id 与版本")
    _OCR_PROVIDERS[provider.provider_id] = provider


def ocr_capability() -> dict:
    provider_id = os.getenv("LEX_OCR_PROVIDER", "paddle")
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
    elif path.suffix.lower() in (".png", ".jpg", ".jpeg"):
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
        raise ValueError("仅支持 DOCX、PDF、PNG、JPEG 和 TXT")
    needs_review = not blocks or any(block.kind in ("ocr", "scan") and not block.reviewed for block in blocks)
    return DocumentIRV2(document_id=document_id, version=version, blocks=blocks, material_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                        warnings=warnings, needs_review=needs_review, review_status="pending" if needs_review else "reviewed").model_dump()
