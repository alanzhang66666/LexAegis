import { Download, FileText, Upload } from "lucide-react";
import { Empty, Tag } from "../components/ui";

type Obj = Record<string, any>;

export function SourceViewer({ data, currentCase, caseId, busy, activeSource, blocks,
  onSelect, onUpload, onCorrect }: {
  data: Obj; currentCase: Obj; caseId: string; busy: boolean;
  activeSource: Obj | null; blocks: Obj[];
  onSelect: (source: Obj | null) => void;
  onUpload: (file: File) => void;
  onCorrect: (source: Obj) => void;
}) {
  return <section className="source-panel">
    <div className="panel-heading"><h3><FileText size={16}/>原始材料</h3><Tag>仅边侧</Tag></div>
    <div className="document-list">{data.documents.map((document: Obj) =>
      <button key={document.id} onClick={() => onSelect(document.ir?.blocks[0] || null)}>
        <FileText size={15}/><span>{document.name}<small>v{document.version} · {document.status === "ready" ? "已解析" : document.status}</small>
          {document.error && <small className="danger-text">{document.error}</small>}</span>
        {document.extension !== "demo" && <a href={`/api/v1/cases/${caseId}/documents/${document.id}/file`}
          onClick={event => event.stopPropagation()} title="下载原件"><Download size={14}/></a>}
      </button>)}</div>
    {currentCase.mode === "formal" && <label className="upload"><Upload size={17}/><span>
      上传 DOCX / PDF / 图片<small>PNG/JPEG 可选本地 OCR · 最大 20 MB</small></span>
      <input type="file" accept=".docx,.pdf,.png,.jpg,.jpeg" disabled={busy}
        onChange={event => {
          const file = event.target.files?.[0];
          if (file) onUpload(file);
          event.target.value = "";
        }}/></label>}
    {activeSource ? <>
      <div className="source-label"><span>{activeSource.locator} · v{activeSource.document_version}</span>
        {activeSource.confidence !== null && activeSource.confidence !== undefined &&
          <Tag tone="amber">OCR {Math.round(activeSource.confidence * 100)}%</Tag>}</div>
      {activeSource.page && <div className="page-preview">
        <img alt={`原文第 ${activeSource.page} 页`}
          src={`/api/v1/cases/${caseId}/documents/${activeSource.document_id}/page/${activeSource.page}`}/>
        {activeSource.bbox && <div className="bbox" style={{
          left: activeSource.bbox[0] * 100 + "%", top: activeSource.bbox[1] * 100 + "%",
          width: (activeSource.bbox[2] - activeSource.bbox[0]) * 100 + "%",
          height: (activeSource.bbox[3] - activeSource.bbox[1]) * 100 + "%",
        }}/>}
      </div>}
      <div className="source-text">{activeSource.text || "未识别文本。请配置本地 OCR 或查看原图后人工转录。"}</div>
      <div className="source-actions">{currentCase.mode === "formal" &&
        <button className="text-button" onClick={() => onCorrect(activeSource)}>校正并生成新版本</button>}</div>
      <div className="anchor-list">{blocks.map((block, index) =>
        <button className={activeSource.id === block.id ? "selected" : ""} key={block.id} onClick={() => onSelect(block)}>
          <span>{String(index + 1).padStart(2, "0")}</span><span>{block.text.slice(0, 35) || block.locator}</span>
        </button>)}</div>
    </> : <Empty title="尚无材料" detail="上传材料后在此查看原文与来源位置。"/>}
  </section>;
}
