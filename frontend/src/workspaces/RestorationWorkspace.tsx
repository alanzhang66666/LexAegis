import { Check, Download } from "lucide-react";
import { AnchorViewer, Empty, IssueList, Tag } from "../components/ui";

type Obj = Record<string, any>;

export function RestorationWorkspace({task,busy,locate,onAction}:{
  task:Obj;busy:boolean;locate:(ids:any[])=>void;onAction:(action:string)=>void;
}) {
  if (!task.artifact) return <Empty title="尚无摘要结果" detail="完成审批和调用后，结果会在此进入来源校核。"/>;
  if (task.type === "timeline") return <>
    <div className="result-heading"><Tag tone="green">本地确定性结果</Tag></div>
    <p className="context-note">时间线仅从已确认事实中筛选，不调用边侧或云端模型。</p>
    {(task.artifact.events||[]).map((event:Obj,index:number)=><article className="claim-card" key={event.id}>
      <div className="fact-meta"><span className="fact-no">{String(index+1).padStart(2,"0")}</span><Tag>时间事实</Tag></div>
      <p>{event.text}</p><div className="fact-footer"><AnchorViewer anchors={event.source_ids} onOpen={locate}/></div>
    </article>)}
  </>;
  return <>
    <div className="result-heading"><Tag tone={task.artifact.provenance==="simulation"?"amber":"green"}>
      {task.artifact.provenance==="simulation"?"模拟结果 · 非模型生成":"云端 API 返回"}</Tag>
      <a className="text-button" href={`/api/v1/tasks/${task.id}/export`}><Download size={14}/>导出云端视图</a>
    </div>
    <p className="context-note">云端原句与边侧身份回填分轨保存；引用优先于字符串替换。</p>
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
