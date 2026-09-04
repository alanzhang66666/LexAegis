import { Download, ExternalLink, LockKeyhole, X } from "lucide-react";
import { AuditTimeline } from "../components/ui";

type Obj = Record<string, any>;

export function ContextRail({ currentCase, task, caseId, audit, busy, onClose, onStartCloud }: {
  currentCase: Obj; task?: Obj; caseId: string; audit: Obj[]; busy: boolean;
  onClose: () => void; onStartCloud: () => void;
}) {
  return <aside className="context-panel">
    <div className="panel-heading"><h3>依据与运行边界</h3>
      <button className="context-close" aria-label="关闭依据面板" onClick={onClose}><X size={16}/></button></div>
    <div className="boundary-card"><LockKeyhole size={20}/><h4>原文始终留在边侧</h4>
      <p>身份映射、内部理由和评分真值不会自动进入云端请求。</p></div>
    <dl className="metadata">
      <dt>运行模式</dt><dd>{currentCase.mode === "demo" ? "固定合成演示" : "正式案件"}</dd>
      <dt>当前任务</dt><dd>{task?.type || "尚未创建"}</dd>
      <dt>规则版本</dt><dd>{task?.pack_id || "尚未绑定"}</dd>
      <dt>调用方式</dt><dd>{task ? task.transport === "mock" ? "模拟调用（不访问云端）" :
        task.transport === "local" ? "本地确定性" : "云端大模型 API" : "待创建任务"}</dd>
    </dl>
    {currentCase.mode === "demo" && <button className="secondary full" disabled={busy} onClick={onStartCloud}>
      <ExternalLink size={14}/>新建真实 API 演示任务</button>}
    <div className="context-divider"/>
    <h4 className="aside-title">操作留痕
      <a href={`/api/v1/cases/${caseId}/audit-export`} title="导出审计"><Download size={14}/></a></h4>
    <AuditTimeline events={audit}/>
    <p className="small-note">风险攻击未按冻结协议完成时不会显示“通过”。正式案件当前保持外发阻断。</p>
  </aside>;
}
