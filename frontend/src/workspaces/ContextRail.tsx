import { PRODUCT_VERSION } from "../release";
import { Fragment } from "react";
import { Download, ExternalLink, LockKeyhole, X } from "lucide-react";
import { AuditTimeline } from "../components/ui";

type Obj = Record<string, any>;

export function ContextRail({ currentCase, task, caseId, audit, busy, runtimeProfile, runtimeConfig, onClose, onStartCloud }: {
  currentCase: Obj; task?: Obj; caseId: string; audit: Obj[]; busy: boolean; runtimeProfile?: string; runtimeConfig?:Obj;
  onClose: () => void; onStartCloud: () => void;
}) {
  const attempts = task?.attempts || [];
  return <aside className="context-panel">
    <div className="panel-heading"><h3>依据与运行边界</h3>
      <button className="context-close" aria-label="关闭依据面板" onClick={onClose}><X size={16}/></button></div>
    <div className="boundary-card"><LockKeyhole size={20}/><h4>原文始终留在边侧</h4>
      <p>身份映射、内部理由和评分真值不会自动进入云端请求。</p></div>
    <dl className="metadata">
      {runtimeProfile !== "demo" && <><dt>运行环境</dt><dd>{runtimeProfile || "未知"}</dd>
      <dt>数据来源</dt><dd>{currentCase.data_origin || (currentCase.mode === "demo" ? "synthetic" : "case_materials")}</dd>
      {currentCase.synthetic_manifest_hash&&<><dt>合成清单哈希</dt><dd><code>{currentCase.synthetic_manifest_hash}</code></dd></>}
      </>}<dt>运行模式</dt><dd>{currentCase.mode === "demo" ? "案例工作区" : "正式案件"}</dd>
      {runtimeConfig&&<><dt>返回方式</dt><dd>{runtimeConfig.mock_responses ? "本地预置" : runtimeConfig.external_calls_allowed ? "允许联调外呼" : "禁止外呼"}</dd></>}
      <dt>当前任务</dt><dd>{task?.type || "尚未创建"}</dd>
      <dt>{runtimeProfile === "demo" ? "产品版本" : "规则版本"}</dt><dd>{runtimeProfile === "demo" ? PRODUCT_VERSION : task?.pack_id || "尚未绑定"}</dd>
      <dt>调用方式</dt><dd>{task ? task.transport === "mock" ? "本地处理（不访问云端）" :
        task.transport === "local" ? "本地确定性" : "云端大模型 API" : "待创建任务"}</dd>
      <dt>回写待办</dt><dd>{(currentCase.followups || []).filter((item: Obj) => item.status === "open").length} 项未处理</dd>
      <dt>授权接收方</dt><dd>{authorizedLabel(task)}</dd>
    </dl>
    {attempts.length > 0 && <div>
      <h4 className="aside-title">发送尝试</h4>
      <dl className="metadata">{attempts.map((attempt: Obj, index: number) => (
        <Fragment key={attempt.id || index}>
          <dt>{attempt.slot || "槽位"} · {disclosureLabel(attempt.disclosure_state)}</dt>
          <dd>{attempt.target || "目标未记录"} · {generationLabel(attempt.generation_state)}</dd>
        </Fragment>
      ))}</dl>
      <p className="small-note">逐次尝试分开记录生成状态、是否离开本地和披露状态。可能披露不等于已确认送达。</p>
    </div>}
    {currentCase.mode === "demo" && runtimeProfile === "integration" && runtimeConfig?.external_calls_allowed && <button className="secondary full" disabled={busy} onClick={onStartCloud}>
      <ExternalLink size={14}/>新建真实 API 联调任务</button>}
    {currentCase.mode === "formal" && runtimeProfile === "production" && <button className="secondary full" disabled={busy} onClick={onStartCloud}>
      <ExternalLink size={14}/>新建正式云端请求草案</button>}
    <div className="context-divider"/>
    <h4 className="aside-title">操作留痕
      <a href={`/api/v1/cases/${caseId}/audit-export`} title="导出审计"><Download size={14}/></a></h4>
    <AuditTimeline events={audit}/>
    {runtimeProfile!=="demo"&&<p className="small-note">创建请求只生成待检验草案，不会调用服务商。外发仍须规则、证据、风险复核、审批和一次性许可；风险攻击未按冻结协议完成时不会显示“通过”。</p>}
  </aside>;
}

function authorizedLabel(task?: Obj) {
  const recipients = task?.authorized_recipients || task?.request?.dependencies?.authorized_recipients || [];
  if (!recipients.length) {
    const note = task?.request?.dependencies?.standby_note;
    return note || "尚未冻结批准目标";
  }
  return recipients.map((item: Obj) => item.slot || item.model || item.target).join(" / ");
}

function disclosureLabel(state?: string) {
  if (state === "disclosed") return "已披露";
  if (state === "possible") return "可能披露";
  if (state === "undisclosed") return "未离开本地";
  return "未记录";
}

function generationLabel(state?: string) {
  if (state === "complete") return "生成完成";
  if (state === "started") return "已开始生成";
  return "未开始生成";
}
