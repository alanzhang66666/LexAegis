import { Fragment, useState } from "react";
import { AlertTriangle, ArrowRight, Check, Play, ShieldCheck } from "lucide-react";
import { Empty, IssueList, Tag } from "../components/ui";
import { ApprovalWorkspace, dispositionCopy } from "./ApprovalWorkspace";
import { FormalReleaseIntake } from "./FormalReleaseIntake";

type Obj = Record<string, any>;

export function RiskWorkspace({ task, pack, busy, role, runtimeProfile, dataOrigin, label, attackLabels, request, onRefreshCase, onAction, onApprove, onResult, onRunAttacks, onInstallPolicy, onLegalReview, onTechnicalIssue, onSuccessor }:{
  task: Obj; pack?: Obj; busy: boolean; role?:string; runtimeProfile?:string; dataOrigin?:string; label:(key:string)=>string; attackLabels:Record<string,string>;
  onAction:(action:string)=>void; onApprove:()=>void; onResult:()=>void; onRunAttacks:(auxiliary:Obj)=>void;
  onInstallPolicy?:()=>void;
  request:(path:string,method?:string,body?:any)=>Promise<any>; onRefreshCase:()=>Promise<void>;
  onLegalReview:(body:Obj)=>Promise<any>|void; onTechnicalIssue:(body:Obj)=>Promise<any>|void; onSuccessor:()=>void;
}) {
  const [auxiliary, setAuxiliary] = useState("{}");
  const [inputError, setInputError] = useState("");
  if (!task.risk) return <Empty title="检验当前披露方案" detail="冻结请求后，查看完整发送内容与阻断原因。" />;
  const formal = task.request?.mode === "formal";
  const syntheticAttackRun = ["demo", "integration"].includes(runtimeProfile || "")
    && dataOrigin === "bundled_synthetic";
  const attackRunAllowed = formal || syntheticAttackRun;
  const summary = dispositionCopy(task.risk);
  const reviewStatus = task.review_status || "pending";
  const reviewBlocked = !["cleared", "not_required"].includes(reviewStatus)
    || ["review_blocked", "rejected", "stopped"].includes(task.status);
  const manuallyStopped = ["blocked", "rejected"].includes(reviewStatus)
    || ["review_blocked", "rejected", "stopped"].includes(task.status);
  const effectiveTitle = reviewStatus === "rejected" || task.status === "rejected"
    ? "人工复核已否决，本次请求不可继续"
    : reviewStatus === "blocked" || task.status === "review_blocked" || task.status === "stopped"
      ? "本次请求已暂停"
      : reviewBlocked ? "待人工复核，本次请求暂不可继续" : summary.legal;
  const canReevaluate = !manuallyStopped && !["queued","sending","complete","unknown","rejected","stopped"].includes(task.status);
  const release = task.product_release || {};
  const releaseState = release.state || "blocked";
  const releaseAllowed = task.request?.mode !== "formal" || task.transport !== "cloud"
    ? ["not_applicable", "eligible", "armed_once"].includes(releaseState)
    : ["eligible", "armed_once"].includes(releaseState);
  const releaseReasons = [
    ...(release.reason ? [release.reason] : []),
    ...((release.decision?.hits || []).filter((hit:Obj)=>hit.status !== "pass").map((hit:Obj)=>hit.message || hit.reason_code).filter(Boolean)),
  ];
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
    <div role={reviewBlocked ? "alert" : undefined} className={"risk-banner " + (summary.blocked || reviewBlocked ? "blocked" : "ready")}>
      <ShieldCheck size={28}/><div><h2>当前操作状态：{effectiveTitle}</h2>
      <p>是否可以继续，以当前人工复核状态、风险门禁和审批状态共同决定。</p></div>
    </div>
    <div className="initial-risk-result"><b>系统初检结果</b><Tag tone={summary.blocked?"amber":"green"}>{summary.legal}</Tag>
      <span>{summary.ready} · 完整风险检验：{task.risk.completion === "complete" ? "已完成" : "未完成"} · 不代表已证明安全</span>
    </div>
    <div className="review-status-strip"><b>人工复核：{({pending:"待人工复核",blocked:"已暂停",rejected:"已否决",cleared:"已完成",not_required:"无需复核"} as Record<string,string>)[reviewStatus] || reviewStatus}</b>
      <span>{task.review_status === "rejected" || task.status === "rejected" ? "否决仅针对当前请求；请调整后创建关联后继任务。" : task.review_status === "blocked" || task.status === "review_blocked" ? "原初检结果保留供追溯，当前请求已停止。" : reviewBlocked ? "完成具名人工复核后才能继续。" : "人工复核状态已解除；仍需通过其余风险门禁和审批。"}</span>
    </div>
    <div className={"product-release-state " + (releaseAllowed ? "ready" : "blocked")}>
      <b>正式放行门：{releaseState === "eligible" ? "符合当前放行范围" : releaseState === "armed_once" ? "一次性许可已就绪" : releaseState === "not_applicable" ? "本任务不适用正式外发" : "未满足，禁止审批或发送"}</b>
      {releaseReasons.length > 0 && <ul>{[...new Set(releaseReasons)].map((message:string)=><li key={message}>{message}</li>)}</ul>}
    </div>
    <IssueList issues={task.risk.blockers}/>
    <h4 className="subheading">四类攻击运行</h4>
    <div className="attack-list">{(task.risk.attacks || []).map((attack:Obj)=><div key={attack.kind}>
      <span>{label(attack.kind)}</span><Tag tone={attack.outcome === "resisted" ? "green" : "amber"}>
        {attackLabels[attack.outcome || "not_run"]}</Tag>
      {syntheticAttackRun && attack.outcome && attack.outcome !== "not_run" && <Tag>{runtimeProfile==="demo"?"模拟结果":"合成材料联调"}</Tag>}
      <details><summary>检验依据</summary><dl className="metadata">
        {attack.protocol_id&&<><dt>协议</dt><dd>{attack.protocol_id} · {attack.protocol_version || "版本未记录"}</dd></>}
        {attack.attacker_view&&<><dt>攻击者可见范围</dt><dd>{Array.isArray(attack.attacker_view)?attack.attacker_view.join("、"):attack.attacker_view}</dd></>}
        {attack.input_hash&&<><dt>输入哈希</dt><dd><code>{attack.input_hash}</code></dd></>}
        {attack.result_hash&&<><dt>结果哈希</dt><dd><code>{attack.result_hash}</code></dd></>}
        {attack.evidence_ids?.length>0&&<><dt>证据</dt><dd>{attack.evidence_ids.join("、")}</dd></>}
        {attack.evidence?.length>0&&<><dt>证据摘要</dt><dd>{Array.isArray(attack.evidence)?attack.evidence.map((item:any)=>typeof item==="string"?item:item.summary||item.description||item.id).join("；"):String(attack.evidence)}</dd></>}
        {attack.provenance&&<><dt>结果来源</dt><dd>{attack.provenance}</dd></>}
        {attack.input_hash&&attack.input_hash!==attack.attacker_view_hash&&<><dt>攻击输入哈希</dt><dd><code>{attack.input_hash}</code></dd></>}
        {!attack.protocol_id&&!attack.attacker_view&&!attack.input_hash&&!attack.result_hash&&<dd>当前结果未提供独立协议证据。</dd>}
      </dl></details>
    </div>)}</div>
    {attackRunAllowed && <details className="attack-runner">
      {formal ? <>
      <summary>运行绑定到当前请求的隔离红队</summary>
      <p>只允许提供攻击者可见的辅助数据；原文、mapping、anchors 和 local_text 会被拒绝。</p>
      <textarea rows={5} value={auxiliary} onChange={event=>setAuxiliary(event.target.value)}
        aria-label="攻击者可见辅助数据 JSON"/>
      {inputError && <p className="error">{inputError}</p>}
      </> : <><summary>合成材料四类攻击联调</summary><p>仅使用已登记合成材料和当前冻结请求，不接受自定义攻击输入。</p></>}
      <button className="secondary" disabled={busy || task.redteam_status === "pending" || manuallyStopped || ["rejected","stopped","sending","unknown","complete"].includes(task.status)} onClick={()=>formal?runAttacks():onRunAttacks({})}>
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
      {runtimeProfile==="production"&&task.request?.mode==="formal"&&task.transport==="cloud"&&task.request_hash&&role==="admin"&&onInstallPolicy&&
        <button className="secondary" disabled={busy||Boolean(release.policy_id||release.policy?.id||task.formal_release_policy_id)} onClick={onInstallPolicy}>为当前完整请求创建阻断策略</button>}
      {task.status === "review" && role === "approver" && !reviewBlocked && releaseAllowed && <button className="primary" disabled={busy} onClick={onApprove}><Check size={16}/>审批当前完整请求</button>}
      {task.status === "approved" && ["case_operator","admin"].includes(role||"") && <button className="primary" disabled={busy || reviewBlocked || !releaseAllowed} onClick={()=>onAction("send")}><Play size={15}/>
        {task.transport === "mock" ? "执行模拟调用" : task.transport === "local" ? "生成本地摘要草稿" : "发送至已批准云端"}</button>}
      {task.status === "approved" && !["case_operator","admin"].includes(role||"") && <p className="small-note">当前具名角色不能执行发送；请交由案件操作人员完成发送。</p>}
      {task.status === "unknown" && <button className="secondary" onClick={()=>onAction("reconcile")}>查询网关记录（不重发）</button>}
      <button className="secondary" disabled={busy || !canReevaluate}
        onClick={()=>onAction("evaluate")}>重新检验</button>
      <button className="text-button danger-text" disabled={busy || reviewBlocked || ["queued","sending","complete","unknown"].includes(task.status)}
        onClick={()=>onAction("stop")}>停止任务</button>
      {(task.status === "rejected" || task.status === "review_blocked" || task.review_status === "rejected") &&
        <button className="secondary" disabled={busy} onClick={onSuccessor}>调整后创建关联后继任务</button>}
    </div>
    {runtimeProfile==="production"&&formal&&task.transport==="cloud"&&task.request_hash&&["technical_reviewer","legal_reviewer","approver","admin"].includes(role||"")&&
      <FormalReleaseIntake task={task} role={role} request={request} busy={busy} onRefreshCase={onRefreshCase}/>}
    {task.status === "complete" && <button className="primary" onClick={onResult}>查看摘要与回链 <ArrowRight size={16}/></button>}
    {task.error && <div className="inline-warning"><AlertTriangle size={14}/>{task.error}</div>}
    <ApprovalWorkspace task={task} pack={pack} busy={busy} role={role} onSubmit={onLegalReview} onTechnicalIssue={onTechnicalIssue}/>
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
