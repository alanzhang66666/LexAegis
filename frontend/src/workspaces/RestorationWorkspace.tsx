import { Check, Download } from "lucide-react";
import { AnchorViewer, Empty, IssueList, Tag } from "../components/ui";

type Obj = Record<string, any>;

const GAP_LABEL: Record<string, string> = {
  missing_field: "缺少字段",
  insufficient_support: "依据不足",
  ambiguous_reference: "引用含混",
  other: "其他",
};

function FeedbackPanel({ task, currentCase, busy, onDismissFollowup, onFollowupTask }: {
  task: Obj; currentCase?: Obj; busy: boolean;
  onDismissFollowup?: (id: string) => void; onFollowupTask?: () => void;
}) {
  const unusedIds: string[] = task.artifact.unused_fact_ids || [];
  const gaps: Obj[] = task.artifact.gaps || [];
  const issues: string[] = task.artifact.feedback_issues || [];
  const decisions: Obj[] = task.decisions || [];
  const facts: Obj[] = task.fact_snapshot || [];
  const unused = unusedIds.map((id) => {
    const decision = decisions.find((item) => item.fact_id === id);
    const fact = facts.find((item) => item.id === id);
    return {
      id,
      field: decision?.field || fact?.field || "",
      text: decision?.output || fact?.value || id,
    };
  });
  return <article className="claim-card">
    <div className="fact-meta"><Tag>云边回写</Tag>
      {unused.length ? <Tag tone="amber">未使用 {unused.length}</Tag> : <Tag tone="green">外发事实均已被引用</Tag>}
    </div>
    {unused.length ? <div className="restoration-grid">
      {unused.map((item) => <section key={item.id}>
        <small>{item.field || "未使用事实"}</small>
        <p>{item.text}</p>
      </section>)}
    </div> : <p className="context-note">外发事实均已被引用。</p>}
    {gaps.map((gap, index) => <p className="context-note" key={`${gap.code}-${index}`}>
      {GAP_LABEL[gap.code] || gap.code}：{gap.detail}
      {gap.fact_ids?.length ? `（${gap.fact_ids.join("、")}）` : ""}
    </p>)}
    <IssueList issues={issues}/>
    {(() => {
      const followups = ((currentCase?.followups || []) as Obj[]).filter((item) =>
        item.source_task_id === task.id || item.status === "open");
      const openUnused = followups.filter((item) => item.status === "open" && item.kind === "unused_fact");
      if (!followups.length) return null;
      return <>
        {followups.map((item) => <div className="fact-footer" key={item.id}>
          <small>{item.kind === "unused_fact" ? "未使用事实" : item.kind === "gap" ? "云端缺口" : "回写问题"}：{item.detail}</small>
          {item.status === "open" && onDismissFollowup
            ? <button disabled={busy} onClick={() => onDismissFollowup(item.id)}>已阅并忽略</button>
            : <Tag>{item.status === "addressed" ? "已转入新任务" : item.status === "dismissed" ? "已忽略" : item.status}</Tag>}
        </div>)}
        {openUnused.length > 0 && onFollowupTask
          ? <div className="bottom-action"><button className="secondary" disabled={busy} onClick={onFollowupTask}>
              从未使用事实创建后续披露</button></div>
          : null}
      </>;
    })()}
  </article>;
}

export function RestorationWorkspace({task,currentCase,busy,locate,onAction,onDismissFollowup,onFollowupTask}:{
  task:Obj;currentCase?:Obj;busy:boolean;locate:(ids:any[])=>void;onAction:(action:string)=>void;
  onDismissFollowup?:(id:string)=>void;onFollowupTask?:()=>void;
}) {
  if (!task.artifact) return <Empty title="尚无摘要结果" detail="完成审批和调用后，结果会在此进入来源校核。"/>;
  if (task.type === "timeline" || task.type === "evidence_inventory" || task.type === "issue_extraction") {
    const rows = task.type === "timeline" ? (task.artifact.events || [])
      : task.type === "evidence_inventory" ? (task.artifact.items || [])
      : (task.artifact.issues || []);
    const note = task.type === "timeline"
      ? "时间线仅从已确认事实中筛选，不调用边侧或云端模型。"
      : task.type === "evidence_inventory"
        ? "证据清单仅列出 field=evidence 的已有事实，不调用边侧或云端模型。"
        : "按字段分组的候选 · 非法学结论 · 未调用模型";
    return <>
    <div className="result-heading"><Tag tone="green">本地确定性结果</Tag></div>
    <p className="context-note">{note}</p>
    {rows.map((row:Obj,index:number)=><article className="claim-card" key={row.id}>
      <div className="fact-meta"><span className="fact-no">{String(index+1).padStart(2,"0")}</span>
        <Tag>{task.type === "timeline" ? "时间事实" : task.type === "evidence_inventory" ? "证据" : (row.label || row.topic)}</Tag></div>
      <p>{row.text}</p>
      {row.purpose ? <small className="reason">{row.purpose}</small> : null}
      <div className="fact-footer"><AnchorViewer anchors={row.source_ids} onOpen={locate}/></div>
    </article>)}
  </>;
  }
  return <>
    <div className="result-heading"><Tag tone={task.artifact.provenance==="cloud"?"green":"amber"}>
      {task.artifact.provenance==="simulation"?"模拟结果 · 非模型生成":task.artifact.provenance==="local_deterministic"?"本地确定性草稿 · 未调用云端":"云端 API 返回"}</Tag>
      <a className="text-button" href={`/api/v1/tasks/${task.id}/export`}><Download size={14}/>导出云端视图</a>
    </div>
    <p className="context-note">云端原句与边侧身份回填分轨保存；引用优先于字符串替换。</p>
    <FeedbackPanel task={task} currentCase={currentCase} busy={busy}
      onDismissFollowup={onDismissFollowup} onFollowupTask={onFollowupTask}/>
    {(task.artifact.claims||[]).map((claim:Obj,index:number)=><article className="claim-card restoration-card" key={claim.id}>
      <div className="fact-meta"><span className="fact-no">{String(index+1).padStart(2,"0")}</span>
        <Tag tone={claim.reviewed?"green":"amber"}>{claim.reviewed?"律师已复核":claim.status==="source_matched"?"引用文本匹配":"需人工复核"}</Tag>
      </div>
      <div className="restoration-grid">
        <section><small>云端陈述 · 假名化审计轨</small><p>{claim.text}</p></section>
        <section><small>边侧复原 · 本地查看轨</small><p>{claim.local_text||claim.text}</p></section>
        <section><small>实际外发支持事实</small>{(claim.support||[]).map((text:string)=><p key={text}>{text}</p>)}</section>
        <section><small>原文锚点</small><p>{(claim.anchors||[]).map((anchor:Obj)=>`${anchor.locator||anchor.id} · v${anchor.document_version}`).join("；")||"无可用锚点"}</p></section>
      </div>
      <IssueList issues={claim.issues||[]}/>
      <div className="fact-footer"><AnchorViewer anchors={claim.anchors||[]} onOpen={locate}/>
        <button disabled={busy||claim.reviewed||task.stale} onClick={()=>onAction("claims/"+claim.id+"/review")}>
          {claim.reviewed?"已确认":"已核对本项"}</button>
      </div>
    </article>)}
    <div className="bottom-action"><button className="primary" disabled={busy||task.artifact.confirmed||task.stale||
      !(task.artifact.claims||[]).every((claim:Obj)=>claim.reviewed)} onClick={()=>onAction("confirm")}>
      <Check size={15}/>{task.artifact.confirmed?"结果已确认":"确认最终结果"}</button></div>
  </>;
}
