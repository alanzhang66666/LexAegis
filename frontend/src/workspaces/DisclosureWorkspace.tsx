import { ArrowRight, Link2, LockKeyhole } from "lucide-react";
import { IssueList, Tag } from "../components/ui";

type Obj = Record<string, any>;
const TERMINAL = ["complete", "unknown", "stopped", "queued", "sending", "failed", "review_blocked", "rejected"];
const JUDGMENT: Record<string, string> = {
  necessary: "必要",
  not_necessary: "不必要",
  review: "复核",
  unknown: "未知",
  processable: "可处理",
  not_processable: "不可处理",
  unverified: "未验证",
  elevated: "较高",
  ordinary: "一般",
  restricted: "限制外发",
};
const UNKNOWN_CONDITION: Record<string, string> = {
  day_nature_known: "工作日性质未填写",
  hours_known: "加班小时未填写",
  wage_base_known: "工资基数未填写",
  claim_stance_known: "主张或否认未填写",
  evidence_holder_known: "证据持有人未填写",
  sub_purpose_overtime: "子目的不是核对加班",
  sub_purpose_relation: "子目的不是劳动关系经过与争议状态",
  sub_purpose_wage: "子目的不是欠薪、解除与经济补偿经过",
  sub_purpose_injury: "子目的不是工伤待遇争议经过",
};

function modelSuggestion(decision: Obj, facts: Obj[] | undefined) {
  const fact = Array.isArray(facts) ? facts.find((item) => item.id === decision.fact_id) : undefined;
  const raw = decision.model_suggestion || fact?.model_suggestion;
  if (!raw || typeof raw !== "object") return null;
  const transform = raw.transform || "";
  const reason = raw.reason || "";
  return transform || reason ? { transform, reason } : null;
}

function judgmentLine(basis: Obj | undefined, key: string, title: string) {
  if (!basis || !basis[key]) return null;
  const value = String(basis[key]);
  return <><dt>{title}</dt><dd>{JUDGMENT[value] || value}</dd></>;
}

function readableReason(reason: string) {
  return reason
    .replace(/条件未知：([A-Za-z0-9_]+)/g, (_, id) => `条件未知：${UNKNOWN_CONDITION[id] || id}`)
    .replace(/最低精度：calendar_day/g, "最低精度：日历日")
    .replace(/最低精度：exact_hours/g, "最低精度：确切小时数")
    .replace(/最低精度：wage_amount/g, "最低精度：工资金额")
    .replace(/最低精度：weekday_rest_holiday/g, "最低精度：工作日、休息日或节假日")
    .replace(/最低精度：claim_or_deny/g, "最低精度：主张或否认")
    .replace(/最低精度：who_holds/g, "最低精度：谁持有证据")
    .replace(/spc_labor_interp_1/g, "劳动争议解释（一）草稿")
    .replace(/spc_labor_interp_2/g, "劳动争议解释（二）草稿")
    .replace(/lawyer_law_2026_09_01/g, "律师法2026-09-01");
}

export function DisclosureWorkspace({ task, currentCase, busy, label, onEdit,
  onLocate, onEditOutput, onEvaluate }: {
  task: Obj; currentCase: Obj; busy: boolean; label: (value: string) => string;
  onEdit: (decision: Obj, patch: Obj) => void;
  onLocate: (ids: string[]) => void; onEditOutput: (decision: Obj) => void;
  onEvaluate: () => void;
}) {
  const disabled = busy || task.stale || TERMINAL.includes(task.status) || ["blocked","rejected"].includes(task.review_status);
  const followupIds: string[] = task.followup_fact_ids || [];
  const candidatesOf = (decision: Obj) => Array.isArray(decision.candidates) ? decision.candidates : [];
  return <>
    <div className="context-note"><LockKeyhole size={14}/>
      仅下方披露内容会进入请求；原文和身份映射保留在边侧。</div>
    {task.sub_purpose ? <div className="context-note">子目的 {label(String(task.sub_purpose))} · 规则为待审草稿，非正式法源，正式外发仍阻断。</div> : null}
    {task.decisions.map((decision: Obj, index: number) => {
      const suggestion = modelSuggestion(decision, task.fact_snapshot);
      const fromFollowup = followupIds.includes(decision.fact_id);
      const candidates = candidatesOf(decision);
      const allowed = candidates.filter((item: Obj) => item.allowed).filter((item: Obj, index: number, rows: Obj[]) =>
        rows.findIndex(other => other.transform === item.transform && other.output === item.output) === index);
      const rejected = candidates.filter((item: Obj) => !item.allowed);
      const basis = decision.processing_basis;
      const secrecy = decision.confidentiality;
      const reviewReasons = (decision.block_reasons || []).map(readableReason);
      const dropReasons = rejected.flatMap((item: Obj) =>
        (item.block_reasons || []).map((reason: string) => `${label(item.kind || item.id)}：${readableReason(reason)}`));
      return <article className="decision-card" key={decision.fact_id}>
      <div className="fact-meta"><span className="fact-no">F{String(index + 1).padStart(2, "0")}</span>
        <Tag>{label(decision.field)}</Tag>
        {fromFollowup ? <Tag tone="amber">回写待纳入</Tag> : null}
        {decision.status === "review" ? <Tag tone="amber">复核</Tag> : null}
        {decision.sub_purpose ? <Tag>{label(String(decision.sub_purpose))}</Tag> : null}
        <select aria-label={`字段 ${index + 1} 必要性`} disabled={disabled} value={decision.necessity}
          onChange={event => onEdit(decision, { necessity: event.target.value })}>
          {["required", "conditional", "unnecessary", "uncertain"].map(value =>
            <option key={value} value={value}>{label(value)}</option>)}
        </select>
      </div>
      {candidates.length > 0
        ? <div className="transform-options">{allowed.map((item: Obj) =>
          <button disabled={disabled} className={decision.selected_candidate_id === item.id ? "active" : ""} key={item.id}
            onClick={() => onEdit(decision, { transform: item.transform, candidate_id: item.id })}>
            {(item.transform === "keep" || item.kind === "keep" ? "保持精度（身份已一致替换）" : label(item.kind || item.id))}</button>)}</div>
        : <div className="finding">当前规则没有提供可选的已校验处理候选；保留当前输出，不提供未经校验的替换选项。</div>}
      {allowed.some((item:Obj)=>item.transform === "keep") && <small className="reason">“保持精度”仍按稳定身份映射一致替换身份字段；原文与身份映射留在边侧。</small>}
      <div className={"disclosed-text " + (!decision.output ? "deleted" : "")}>
        {decision.output || "此项已删除，不进入外发内容。"}</div>
      {decision.retain_reason ? <small className="reason">保留理由：{readableReason(decision.retain_reason)}</small> : null}
      {decision.information_loss ? <small className="reason">信息损失：{decision.information_loss}</small> : null}
      <small className="reason">{decision.reason}</small>
      {reviewReasons.length > 0 ? <IssueList issues={reviewReasons}/> : null}
      {dropReasons.length > 0 ? <>
        <small className="reason">淘汰原因</small>
        <IssueList issues={dropReasons}/>
      </> : null}
      {basis && <dl className="judgment-list">
        {judgmentLine(basis, "necessity_judgment", "必要性")}
        {judgmentLine(basis, "processability_judgment", "可处理性")}
        {judgmentLine(basis, "residual_risk_judgment", "残余风险")}
      </dl>}
      {secrecy?.lawyer_law_article ? <small className="reason">
        律师法 {secrecy.lawyer_law_article}（{secrecy.lawyer_law_text_date || "2026-09-01"}）
        {secrecy.lawyer_law_mapping_note ? ` · ${secrecy.lawyer_law_mapping_note}` : ""}
      </small> : null}
      {suggestion && <div className="fact-meta">
        <Tag>模型建议 · 非规则</Tag>
        {suggestion.transform ? <Tag>{label(suggestion.transform)}</Tag> : null}
      </div>}
      {suggestion?.reason ? <small className="reason">{suggestion.reason}</small> : null}
      <div className="fact-footer">
        <button onClick={() => onLocate((task.fact_snapshot || []).find((fact: Obj) => fact.id === decision.fact_id)?.source_ids || [])}>
          <Link2 size={13}/>查看依据</button>
        {currentCase.mode === "formal" && <button disabled={disabled} onClick={() => onEditOutput(decision)}>编辑披露文本</button>}
      </div>
    </article>;
    })}
    <div className="bottom-action"><button className="primary" disabled={disabled} onClick={onEvaluate}>
      检验风险并冻结请求 <ArrowRight size={15}/></button></div>
  </>;
}
