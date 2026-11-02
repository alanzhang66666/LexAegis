import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, ShieldAlert, Upload } from "lucide-react";
import { Button, Panel, StatusBadge } from "../components/ui";

type Obj = Record<string, any>;
type RequestFn = (path:string,method?:string,body?:any)=>Promise<any>;

const roleLabel:Record<string,string>={legal_reviewer:"法学人员",technical_reviewer:"技术复核人员",approver:"审批人",case_operator:"案件操作员",admin:"管理员"};
const readinessKinds=["build_manifest","compose_isolation","k8s_conformance","host_firewall","supply_chain"] as const;
const readinessLabel:Record<string,string>={build_manifest:"构建清单",compose_isolation:"Compose 隔离",k8s_conformance:"kind/KubeEdge 一致性",host_firewall:"宿主机防火墙",supply_chain:"供应链"};
const readinessRole:Record<string,string>={build_manifest:"技术复核人员",compose_isolation:"技术复核人员",k8s_conformance:"技术复核人员",host_firewall:"技术复核人员",supply_chain:"技术复核人员"};
const readinessStatus:Record<string,string>={pass:"通过",pending:"待补证",fail:"失败",expired:"已过期",stale:"已失效",unknown:"未知"};
const isoNow=()=>new Date().toISOString();
const stable=(value:Obj)=>JSON.stringify(Object.fromEntries(Object.entries(value||{}).sort(([a],[b])=>a.localeCompare(b))));
const toIso=(value:string|undefined)=>value?new Date(value).toISOString():null;

export function FormalReleaseIntake({task,role,request,busy,onRefreshCase}:{task:Obj;role?:string;request:RequestFn;busy:boolean;onRefreshCase:()=>Promise<void>}) {
  const [context,setContext]=useState<Obj|null>(null),[artifacts,setArtifacts]=useState<Obj[]>([]),[receipts,setReceipts]=useState<Obj[]>([]),[isolations,setIsolations]=useState<Obj[]>([]);
  const [templateKind,setTemplateKind]=useState(""),[file,setFile]=useState<File|null>(null),[isolationFile,setIsolationFile]=useState<File|null>(null);
  const [drafts,setDrafts]=useState<Record<string,Obj>>({}),[revokeReason,setRevokeReason]=useState<Record<string,string>>({});
  const [error,setError]=useState(""),[notice,setNotice]=useState(""),[working,setWorking]=useState(false);
  const [contextUnavailable,setContextUnavailable]=useState(false);
  const [g8Selection,setG8Selection]=useState<Record<string,string>>({});
  const base=`/tasks/${encodeURIComponent(task.id)}/formal-release`;
  const taskKey=`${task.id}:${task.request_hash||""}`,taskKeyRef=useRef(taskKey);taskKeyRef.current=taskKey;
  const reload=async()=>{
    const expectedKey=taskKey;
    setError("");setContextUnavailable(false);
    const [value,status]=await Promise.all([request(`${base}/intake-context`),request("/formal-release")]);
    if(taskKeyRef.current!==expectedKey)return;
    if(value.task_id!==task.id||value.request_hash!==task.request_hash)
      throw new Error("正式证据上下文与当前任务 ID/请求哈希不匹配；请刷新任务，不会接受旧快照。");
    setContext(value);setArtifacts(status.artifacts||[]);setReceipts((status.receipts||[]).filter((item:Obj)=>sameTuple(item.tuple,value.tuple)&&
      (item.request_hash===value.request_hash||(["G1","G2","G3","G5"].includes(item.gate_id)&&stable(item.bound_versions)===stable(value.bound_versions)))));
    setIsolations((status.isolation_receipts||[]).filter((item:Obj)=>item.request_hash===value.request_hash&&sameTuple(item.tuple,value.tuple)));
  };
  useEffect(()=>{setContext(null);setContextUnavailable(false);setDrafts({});setG8Selection({});setReceipts([]);setIsolations([]);reload().catch(e=>{
    if(taskKeyRef.current===taskKey){setContextUnavailable(true);setError((e as Error).message)}})},[task.id,task.request_hash]);
  const availableKinds=useMemo<string[]>(()=>{
    const kinds=(context?.gates||[]).flatMap((gate:Obj)=>gate.templates||[])
      .flatMap((item:Obj)=>[item.template_kind,item.technical_template].filter(Boolean).map(String));
    return Array.from(new Set(kinds));
  },[context]);
  const setDraft=(key:string,change:Obj)=>setDrafts(old=>({...old,[key]:{...old[key],...change}}));
  const matchingArtifacts=(kind:string)=>artifacts.filter(item=>normalize(item.template_kind)===normalize(kind));
  const upload=async()=>{
    if(!templateKind||!file)return;
    setWorking(true);setError("");setNotice("");
    try{const data=new FormData();data.append("file",file);const result=await request(`/formal-release/evidence?template_kind=${encodeURIComponent(templateKind)}`,"POST",data);
      setFile(null);await reload();setNotice(`已登记 ${templateKind} 证据 ${result.id} · SHA-256 ${result.content_hash}。登记不代表通过。`);
    }catch(e){setError((e as Error).message)}finally{setWorking(false)}
  };
  const saveReceipt=async(gate:Obj,template:Obj)=>{
    const key=`${gate.gate_id}:${template.template_kind}`,draft=drafts[key]||{};
    if(!context)return;
    const matchingTemplate=matchingArtifacts(template.template_kind).find((item:Obj)=>item.id===draft.templateArtifactId);
    const allArtifactIds=Array.from(new Set([matchingTemplate?.id,...(draft.evidenceIds||[]),...(draft.organizationId?[draft.organizationId]:[]),...(draft.technicalId?[draft.technicalId]:[])].filter(Boolean)));
    if(!matchingTemplate){setError("请先选择与本表格类别匹配的已登记模板原件。");return}
    const body:Obj={gate_id:gate.gate_id,tuple:context.tuple,template_kind:template.template_kind,template_version:draft.templateVersion||"",
      template_artifact_id:matchingTemplate.id,bound_versions:["G1","G2","G3","G5"].includes(gate.gate_id)?context.bound_versions:{},
      request_hash:["G6","G7","G8","G9","G10"].includes(gate.gate_id)?context.request_hash:null,
      conclusion:draft.conclusion||"pending",evidence_artifact_ids:allArtifactIds,confirmed_by:context.actor.actor,confirmed_role:role,confirmed_at:isoNow(),
      valid_from:toIso(draft.validFrom),valid_until:toIso(draft.validUntil)};
    if(gate.gate_id==="G1")body.adopted_fact_ids=draft.factIds||[];
    if(gate.gate_id==="G2") {body.authorization_statement=context.g2_authorization_statement;body.organization_authorization_artifact_id=draft.organizationId||null}
    if(template.technical_template&&draft.technicalId){const tech=artifacts.find(item=>item.id===draft.technicalId);body.technical_evidence_artifact_id=tech?.id;body.technical_evidence_hash=tech?.content_hash;body.technical_evidence_request_hash=context.request_hash}
    if((draft.conclusion||"pending")==="pass"&&(!draft.templateVersion||!draft.validFrom||!draft.validUntil||!allArtifactIds.length)){
      setError("通过结论必须绑定模板版本、有效期和至少一项附件证据；表单不会自动补齐这些内容。");return}
    if((draft.conclusion||"pending")==="pass"&&gate.gate_id==="G1"&&!(draft.factIds||[]).length){setError("G1 通过收据须明确勾选采纳的当前披露事实。");return}
    if((draft.conclusion||"pending")==="pass"&&gate.gate_id==="G2"&&!draft.organizationId){setError("G2 通过收据须选择组织授权材料。");return}
    if((draft.conclusion||"pending")==="pass"&&template.technical_template&&!draft.technicalId){setError(`${gate.gate_id} 通过收据须选择对应的 ${template.technical_template} 技术证据。`);return}
    setWorking(true);setError("");setNotice("");
    try{const result=await request("/formal-release/receipts","POST",body);await reload();setNotice(`${result.gate_id} ${result.template_kind} 收据已登记为“${result.conclusion}”。`)}
    catch(e){setError((e as Error).message)}finally{setWorking(false)}
  };
  const submitIsolation=async()=>{
    if(!isolationFile||!context)return;
    setWorking(true);setError("");
    try{const value=JSON.parse(await isolationFile.text());if(!value||Array.isArray(value)||typeof value!=="object")throw new Error("隔离收据必须是 JSON 对象。");
      if(!sameTuple(value.tuple,context.tuple)||value.request_hash!==context.request_hash||value.build_manifest_hash!==context.build_manifest_hash)
        throw new Error("隔离证据的案件、请求哈希和构建哈希必须与当前上下文完全一致；系统不会替换或重绑定原文件字段。");
      if(value.status!=="pending_legal_confirmation"||value.legal_confirmation_receipt_id)
        throw new Error("技术提交的隔离收据必须处于 pending_legal_confirmation 且未填写法学确认；原始状态不会被自动改写。");
      const result=await request("/formal-release/isolation","POST",value);setIsolationFile(null);await reload();setNotice(`技术隔离收据 ${result.id} 已登记，正在等待法学人员基于同请求 G8 通过收据确认。`);
    }catch(e){setError((e as Error).message)}finally{setWorking(false)}
  };
  const confirmIsolation=async(item:Obj)=>{
    const g8=receipts.find(receipt=>receipt.id===g8Selection[item.id]&&receipt.gate_id==="G8"&&receipt.conclusion==="pass"&&!receipt.revoked_at&&receipt.confirmed_role==="legal_reviewer"&&receipt.confirmed_by===context?.actor?.actor);
    if(!g8){setError("当前请求没有有效的法学 G8 通过收据，不能确认隔离证据。");return}
    setWorking(true);setError("");
    try{await request(`/formal-release/isolation/${encodeURIComponent(item.id)}/confirm`,"POST",{receipt_id:g8.id});await reload();setNotice("法学人员已将该技术隔离收据与当前请求的 G8 收据绑定确认。")}
    catch(e){setError((e as Error).message)}finally{setWorking(false)}
  };
  const revoke=async(item:Obj)=>{
    const reason=revokeReason[item.id]?.trim();if(!reason){setError("撤销前请填写理由。");return}
    setWorking(true);setError("");
    try{await request(`/formal-release/receipts/${encodeURIComponent(item.id)}/revoke`,"POST",{reason});await reload();setNotice("收据已登记撤销；历史记录保留。")}
    catch(e){setError((e as Error).message)}finally{setWorking(false)}
  };
  const check=async()=>{setWorking(true);setError("");setNotice("");try{await request(`${base}/check`,"POST",{});await onRefreshCase();await reload();setNotice("已按当前证据手动检查放行门；刷新后以页面回显状态为准。")}
    catch(e){setError((e as Error).message)}finally{setWorking(false)}};
  const actor=context?.actor?.role;
  return <Panel title="正式放行证据与人工收据" actions={<button disabled={working||busy} onClick={()=>reload().catch(e=>setError((e as Error).message))}><RefreshCw size={14}/>刷新上下文</button>}>
    <div className="legal-block"><ShieldAlert/><div><h3>每份收据须绑定当前请求和具名人员</h3><p>上传原件只登记附件与哈希。人工结论默认为 pending，不会自动通过、批准或发送；本面板只用于当前正式云端请求。</p></div></div>
    {contextUnavailable||!context?<div className="inline-warning" role="status">当前正式证据上下文不可用：{error||"请先冻结请求并满足构建、网关和服务身份检查。"} 未生成或补填任何放行证据。</div>:<>
      <dl className="metadata"><dt>请求哈希</dt><dd><code>{context.request_hash}</code></dd><dt>绑定范围</dt><dd>{context.tuple.case_id} · {context.tuple.purpose} · {context.tuple.recipient}</dd>
        <dt>构建清单哈希</dt><dd><code>{context.build_manifest_hash}</code></dd><dt>当前登记人</dt><dd>{actor} · {context.actor.actor}（{context.actor.username}）</dd></dl>
      <ReadinessPanel report={context.readiness} receipts={receipts}/>
      <div className="governance-form"><label>证据模板类别<select value={templateKind} onChange={event=>setTemplateKind(event.target.value)}><option value="">选择法/技模板</option>
        {availableKinds.map((kind:string)=><option key={kind}>{kind}</option>)}</select></label><label>上传受控模板/证据原件<input type="file" onChange={event=>setFile(event.target.files?.[0]||null)}/></label></div>
      <p className="small-note">上传后只保存受控副本与内容哈希。请核对现有原件并由相应法学、技术或审批角色另行签收。</p>
      <Button disabled={working||busy||!templateKind||!file} onClick={upload}><Upload size={14}/>登记选定证据</Button>
      {(context.gates||[]).map((gate:Obj)=><div className="intake-gate" key={gate.gate_id}><h4>{gate.gate_id} · 当前请求收据</h4>
        {(gate.templates||[]).map((template:Obj)=>{const key=`${gate.gate_id}:${template.template_kind}`,draft=drafts[key]||{conclusion:"pending",evidenceIds:[],factIds:[]};const signerAllowed=role===template.required_role;
          return <div className="intake-template" key={template.template_kind}><div className="panel-actions"><b>{template.template_kind}{template.required_for_gate?" · 必需":" · 辅助材料"}</b><StatusBadge tone={signerAllowed?"amber":"neutral"}>要求角色：{roleLabel[template.required_role]||template.required_role}</StatusBadge></div>
            {template.purpose&&<p className="small-note">{template.purpose}</p>}{signerAllowed?<>
              <div className="governance-form"><label>模板原件<select value={draft.templateArtifactId||""} onChange={event=>setDraft(key,{templateArtifactId:event.target.value})}><option value="">选择已登记 {template.template_kind} 模板</option>{matchingArtifacts(template.template_kind).map((item:Obj)=><option key={item.id} value={item.id}>{item.id} · {item.source_path_hint} · {item.content_hash}</option>)}</select></label>
                <label>模板版本<input value={draft.templateVersion||""} onChange={event=>setDraft(key,{templateVersion:event.target.value})}/></label>
                <label>{gate.gate_id} {template.template_kind} 人工结论<select aria-label={`${gate.gate_id} ${template.template_kind} 人工结论`} value={draft.conclusion||"pending"} onChange={event=>setDraft(key,{conclusion:event.target.value})}><option value="pending">pending · 待核</option><option value="unknown">unknown · 未知</option><option value="pass">pass · 人工确认通过</option><option value="fail">fail · 人工确认不通过</option></select></label>
                <label>有效期起<input type="datetime-local" value={draft.validFrom||""} onChange={event=>setDraft(key,{validFrom:event.target.value})}/></label>
                <label>有效期止<input type="datetime-local" value={draft.validUntil||""} onChange={event=>setDraft(key,{validUntil:event.target.value})}/></label></div>
              <fieldset className="intake-artifacts"><legend>选择本收据所引用的已登记附件</legend>{artifacts.length?artifacts.map((item:Obj)=><label key={item.id}><input type="checkbox" checked={(draft.evidenceIds||[]).includes(item.id)} onChange={event=>setDraft(key,{evidenceIds:event.target.checked?[...(draft.evidenceIds||[]),item.id]:(draft.evidenceIds||[]).filter((id:string)=>id!==item.id)})}/>{item.template_kind||"无模板类别"} · {item.source_path_hint} · {item.content_hash}</label>):<span>尚无已登记附件</span>}</fieldset>
              {gate.gate_id==="G1"&&<fieldset className="intake-artifacts"><legend>法01采纳的当前披露事实</legend>{context.facts.map((fact:Obj)=><label key={fact.id}><input type="checkbox" checked={(draft.factIds||[]).includes(fact.id)} onChange={event=>setDraft(key,{factIds:event.target.checked?[...(draft.factIds||[]),fact.id]:(draft.factIds||[]).filter((id:string)=>id!==fact.id)})}/>{fact.field} · {fact.text} · 来源：{fact.source_ids.join("、")}</label>)}</fieldset>}
              {gate.gate_id==="G2"&&<div className="legal-block"><div><b>本次授权声明（由请求上下文生成）</b><p>{context.g2_authorization_statement}</p><label>组织授权证据<select value={draft.organizationId||""} onChange={event=>setDraft(key,{organizationId:event.target.value})}><option value="">选择已登记组织授权材料</option>{artifacts.map((item:Obj)=><option key={item.id} value={item.id}>{item.template_kind} · {item.source_path_hint} · {item.content_hash}</option>)}</select></label></div></div>}
              {template.technical_template&&<label>匹配的技术证据 {template.technical_template}<select value={draft.technicalId||""} onChange={event=>setDraft(key,{technicalId:event.target.value})}><option value="">选择同请求技术证据</option>{matchingArtifacts(template.technical_template).map((item:Obj)=><option key={item.id} value={item.id}>{item.id} · {item.content_hash}</option>)}</select></label>}
              <Button disabled={working||busy||!draft.templateArtifactId} onClick={()=>saveReceipt(gate,template)}>登记{draft.conclusion||"pending"} 人工收据</Button>
            </>:<p className="small-note">当前角色为 {roleLabel[role||""]||role||"未知"}，只可查看证据与收据；需要 {roleLabel[template.required_role]||template.required_role} 账号签署。</p>}
          </div>})}</div>)}
      {role==="technical_reviewer"&&<div className="intake-isolation"><h4>技术隔离证据（人工测量结果 JSON）</h4><p>上传已经形成的证据，不可在页面内伪造或编辑网络探测、镜像和防火墙结果。新记录将等待法学人员依据同请求 G8 收据确认。</p><label>隔离测量 JSON<input type="file" accept="application/json,.json" onChange={event=>setIsolationFile(event.target.files?.[0]||null)}/></label>
        <Button disabled={working||busy||!isolationFile} onClick={submitIsolation}>登记待法学确认的隔离收据</Button></div>}
      {isolations.map((item:Obj)=><div className="panel-actions" key={item.id}><span>隔离 {item.id} · {item.status} · 技术提交 {item.attested_by}</span>{role==="legal_reviewer"&&item.status==="pending_legal_confirmation"&&<><select aria-label={`${item.id} 选择本人 G8 收据`} value={g8Selection[item.id]||""} onChange={event=>setG8Selection(old=>({...old,[item.id]:event.target.value}))}><option value="">选择本人签署的同请求 G8 通过收据</option>{receipts.filter(receipt=>receipt.gate_id==="G8"&&receipt.conclusion==="pass"&&!receipt.revoked_at&&receipt.confirmed_role==="legal_reviewer"&&receipt.confirmed_by===context?.actor?.actor).map(receipt=><option key={receipt.id} value={receipt.id}>{receipt.id} · {receipt.confirmed_by} · {receipt.confirmed_at}</option>)}</select><button disabled={working||busy||!g8Selection[item.id]} onClick={()=>confirmIsolation(item)}>引用同请求 G8 并确认隔离</button></>}
        {item.evidence_artifact_ids&&Object.keys(item.evidence_artifact_ids).length>0&&<dl className="metadata"><dt>证据绑定</dt><dd>{Object.entries(item.evidence_artifact_ids).map(([field,id])=>`${field}→${id}`).join("；")}</dd></dl>}</div>)}
      <div className="panel-actions"><Button disabled={working||busy} onClick={check}>手动检查当前放行门并刷新任务</Button></div>
      {!receipts.length?<p className="small-note">当前请求尚无门禁收据。</p>:<div className="intake-receipts">{receipts.map((item:Obj)=><div className="panel-actions" key={item.id}><span>{item.gate_id} · {item.template_kind} · {item.conclusion} · {item.confirmed_by}（{item.confirmed_role}）{item.revoked_at?` · 已撤销：${item.revocation_reason}`:""}</span>
        {!item.revoked_at&&["legal_reviewer","approver","admin"].includes(role||"")&&<><input aria-label={`${item.id} 撤销理由`} value={revokeReason[item.id]||""} onChange={event=>setRevokeReason(old=>({...old,[item.id]:event.target.value}))}/><button disabled={working||!revokeReason[item.id]?.trim()} onClick={()=>revoke(item)}>撤销收据</button></>}</div>)}</div>}
    </>}{notice&&<p className="notice" role="status">{notice}</p>}{error&&<p className="error" role="alert">{error}</p>}
  </Panel>;
}

function ReadinessPanel({report,receipts}:{report:Obj|null|undefined;receipts:Obj[]}) {
  const checks=report?.checks&&typeof report.checks==="object"&&!Array.isArray(report.checks)?report.checks:{};
  const legalG9Confirmed=receipts.some(item=>item.gate_id==="G9"&&item.conclusion==="pass"&&!item.revoked_at);
  return <section className="readiness-panel" data-testid="readiness-report" aria-label="放行前置 readiness">
    <div className="readiness-heading"><div><h3>放行前置 readiness</h3><p className="small-note">工程证据与法学 G9 收据分开核验。系统会绑定当前请求、构建清单和证据有效期。</p></div><StatusBadge tone={report?.state==="eligible"?"green":"amber"}>{report?`${report.mode=== "enforced"?"强制":"报告"} · ${report.state==="eligible"?"eligible":"blocked"}`:"blocked · 未生成报告"}</StatusBadge></div>
    <div className="readiness-legal"><b>法学 G9 收据</b><span className={legalG9Confirmed?"readiness-pass":"readiness-pending"}>{legalG9Confirmed?"已确认":"未确认，不能替代工程证据"}</span></div>
    <div className="readiness-list">{readinessKinds.map(kind=>{const item=checks[kind]||{};const status=String(item.status||"pending");const engineering=item.source_kind==="command_generated";const ids=Array.isArray(item.artifact_ids)?item.artifact_ids:[];
      return <div className="readiness-row" key={kind} data-testid={`readiness-${kind}`}><div className="readiness-row-title"><b>{readinessLabel[kind]}</b><StatusBadge tone={status==="pass"?"green":status==="fail"?"red":"amber"}>{readinessStatus[status]||status}</StatusBadge></div><dl className="readiness-details"><dt>责任角色</dt><dd>{readinessRole[kind]}</dd><dt>证据来源</dt><dd>{engineering?"工程证据已生成，只可查看和绑定":"人工上传证据，仍需相应人工收据"}</dd><dt>证据 ID</dt><dd>{ids.length?ids.join("、"):"无"}</dd><dt>有效期止</dt><dd>{item.valid_until||"未设置"}</dd><dt>下一步</dt><dd>{item.reason||"补齐当前请求所需证据并重新检查"}</dd></dl></div>})}</div>
    {report?.source_commit&&<p className="small-note">来源提交 <code>{report.source_commit}</code> · 构建清单 <code>{report.build_manifest_hash||"无"}</code> · 生成于 {report.generated_at||"未知"}</p>}
  </section>;
}

function normalize(value:string|undefined){return (value||"").replace(/\s+/g,"").toUpperCase()}
function sameTuple(left:Obj,right:Obj){return Boolean(left&&right&&left.case_id===right.case_id&&left.purpose===right.purpose&&left.recipient===right.recipient)}
