import { ArrowRight, Link2, Plus } from "lucide-react";
import { Empty, Tag } from "../components/ui";

type Obj = Record<string, any>;

function factMarks(fact: Obj, label: (value: string) => string) {
  const marks: { key: string; text: string }[] = [];
  const aliases = Array.isArray(fact.aliases) ? fact.aliases : fact.aliases ? [fact.aliases] : [];
  aliases.forEach((item: any, index: number) => {
    const text = typeof item === "string" ? item : item?.label || item?.alias || item?.value || "";
    if (text) marks.push({ key: `alias-${index}-${text}`, text: `别名 · ${text}` });
  });
  if (fact.role) marks.push({ key: "role", text: `角色 · ${label(String(fact.role))}` });
  if (fact.conflict_group) marks.push({ key: "conflict", text: `冲突组 · ${String(fact.conflict_group)}` });
  if (fact.not_stated) marks.push({ key: "not_stated", text: "材料未陈述" });
  return marks;
}

export function FactWorkspace({ facts, currentCase, busy, label, onExtract, onOpen,
  onLocate, onDelete, onTimeline, onEvidence, onIssues, onSummary, onStartCloud }: {
  facts: Obj[]; currentCase: Obj; busy: boolean; label: (value: string) => string;
  onExtract: () => void; onOpen: (fact?: Obj) => void;
  onLocate: (ids: string[]) => void; onDelete: (fact: Obj) => void;
  onTimeline: () => void; onEvidence: () => void; onIssues: () => void; onSummary: () => void;
  onStartCloud?: () => void;
}) {
  return <>
    <div className="toolbar"><p>{facts.length} 项事实 · 来源可追溯</p>
      {currentCase.mode === "formal" && <div>
        <button className="secondary compact" disabled={busy} onClick={onExtract}>边侧提取</button>
        <button className="primary compact" onClick={() => onOpen()}><Plus size={14}/>添加事实</button>
        {onStartCloud && (
          <button className="secondary compact" disabled={busy || !facts.length} onClick={onStartCloud}>
            云端摘要任务
          </button>
        )}
      </div>}</div>
    {facts.length ? facts.map((fact, index) => {
      const marks = factMarks(fact, label);
      return <article className="fact-card" key={fact.id}>
      <div className="fact-meta"><span className="fact-no">F{String(index + 1).padStart(2, "0")}</span>
        <Tag>{label(fact.field)}</Tag><span className={"fact-state " + (fact.stale ? "danger-text" : "")}>
          {fact.stale ? "来源已更新" : fact.confirmed ? "已确认" : "待人工确认"}</span></div>
      {marks.length > 0 && <div className="fact-meta">
        {marks.map((mark) => <Tag key={mark.key}>{mark.text}</Tag>)}</div>}
      <p>{fact.value}</p><div className="fact-footer">
        <button onClick={() => onLocate(fact.source_ids)}><Link2 size={13}/>查看原文依据</button>
        <span>{fact.origin === "edge_model" ? "边侧模型提取" : fact.origin === "synthetic" ? "合成标注" : "人工录入"}</span>
        {currentCase.mode === "formal" && <>
          <button onClick={() => onOpen(fact)}>编辑</button>
          <button className="danger-text" onClick={() => onDelete(fact)}>删除</button>
        </>}
      </div>
    </article>;
    }) : <Empty title="将材料整理为可核实事实" detail="使用边侧模型提取，或选择原文片段后人工添加。"/>}
    <div className="bottom-action">
      {currentCase.mode === "formal" && <button className="secondary" disabled={busy || !facts.length}
        onClick={onTimeline}>本地生成时间线</button>}
      <button className="secondary" disabled={busy || !facts.length} onClick={onEvidence}>
        本地整理证据清单</button>
      <button className="secondary" disabled={busy || !facts.length} onClick={onIssues}>
        本地生成争点候选</button>
      <button className="primary" disabled={busy || !facts.length} onClick={onSummary}>
        生成披露方案 <ArrowRight size={15}/>
      </button>
    </div>
  </>;
}
