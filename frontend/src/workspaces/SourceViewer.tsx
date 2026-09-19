import { useState } from "react";
import { Download, FileText, Upload } from "lucide-react";
import { Empty, Tag } from "../components/ui";

type Obj = Record<string, any>;

export function SourceViewer({ data, currentCase, caseId, busy, activeSource, blocks,
  onSelect, onUpload, onCorrect, onConfirm, onRetry }: {
  data: Obj; currentCase: Obj; caseId: string; busy: boolean;
  activeSource: Obj | null; blocks: Obj[];
  onSelect: (source: Obj | null) => void;
  onUpload: (file: File) => void;
  onCorrect: (source: Obj) => void;
  onConfirm?: (source: Obj) => void;
  onRetry?: (document: Obj) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  const viewed = (activeSource && blocks.find((block) => block.id === activeSource.id)) || activeSource;
  const canConfirm = Boolean(
    currentCase.mode === "formal"
    && viewed
    && (viewed.kind === "ocr" || viewed.kind === "scan" || viewed.kind === "transcript")
    && String(viewed.text || "").trim()
    && !viewed.reviewed
  );
  const confirmBlock = (source: Obj) => {
    if (onConfirm) {
      onConfirm(source);
      return;
    }
    setConfirming(true);
    setConfirmError("");
    void fetch(`/api/v1/cases/${caseId}/documents/${source.document_id}/confirmation`, {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block_id: source.id }),
    }).then(async (response) => {
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: "确认失败" }));
        throw new Error(typeof payload.detail === "string" ? payload.detail : "确认失败");
      }
    }).catch((error: Error) => setConfirmError(error.message)).finally(() => setConfirming(false));
  };
  return <section className="source-panel">
    <div className="panel-heading"><h3><FileText size={16}/>原始材料</h3><Tag>仅边侧</Tag></div>
    <div className="document-list">{data.documents.map((document: Obj) =>
      <div className="document-row" key={document.id}>
      <button onClick={() => onSelect(document.ir?.blocks[0] || null)}>
        <FileText size={15}/><span>{document.name}<small>v{document.version} · {document.status === "ready" ? "已解析" : document.status}</small>
          {document.error && <small className="danger-text">{document.error}</small>}</span>
        {document.extension !== "demo" && <a href={`/api/v1/cases/${caseId}/documents/${document.id}/file`}
          onClick={event => event.stopPropagation()} title="下载原件"><Download size={14}/></a>}
      </button>{document.status === "failed" && onRetry && <button className="text-button" disabled={busy} onClick={()=>onRetry(document)}>重试解析</button>}
      </div>)}</div>
    {currentCase.mode === "formal" && <label className="upload"><Upload size={17}/><span>
      上传 DOCX / PDF / 文本 / 表格 / 图片 / 音视频<small>TXT 按段落切块 · XLSX/CSV 按单元格定位 · PNG/JPEG 可选本地 OCR · 音视频本机转写后复核 · 最大 20 MB</small></span>
      <input type="file" accept=".docx,.pdf,.txt,.png,.jpg,.jpeg,.xlsx,.csv,.mp3,.m4a,.wav,.mp4" disabled={busy}
        onChange={event => {
          const file = event.target.files?.[0];
          if (file) onUpload(file);
          event.target.value = "";
        }}/></label>}
    {viewed ? <>
      <div className="source-label"><span>{viewed.locator} · v{viewed.document_version}</span>
        {viewed.confidence !== null && viewed.confidence !== undefined &&
          <Tag tone="amber">{viewed.kind === "transcript" ? "转写" : "OCR"} {Math.round(viewed.confidence * 100)}%</Tag>}</div>
      {viewed.page && <div className="page-preview">
        <img alt={`原文第 ${viewed.page} 页`}
          src={`/api/v1/cases/${caseId}/documents/${viewed.document_id}/page/${viewed.page}`}/>
        {viewed.bbox && <div className="bbox" style={{
          left: viewed.bbox[0] * 100 + "%", top: viewed.bbox[1] * 100 + "%",
          width: (viewed.bbox[2] - viewed.bbox[0]) * 100 + "%",
          height: (viewed.bbox[3] - viewed.bbox[1]) * 100 + "%",
        }}/>}
      </div>}
      <div className="source-text">{viewed.text || (viewed.kind === "transcript"
        ? "未转写文本。请配置本机转写或人工校正。"
        : "未识别文本。请配置本地 OCR 或查看原图后人工转录。")}</div>
      <div className="source-actions">{currentCase.mode === "formal" && <>
        {canConfirm && <button className="text-button" disabled={busy || confirming} onClick={() => confirmBlock(viewed)}>确认本块</button>}
        <button className="text-button" disabled={busy} onClick={() => onCorrect(viewed)}>校正并生成新版本</button>
      </>}{confirmError && <small className="danger-text">{confirmError}</small>}</div>
      <div className="anchor-list">{blocks.map((block, index) =>
        <button className={viewed.id === block.id ? "selected" : ""} key={block.id} onClick={() => onSelect(block)}>
          <span>{String(index + 1).padStart(2, "0")}</span><span>{block.text.slice(0, 35) || block.locator}</span>
        </button>)}</div>
    </> : <Empty title="尚无材料" detail="上传材料后在此查看原文与来源位置。"/>}
  </section>;
}
