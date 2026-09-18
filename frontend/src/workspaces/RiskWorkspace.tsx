import { Fragment, useState } from "react";
import { AlertTriangle, ArrowRight, Check, Play, ShieldCheck } from "lucide-react";
import { Empty, IssueList, Tag } from "../components/ui";
import { ApprovalWorkspace, dispositionCopy } from "./ApprovalWorkspace";

type Obj = Record<string, any>;

export function RiskWorkspace({ task, pack, busy, label, attackLabels, onAction, onApprove, onResult, onRunAttacks, onLegalReview }:{
  task: Obj; pack?: Obj; busy: boolean; label:(key:string)=>string; attackLabels:Record<string,string>;
  onAction:(action:string)=>void; onApprove:()=>void; onResult:()=>void; onRunAttacks:(auxiliary:Obj)=>void;
  onLegalReview:(body:Obj)=>void;
}) {
  const [auxiliary, setAuxiliary] = useState("{}");
  const [inputError, setInputError] = useState("");
  if (!task.risk) return <Empty title="检验当前披露方案" detail="冻结请求后，查看完整发送内容与阻断原因。" />;
  const formal = task.request?.mode === "formal";
  const summary = dispositionCopy(task.risk);
  const runAttacks = () => {
    try {
      const value = JSON.parse(auxiliary);
      if (!value || Array.isArray(value) || typeof value !== "object") throw new Error();
      setInputError("");
      onRunAttacks(value);
    } catch {
      setInputError("辅助数据必须为以协议 id 或攻击类型为键的 JSON 对象。");
    }
  };
  return <>
    <div className={"risk-banner " + (summary.blocked ? "blocked" : "ready")}>
      <ShieldCheck size={28}/><div><h2>{summary.legal}</h2>
      <p>{summary.ready} · 完整风险检验：{task.risk.completion === "complete" ? "已完成" : "未完成"} · 不代表已证明安全，也不授予发送权</p></div>
    </div>
    <IssueList issues={task.risk.blockers}/>
    <h4 className="subheading">四类攻击运行</h4>
    <div className="attack-list">{task.risk.attacks.map((attack:Obj)=><div key={attack.kind}>
      <span>{label(attack.kind)}</span><Tag tone={attack.outcome === "resisted" ? "green" : "amber"}>
        {attackLabels[attack.outcome || "not_run"]}</Tag>
    </div>)}</div>
    {formal && <details className="attack-runner">
      <summary>运行绑定到当前请求的隔离红队</summary>
      <p>只允许提供攻击者可见的辅助数据；原文、mapping、anchors 和 local_text 会被拒绝。</p>
      <textarea rows={5} value={auxiliary} onChange={event=>setAuxiliary(event.target.value)}
        aria-label="攻击者可见辅助数据 JSON"/>
      {inputError && <p className="error">{inputError}</p>}
      <button className="secondary" disabled={busy || task.redteam_status === "pending"} onClick={runAttacks}>
        {task.redteam_status === "pending" ? "红队作业排队中" : "排队运行四类攻击"}
      </button>
    </details>}
    {task.risk.findings.map((finding:string)=><p className="finding" key={finding}>{finding}</p>)}
    <details className="request-detail" open>
      <summary>完整请求快照 <Tag>v{task.version}</Tag></summary>
      <div className="request-target"><b>目标</b>{task.request.target}<b>模型</b>{task.request.body.model}</div>
      <RequestPreviewMeta task={task}/>
      {(task.attempts || []).length > 0 && (
        <dl className="metadata">
          {task.attempts.map((attempt: Obj, index: number) => (
            <Fragment key={attempt.id || index}>
              <dt>{attempt.slot || "槽位"} · {attempt.disclosure_state === "possible" ? "可能披露" : attempt.disclosure_state === "disclosed" ? "已披露" : "未离开本地"}</dt>
              <dd>{attempt.generation_state || "not_started"} · {attempt.target || "目标未记录"}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      <pre>{JSON.stringify(task.request.body,null,2)}</pre><small>SHA-256 · {task.request_hash}</small>
    </details>
    <div className="approval-actions">
      {task.status === "review" && <button className="primary" disabled={busy} onClick={onApprove}><Check size={16}/>审批当前完整请求</button>}
      {task.status === "approved" && <button className="primary" disabled={busy} onClick={()=>onAction("send")}><Play size={15}/>
        {task.transport === "mock" ? "执行模拟调用" : task.transport === "local" ? "生成本地摘要草稿" : "发送至已批准云端"}</button>}
      {task.status === "unknown" && <button className="secondary" onClick={()=>onAction("reconcile")}>查询网关记录（不重发）</button>}
      <button className="secondary" disabled={busy || ["queued","sending","complete","unknown"].includes(task.status)}
        onClick={()=>onAction("evaluate")}>重新检验</button>
      <button className="text-button danger-text" disabled={busy || ["queued","sending","complete","unknown"].includes(task.status)}
        onClick={()=>onAction("stop")}>停止任务</button>
    </div>
    {task.status === "complete" && <button className="primary" onClick={onResult}>查看摘要与回链 <ArrowRight size={16}/></button>}
    {task.error && <div className="inline-warning"><AlertTriangle size={14}/>{task.error}</div>}
    <ApprovalWorkspace task={task} pack={pack} busy={busy} onSubmit={onLegalReview}/>
  </>;
}

function materialVersionLabel(versions: Obj | undefined) {
  const entries = Object.entries(versions || {});
  if (!entries.length) return "无材料版本";
  return entries.map(([id, version]) => `${id} v${version}`).join(" · ");
}

function RequestPreviewMeta({ task }: { task: Obj }) {
  const deps = task.request?.dependencies || {};
  const recipients = task.authorized_recipients || deps.authorized_recipients || [];
  const hasStandby = recipients.some((item: Obj) => item.slot === "standby" || item.role === "standby");
  const primary = recipients.filter((item: Obj) => item.slot === "primary" || item.role === "primary" || (!item.slot && !item.role));
  const shown = hasStandby ? recipients : (primary.length ? primary : recipients);
  const standbyNote = deps.standby_note || (hasStandby
    ? "未审核备用不会纳入批准目标。仅确认请求未离开本地才允许切备。"
    : "备用槽已关闭。境内与国际百炼均不纳入本次批准目标。");
  return <>
    <p className="small-note">{standbyNote}</p>
    <dl className="metadata">
      <dt>系统提示词哈希</dt>
      <dd className="tabular">{deps.prompt_hash || "未绑定"}</dd>
      <dt>案由包</dt>
      <dd>{deps.pack || task.pack_id || "未绑定"} · {deps.pack_hash || "哈希未绑定"}</dd>
      <dt>设置版本</dt>
      <dd className="tabular">{deps.settings_version ?? task.settings_version ?? "未绑定"}</dd>
      <dt>材料版本</dt>
      <dd>{materialVersionLabel(deps.material_versions)}</dd>
      <dt>授权接收方</dt>
      <dd>{hasStandby ? "主槽与已审核备槽" : "仅主槽；备槽关闭"}</dd>
    </dl>
    {shown.length > 0 && (
      <dl className="metadata">
        {shown.map((item: Obj, index: number) => (
          <Fragment key={item.slot || item.role || index}>
            <dt>授权 {item.slot || item.role || "主槽"}</dt>
            <dd>{item.model || "模型未提供"} · {item.target || "目标未提供"}</dd>
          </Fragment>
        ))}
      </dl>
    )}
  </>;
}
