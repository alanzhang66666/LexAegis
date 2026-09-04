import { ArrowRight, Link2, Plus } from "lucide-react";
import { Empty, Tag } from "../components/ui";

type Obj = Record<string, any>;

export function FactWorkspace({ facts, currentCase, busy, label, onExtract, onOpen,
  onLocate, onDelete, onTimeline, onSummary }: {
  facts: Obj[]; currentCase: Obj; busy: boolean; label: (value: string) => string;
  onExtract: () => void; onOpen: (fact?: Obj) => void;
  onLocate: (ids: string[]) => void; onDelete: (fact: Obj) => void;
  onTimeline: () => void; onSummary: () => void;
}) {
  return <>
    <div className="toolbar"><p>{facts.length} 项事实 · 来源可追溯</p>
      {currentCase.mode === "formal" && <div>
        <button className="secondary compact" disabled={busy} onClick={onExtract}>边侧提取</button>
        <button className="primary compact" onClick={() => onOpen()}><Plus size={14}/>添加事实</button>
      </div>}</div>
    {facts.length ? facts.map((fact, index) => <article className="fact-card" key={fact.id}>
      <div className="fact-meta"><span className="fact-no">F{String(index + 1).padStart(2, "0")}</span>
        <Tag>{label(fact.field)}</Tag><span className={"fact-state " + (fact.stale ? "danger-text" : "")}>
          {fact.stale ? "来源已更新" : fact.confirmed ? "已确认" : "待人工确认"}</span></div>
      <p>{fact.value}</p><div className="fact-footer">
        <button onClick={() => onLocate(fact.source_ids)}><Link2 size={13}/>查看原文依据</button>
        <span>{fact.origin === "edge_model" ? "边侧模型提取" : fact.origin === "synthetic" ? "合成标注" : "人工录入"}</span>
        {currentCase.mode === "formal" && <>
          <button onClick={() => onOpen(fact)}>编辑</button>
          <button className="danger-text" onClick={() => onDelete(fact)}>删除</button>
        </>}
      </div>
    </article>) : <Empty title="将材料整理为可核实事实" detail="使用边侧模型提取，或选择原文片段后人工添加。"/>}
    <div className="bottom-action">
      {currentCase.mode === "formal" && <button className="secondary" disabled={busy || !facts.length}
        onClick={onTimeline}>本地生成时间线</button>}
      <button className="primary" disabled={busy || !facts.length} onClick={onSummary}>
        生成披露方案 <ArrowRight size={15}/>
      </button>
    </div>
  </>;
}
