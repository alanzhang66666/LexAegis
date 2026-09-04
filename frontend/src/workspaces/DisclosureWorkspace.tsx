import { ArrowRight, Link2, LockKeyhole } from "lucide-react";
import { Tag } from "../components/ui";

type Obj = Record<string, any>;
const TERMINAL = ["complete", "unknown", "stopped", "queued", "sending", "failed"];

export function DisclosureWorkspace({ task, currentCase, busy, label, onEdit,
  onLocate, onEditOutput, onEvaluate }: {
  task: Obj; currentCase: Obj; busy: boolean; label: (value: string) => string;
  onEdit: (decision: Obj, patch: Obj) => void;
  onLocate: (ids: string[]) => void; onEditOutput: (decision: Obj) => void;
  onEvaluate: () => void;
}) {
  const disabled = busy || task.stale || TERMINAL.includes(task.status);
  return <>
    <div className="context-note"><LockKeyhole size={14}/>
      仅下方披露内容会进入请求；原文和身份映射保留在边侧。</div>
    {task.decisions.map((decision: Obj, index: number) => <article className="decision-card" key={decision.fact_id}>
      <div className="fact-meta"><span className="fact-no">F{String(index + 1).padStart(2, "0")}</span>
        <Tag>{label(decision.field)}</Tag>
        <select aria-label={`字段 ${index + 1} 必要性`} disabled={disabled} value={decision.necessity}
          onChange={event => onEdit(decision, { necessity: event.target.value })}>
          {["required", "conditional", "unnecessary", "uncertain"].map(value =>
            <option key={value} value={value}>{label(value)}</option>)}
        </select>
      </div>
      <div className="transform-options">{["keep", "pseudonymize", "generalize", "delete"].map(value =>
        <button disabled={disabled} className={decision.transform === value ? "active" : ""} key={value}
          onClick={() => onEdit(decision, { transform: value })}>{label(value)}</button>)}</div>
      <div className={"disclosed-text " + (!decision.output ? "deleted" : "")}>
        {decision.output || "此项已删除，不进入外发内容。"}</div>
      <small className="reason">{decision.reason}</small>
      <div className="fact-footer">
        <button onClick={() => onLocate(task.fact_snapshot.find((fact: Obj) => fact.id === decision.fact_id)?.source_ids || [])}>
          <Link2 size={13}/>查看依据</button>
        {currentCase.mode === "formal" && <button onClick={() => onEditOutput(decision)}>编辑披露文本</button>}
      </div>
    </article>)}
    <div className="bottom-action"><button className="primary" disabled={busy || task.stale} onClick={onEvaluate}>
      检验风险并冻结请求 <ArrowRight size={15}/></button></div>
  </>;
}
