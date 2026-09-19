import { useEffect, useState } from "react";
import { Download, FlaskConical, Plus, RefreshCw, ServerCog, ShieldAlert, Upload, Users } from "lucide-react";
import { Button, DataTable, Panel, StatusBadge, Tag } from "../components/ui";

type Obj = Record<string, any>;
type RequestFn = (path:string,method?:string,body?:any)=>Promise<any>;

const split = (value:string) => value.split(/[,，\n]/).map(item=>item.trim()).filter(Boolean);
const providerDefault = {
  id:"",name:"",legal_entity:"",product:"",role:"unknown",endpoint:"",model:"",processing_regions:"",retention:"",training_use:"unknown",
  human_access:"unknown",subprocessors:"",subprocessor_status:"unknown",deletion_mechanism:"",
  contract_reference:"",contract_version:"",impact_assessment_reference:"",impact_assessment_version:"",valid_until:"",allowed_tasks:"fact_summary",
  allowed_domains:"labor",allowed_fields:"entity,relation,event,date,amount,evidence",allowed_transports:["cloud"],status:"draft",
};

export function ProviderCenter({providers=[],request,refresh,busy}:{providers?:Obj[];request:RequestFn;refresh:()=>Promise<any>;busy:boolean}) {
  const [form,setForm]=useState<Obj|null>(null);
  const [error,setError]=useState("");
  const save=async()=>{
    if(!form)return;
    try {
      setError("");
      await request("/providers/"+form.id,"PUT",{...form,
        processing_regions:split(form.processing_regions),subprocessors:split(form.subprocessors),
        allowed_tasks:split(form.allowed_tasks),allowed_domains:split(form.allowed_domains),allowed_fields:split(form.allowed_fields),
        valid_until:form.valid_until||null,retention:form.retention||null,deletion_mechanism:form.deletion_mechanism||null,
        legal_entity:form.legal_entity||null,product:form.product||null,endpoint:form.endpoint||null,model:form.model||null,
        contract_reference:form.contract_reference||null,contract_version:form.contract_version||null,
        impact_assessment_reference:form.impact_assessment_reference||null,impact_assessment_version:form.impact_assessment_version||null,
      });setForm(null);await refresh();
    } catch(e){setError((e as Error).message)}
  };
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">服务商档案</div><h1>服务商治理</h1>
      <p>处理角色、地区、留存、训练、人工访问、分包与删除机制均由人员登记，不使用 IP 推断。</p></div>
      <Button variant="primary" onClick={()=>setForm({...providerDefault})}><Plus size={15}/>新建档案</Button></div>
    {!providers.length&&<div className="legal-block"><ShieldAlert/><div><h3>正式外发被阻断</h3><p>尚无经复核的服务商档案。关键字段未知时不会显示为可用。</p></div></div>}
    <div className="governance-grid">{providers.map(provider=><Panel key={provider.id} title={provider.name}
      actions={<StatusBadge tone={provider.status==="reviewed"?"green":"amber"}>{provider.status} · v{provider.profile_version||1}</StatusBadge>}>
      <dl className="metadata"><dt>处理地区</dt><dd>{provider.processing_regions?.join(" / ")||"未知"}</dd>
        <dt>留存</dt><dd>{provider.retention||"未知"}</dd><dt>训练使用</dt><dd>{provider.training_use}</dd>
        <dt>人工访问</dt><dd>{provider.human_access}</dd><dt>分包状态</dt><dd>{provider.subprocessor_status||"unknown"}</dd></dl>
      <div className="panel-actions"><button onClick={()=>setForm({...provider,
        processing_regions:(provider.processing_regions||[]).join(","),subprocessors:(provider.subprocessors||[]).join(","),
        allowed_tasks:(provider.allowed_tasks||[]).join(","),allowed_domains:(provider.allowed_domains||[]).join(","),
        allowed_fields:(provider.allowed_fields||[]).join(",")})}>编辑（复核失效）</button>
        {provider.status==="draft"&&<button onClick={async()=>{await request("/providers/"+provider.id+"/review","POST",{status:"reviewed"});await refresh()}}>具名复核</button>}
        {provider.status==="reviewed"&&<button onClick={async()=>{await request("/providers/"+provider.id+"/review","POST",{status:"expired"});await refresh()}}>标记过期</button>}</div>
    </Panel>)}</div>
    {form&&<Panel title={form.id?"编辑服务商档案":"新建服务商档案"} actions={<button onClick={()=>setForm(null)}>取消</button>}>
      <div className="governance-form">
        {["id","name","legal_entity","product","endpoint","model","processing_regions","retention","deletion_mechanism","contract_reference","contract_version","impact_assessment_reference","impact_assessment_version","valid_until","subprocessors","allowed_tasks","allowed_domains","allowed_fields"].map(key=>
          <label key={key}>{key}<input disabled={key==="id"&&providers.some(p=>p.id===form.id)} value={form[key]||""} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}
        {(["role","training_use","human_access","subprocessor_status"] as const).map(key=><label key={key}>{key}<select value={form[key]}
          onChange={e=>setForm({...form,[key]:e.target.value})}>
          {(key==="role"?["unknown","processor","independent_controller","other"]:key==="training_use"?["unknown","forbidden","allowed"]:
            key==="human_access"?["unknown","forbidden","controlled","allowed"]:["unknown","none","declared"]).map(value=><option key={value}>{value}</option>)}
        </select></label>)}
      </div>{error&&<p className="error">{error}</p>}<Button variant="primary" disabled={busy} onClick={save}>保存为草案</Button>
    </Panel>}
  </div>;
}

const legalFormLabels: Record<string,string> = {
  fa01_source:"法 01 · 来源与人工审查", fa02_authorization:"法 02 · 本次与组织授权",
  fa03_provider:"法 03 · 本账号服务商证据", fa05_rules:"法 05 · 规则签署",
  fa06_annotation:"法 06 · 双人标注与仲裁",
};

export function LegalEvidenceCenter({cases=[],request}:{cases?:Obj[];request:RequestFn}) {
  const realCases=cases.filter(item=>item.mode!=="demo");
  const [caseId,setCaseId]=useState(""),[formType,setFormType]=useState("fa01_source");
  const [file,setFile]=useState<File|null>(null),[items,setItems]=useState<Obj[]>([]);
  const [notes,setNotes]=useState<Record<string,string>>({}),[basis,setBasis]=useState<Record<string,string>>({});
  const [error,setError]=useState(""),[busy,setBusy]=useState(false);
  useEffect(()=>{if(!caseId&&realCases.length)setCaseId(realCases[0].id)},[cases,caseId]);
  useEffect(()=>{
    if(!caseId){setItems([]);return}
    request(`/cases/${caseId}/legal-evidence`).then(setItems).catch(e=>setError((e as Error).message));
  },[caseId]);
  const reload=async()=>{if(caseId)setItems(await request(`/cases/${caseId}/legal-evidence`))};
  const upload=async()=>{
    if(!caseId||!file)return;
    setBusy(true);setError("");
    try{
      const body=new FormData();body.append("form_type",formType);body.append("file",file);
      await request(`/cases/${caseId}/legal-evidence`,"POST",body);
      setFile(null);await reload();
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  const assess=async(item:Obj,status:"needs_correction"|"evidence_checked")=>{
    setBusy(true);setError("");
    try{
      await request(`/cases/${caseId}/legal-evidence/${item.id}/assessment`,"PUT",{
        status,findings:status==="needs_correction"?split(notes[item.id]||""):[],
        basis_references:split(basis[item.id]||""),
      });if(status==="evidence_checked")setNotes(previous=>({...previous,[item.id]:""}));
      await reload();
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">受控材料</div><h1>法学证据登记</h1>
      <p>上传表格后系统只记录原件与 SHA-256。核验结论在此留痕；门禁通过仍由对应运行回执判断。</p></div></div>
    <div className="legal-block"><ShieldAlert/><div><h3>默认保持外发阻断</h3>
      <p>“已收到”或“证据已核齐”不会把服务商改为 reviewed、规则改为 published，也不会批准请求。</p></div></div>
    {!realCases.length?<Panel title="暂无正式案件"><p>先在案件工作台建立正式案件，再登记法学表格。</p></Panel>:<>
      <Panel title="上传已填写表格"><div className="governance-form">
        <label>对应案件<select value={caseId} onChange={e=>setCaseId(e.target.value)}>{realCases.map(item=><option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></label>
        <label>表格类别<select value={formType} onChange={e=>setFormType(e.target.value)}>{Object.entries(legalFormLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <label>DOCX 原件<input type="file" accept=".docx" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
      </div><Button variant="primary" disabled={!file||busy} onClick={upload}>上传并计算哈希</Button></Panel>
      {items.map(item=><Panel key={item.id} title={legalFormLabels[item.form_type]||item.form_type}
        actions={<StatusBadge tone={item.status==="evidence_checked"?"green":"amber"}>{item.status==="received_unverified"?"待核验":item.status==="needs_correction"?"待补正":"证据已核齐"}</StatusBadge>}>
        <p>{item.name} · SHA-256：<code>{item.sha256}</code></p>
        <p>上传：{item.uploaded_by} · {item.uploaded_at}；核验：{item.assessed_by||"尚无"}。门禁通过：否。</p>
        {!!item.findings?.length&&<p>待补项：{item.findings.join("；")}</p>}
        <div className="governance-form">
          <label>待补问题（一行一项）<textarea rows={3} value={notes[item.id]??item.findings?.join("\n")??""} onChange={e=>setNotes({...notes,[item.id]:e.target.value})}/></label>
          <label>证据位置/哈希或系统回执（一行一项）<textarea rows={3} value={basis[item.id]??item.basis_references?.join("\n")??""} onChange={e=>setBasis({...basis,[item.id]:e.target.value})}/></label>
        </div><div className="panel-actions">
          <button onClick={()=>assess(item,"needs_correction")} disabled={busy}>记录待补正</button>
          <button onClick={()=>assess(item,"evidence_checked")} disabled={busy}>证据已核齐</button>
          <a href={`/api/v1/cases/${caseId}/legal-evidence/${item.id}/file`}>下载受控原件</a>
        </div>
      </Panel>)}
    </>}
    {error&&<p className="error">{error}</p>}
  </div>;
}

const protocolDefault={id:"",kind:"identity",version:"1.0",status:"draft",attacker_view:["wire_payload"],
  auxiliary_data:[],query_budget:3,time_budget_seconds:30,success_criteria:{operator:"gte",metric:"attack_score"},
  threshold:.5,random_seed:23,content_hash:null};

export function BenchmarkCenter({protocols=[],request,refresh}:{protocols?:Obj[];request:RequestFn;refresh:()=>Promise<any>}) {
  const [form,setForm]=useState<Obj|null>(null);
  const frozen=protocols.filter(item=>item.status==="frozen").length;
  const save=async()=>{if(!form)return;await request("/risk-protocols/"+form.id,"PUT",form);setForm(null);await refresh()};
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">隔离研究</div><h1>隔离实验与风险协议</h1>
      <p>生产攻击协议与 Ianvs 离线实验分轨运行，均不挂载原文和 mapping。</p></div>
      <Button variant="primary" onClick={()=>setForm({...protocolDefault})}><Plus size={15}/>新建协议</Button></div>
    <div className="legal-block"><ShieldAlert/><div><h3>不进入生产 dispatch</h3><p>已冻结攻击协议 {frozen} 项；四类是否齐备由具体案由包的版本引用决定。</p></div></div>
    <DataTable rowKey={row=>row.id} rows={protocols} columns={[
      {key:"id",label:"协议"},{key:"kind",label:"攻击类型"},{key:"version",label:"版本"},
      {key:"status",label:"状态",render:row=><Tag tone={row.status==="frozen"?"green":"amber"}>{row.status}</Tag>},
      {key:"action",label:"操作",render:row=><button onClick={()=>setForm({...row})} disabled={row.status==="frozen"}>编辑</button>},
    ]}/>
    {form&&<Panel title="风险协议"><div className="governance-form">
      <label>协议 id<input value={form.id} onChange={e=>setForm({...form,id:e.target.value})}/></label>
      <label>类型<select value={form.kind} onChange={e=>setForm({...form,kind:e.target.value})}>
        {["identity","candidate_set","sensitive_inference","cross_round"].map(value=><option key={value}>{value}</option>)}</select></label>
      <label>版本<input value={form.version} onChange={e=>setForm({...form,version:e.target.value})}/></label>
      <label>阈值<input type="number" step=".01" min="0" max="1" value={form.threshold} onChange={e=>setForm({...form,threshold:Number(e.target.value)})}/></label>
      <label>查询预算<input type="number" value={form.query_budget} onChange={e=>setForm({...form,query_budget:Number(e.target.value)})}/></label>
      <label>时间预算（秒）<input type="number" value={form.time_budget_seconds} onChange={e=>setForm({...form,time_budget_seconds:Number(e.target.value)})}/></label>
      <label>随机种子<input type="number" value={form.random_seed} onChange={e=>setForm({...form,random_seed:Number(e.target.value)})}/></label>
      <label>保存状态<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option value="draft">draft</option><option value="frozen">frozen</option></select></label>
    </div><div className="panel-actions"><Button variant="primary" onClick={save}>保存</Button><button onClick={()=>setForm(null)}>取消</button></div></Panel>}
    <Panel title="ianvs-pipl profile"><code>lexaegis bench --profile ianvs-pipl --input input.json --output report.json</code>
      <p>必须提供真实向量及生成器哈希；模型攻击缺真实输出时返回 not_applicable，常量指标返回 uncertain。</p></Panel>
  </div>;
}

export function UserCenter({request}:{request:RequestFn}) {
  const [usersList,setUsers]=useState<Obj[]>([]),[error,setError]=useState("");
  const [form,setForm]=useState({username:"",display_name:"",role:"case_operator",password:""});
  const load=()=>request("/users").then(setUsers).catch(e=>setError(e.message));
  useEffect(()=>{load()},[]);
  const create=async()=>{try{setError("");await request("/users","POST",form);setForm({username:"",display_name:"",role:"case_operator",password:""});load()}catch(e){setError((e as Error).message)}};
  return <div className="content governance-page"><div className="section-heading"><div><div className="eyebrow">本地账号</div>
    <h1>本地用户与角色</h1><p>账户只保存在当前实例；角色变更与停用在下一请求立即生效。</p></div><Users/></div>
    <DataTable rowKey={row=>row.id} rows={usersList} columns={[{key:"display_name",label:"人员"},{key:"username",label:"用户名"},
      {key:"role",label:"角色",render:row=><select aria-label={`${row.username} 的角色`} value={row.role}
        onChange={async event=>{try{await request("/users/"+row.username,"PUT",{role:event.target.value});load()}catch(e){setError((e as Error).message)}}}>
        {["admin","case_operator","technical_reviewer","legal_reviewer","approver"].map(value=><option key={value}>{value}</option>)}</select>},
      {key:"status",label:"状态",render:row=><Tag tone={row.status==="active"?"green":"amber"}>{row.status}</Tag>},
      {key:"action",label:"操作",render:row=><button disabled={row.username==="admin"} onClick={async()=>{try{
        await request("/users/"+row.username,"PUT",{status:row.status==="active"?"disabled":"active"});load()
      }catch(e){setError((e as Error).message)}}}>{row.status==="active"?"停用":"启用"}</button>}]}/>
    <Panel title="创建本地账户"><div className="governance-form">
      <label>用户名<input value={form.username} onChange={e=>setForm({...form,username:e.target.value})}/></label>
      <label>显示名称<input value={form.display_name} onChange={e=>setForm({...form,display_name:e.target.value})}/></label>
      <label>角色<select value={form.role} onChange={e=>setForm({...form,role:e.target.value})}>
        {["admin","case_operator","technical_reviewer","legal_reviewer","approver"].map(value=><option key={value}>{value}</option>)}</select></label>
      <label>初始口令<input type="password" minLength={12} value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></label>
    </div>{error&&<p className="error">{error}</p>}<Button variant="primary" onClick={create}>创建账户</Button></Panel>
  </div>;
}

const runtimePackBase="/formal-release/runtime-packs";
const runtimeRiskKinds=["entity","density","context","combination","cross_round"] as const;
const firstAcceptanceScope={case_id:"LA-001",purpose:"R_fact_summary",recipient:"D_DeepSeek_official_API"};
type ReviewDraft={reviewRecord:string;evidenceId:string;caseId:string;recipient:string;dispatchAllowed:boolean;
  weights:Record<string,string>;references:string;retireReason:string};
const emptyReviewDraft=():ReviewDraft=>({reviewRecord:"",evidenceId:"",caseId:"",recipient:"",dispatchAllowed:false,
  weights:Object.fromEntries(runtimeRiskKinds.map(key=>[key,""])),references:"",retireReason:""});
const law05Kinds=new Set(["法05","法05_门5_规则发布法学签署","法 05 · 门 5 · 劳动争议 V2 规则发布的法学签署"]);

export function RuntimePackWorkflow({cases,providers=[],runtimeConfig={},request,role}:{cases:Obj[];providers?:Obj[];runtimeConfig?:Obj;request:RequestFn;role?:string}) {
  const [records,setRecords]=useState<Obj[]>([]),[activations,setActivations]=useState<Obj[]>([]),[artifacts,setArtifacts]=useState<Obj[]>([]);
  const [scopeKind,setScopeKind]=useState(""),[sourceFile,setSourceFile]=useState<File|null>(null),[reportFile,setReportFile]=useState<File|null>(null),[evidenceFile,setEvidenceFile]=useState<File|null>(null);
  const [forms,setForms]=useState<Record<string,ReviewDraft>>({}),[error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false);
  const canPrepare=role==="admin"||role==="technical_reviewer",canReview=role==="legal_reviewer",canRetire=role==="legal_reviewer"||role==="admin";
  const providerId=runtimeConfig.cloud_primary?.provider_id||runtimeConfig.provider_id||"";
  const canUploadEvidence=canPrepare||canReview||role==="approver";
  const legalArtifacts=artifacts.filter(item=>law05Kinds.has(item.template_kind));
  const load=async()=>{
    if(role==="case_operator")return;
    const [runtime,evidence]=await Promise.all([request(runtimePackBase),request("/formal-release")]);
    setRecords(runtime.packs||[]);setActivations(runtime.activations||[]);setArtifacts(evidence.artifacts||[]);
  };
  useEffect(()=>{load().catch(e=>setError((e as Error).message))},[role]);
  const updateForm=(id:string,updates:Partial<ReviewDraft>)=>setForms(old=>({...old,[id]:{...emptyReviewDraft(),...old[id],...updates}}));
  const prepare=async()=>{
    if(!sourceFile||!reportFile||!scopeKind) return;
    setBusy(true);setError("");setNotice("");
    try{
      const sourcePack=JSON.parse(await sourceFile.text());
      if(!sourcePack||Array.isArray(sourcePack)||typeof sourcePack!=="object")throw new Error("规则文件必须是 JSON 对象。");
      const importReport=JSON.parse(await reportFile.text());
      if(!importReport||Array.isArray(importReport)||typeof importReport!=="object")throw new Error("导入报告必须是 JSON 对象。");
      const created=await request(runtimePackBase,"POST",{source_pack:sourcePack,import_report:importReport,scope_kind:scopeKind});
      setScopeKind("");setSourceFile(null);setReportFile(null);await load();setNotice(`已保存规则草稿 ${created.id}；仍需法05证据及法学复核，当前不会授权任务发送。`);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  const uploadEvidence=async()=>{
    if(!evidenceFile)return;
    setBusy(true);setError("");setNotice("");
    try{const body=new FormData();body.append("file",evidenceFile);
      const result=await request("/formal-release/evidence?template_kind=%E6%B3%9505","POST",body);
      setEvidenceFile(null);await load();setNotice(`已登记法05证据 ${result.id}（SHA-256 ${result.content_hash}）；尚未形成审核结论。`);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  const review=async(pack:Obj)=>{
    const form={...emptyReviewDraft(),...forms[pack.id]};
    const isFirst=(pack.scope_kind||"first_acceptance")==="first_acceptance";
    const publishedScope=isFirst?firstAcceptanceScope:{...(form.caseId?{case_id:form.caseId}:{domain:pack.pack?.domain_id||pack.pack?.id||"labor"}),
      purpose:"R_fact_summary",recipient:form.recipient||providerId};
    const references=split(form.references);
    const weights=Object.fromEntries(runtimeRiskKinds.map(key=>[key,Number(form.weights[key])]));
    if(!form.reviewRecord.trim()||!form.evidenceId||!references.length||!form.dispatchAllowed||(!isFirst&&!publishedScope.recipient)||
       Object.values(form.weights).some(value=>value===""||!Number.isFinite(Number(value))||Number(value)<0||Number(value)>1)){
      setError("请完整填写具名复核记录、法05证据、案由/任务范围、五类风险权重和法源，并明确勾选发布授权。");return}
    setBusy(true);setError("");setNotice("");
    try{await request(`${runtimePackBase}/${encodeURIComponent(pack.id)}/review`,"POST",{
      review_record:form.reviewRecord.trim(),law_05_evidence_id:form.evidenceId,published_scope:publishedScope,
      risk_weights:weights,references,dispatch_allowed:form.dispatchAllowed});
      await load();setNotice("法学复核记录已冻结为 reviewed 草稿。该步骤尚未发布或激活；请再次核对后另行发布。");
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  const publish=async(pack:Obj)=>{
    if(!window.confirm("确认发布并激活此已复核规则运行包？发布不批准任何具体请求或外发。"))return;
    setBusy(true);setError("");setNotice("");
    try{const result=await request(`${runtimePackBase}/${encodeURIComponent(pack.id)}/publish`,"POST",{});
      await load();setNotice(`运行规则已发布并激活：${result.active_pack?.id||result.runtime_pack?.id}。具体请求仍须独立复核、策略核验和审批。`);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  const retire=async(pack:Obj)=>{
    const reason=forms[pack.id]?.retireReason?.trim();if(!reason){setError("退役前请填写原因。");return}
    setBusy(true);setError("");setNotice("");
    try{await request(`${runtimePackBase}/${encodeURIComponent(pack.id)}/retire`,"POST",{reason});await load();setNotice("运行规则已登记退役；历史版本和激活记录保留。")}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  return <section className="runtime-pack-workflow" aria-label="正式运行规则发布流程">
    <div className="legal-block"><ShieldAlert/><div><h3>规则发布不是发送批准</h3><p>准备、法学复核和发布/激活分为独立操作；发布只使规则进入后续门禁。每个请求仍需单独策略、风险复核、审批和一次性许可。</p></div></div>
    {canPrepare&&<Panel title="准备运行规则草稿"><div className="governance-form">
      <label>明确适用范围<select value={scopeKind} onChange={event=>setScopeKind(event.target.value)}><option value="">请选择范围</option><option value="request">常规：指定正式案件和接收方</option><option value="first_acceptance">首个验收：LA-001 固定范围</option></select></label>
      <label>案由规则 JSON<input type="file" accept="application/json,.json" onChange={event=>setSourceFile(event.target.files?.[0]||null)}/></label>
      <label>对应导入核验报告 JSON<input type="file" accept="application/json,.json" onChange={event=>setReportFile(event.target.files?.[0]||null)}/></label>
    </div><p className="small-note">系统按规范化 JSON 内容计算 SHA-256，并保存对应导入报告；导出文件用于构建清单绑定。系统不自动校正规则、不签署法律结论，也不勾选外发授权。</p>
      <Button variant="primary" disabled={busy||!scopeKind||!sourceFile||!reportFile} onClick={prepare}>保存为运行库草稿</Button></Panel>}
    {canUploadEvidence&&<Panel title="登记法05复核签署材料"><div className="governance-form">
      <label>法05签署文件<input type="file" accept=".docx,.pdf,.txt,.png,.jpg,.jpeg" onChange={event=>setEvidenceFile(event.target.files?.[0]||null)}/></label>
    </div><p className="small-note">上传只登记受控原件与哈希，不代表已核验；须在具体规则草稿中引用后才能复核。</p>
      <Button variant="primary" disabled={busy||!evidenceFile} onClick={uploadEvidence}><Upload size={15}/>登记法05证据</Button></Panel>}
    <div className="panel-actions"><h2 className="subheading">运行规则草稿与发布记录</h2><button disabled={busy} onClick={()=>load().catch(e=>setError((e as Error).message))}><RefreshCw size={14}/>刷新</button></div>
    {!records.length?<Panel title="暂无运行规则草稿"><p>准备草稿不会更改案由规则；已激活规则需具备具名法学复核和法05证据。</p></Panel>:records.map(pack=>{
      const form={...emptyReviewDraft(),...forms[pack.id]};const first=(pack.scope_kind||"first_acceptance")==="first_acceptance";
      const packEvidence=legalArtifacts.find(item=>item.id===pack.law_05_evidence_id);
      return <Panel key={pack.id} title={`${pack.source_pack_id||pack.id}`} actions={<StatusBadge tone={pack.status==="published"?"green":pack.status==="reviewed"?"amber":"neutral"}>{pack.status||"draft"}</StatusBadge>}>
        <dl className="metadata"><dt>运行规则 ID</dt><dd><code>{pack.id}</code></dd><dt>源规则哈希</dt><dd><code>{pack.source_pack_hash}</code></dd>
          <dt>导入报告哈希</dt><dd><code>{pack.import_report_hash}</code></dd><dt>当前外发授权</dt><dd>{pack.dispatch_allowed===true?"已由法学复核明确授权（仍不等于请求批准）":"未授权"}</dd>
          {pack.law_05_evidence_id&&<><dt>法05证据</dt><dd>{pack.law_05_evidence_id} · {packEvidence?.content_hash||pack.law_05_evidence_hash||"哈希未回显"}</dd></>}
          {pack.published_scope&&<><dt>适用范围</dt><dd>{[pack.published_scope.case_id,pack.published_scope.domain,pack.published_scope.purpose,pack.published_scope.recipient].filter(Boolean).join(" · ")}</dd></>}
          {pack.reviewer&&<><dt>法学复核</dt><dd>{pack.reviewer} · {pack.reviewed_at}</dd></>}
        </dl>
        <div className="panel-actions"><a href={`/api/v1${runtimePackBase}/${encodeURIComponent(pack.id)}/export`}><Download size={14}/>导出 JSON</a>
          {canReview&&pack.status==="draft"&&<button onClick={()=>updateForm(pack.id,{})}>填写法学复核</button>}
          {canReview&&pack.status==="reviewed"&&<button className="primary" disabled={busy} onClick={()=>publish(pack)}>发布并激活规则</button>}</div>
        {canReview&&pack.status==="draft"&&<div className="runtime-review-form">
          <h4>法学人员复核</h4><label>具名复核意见<textarea rows={3} value={form.reviewRecord} onChange={event=>updateForm(pack.id,{reviewRecord:event.target.value})}/></label>
          <label>引用已登记法05证据<select value={form.evidenceId} onChange={event=>updateForm(pack.id,{evidenceId:event.target.value})}><option value="">请选择已登记证据</option>
            {legalArtifacts.map(item=><option key={item.id} value={item.id}>{item.id} · {item.source_path_hint||item.template_kind} · {item.content_hash}</option>)}</select></label>
          {first?<p className="small-note">首个验收范围固定为 LA-001 · R_fact_summary · D_DeepSeek_official_API。该范围由规则固定，不可在页面扩展。</p>:<div className="governance-form">
            <label>适用服务商档案<select value={form.recipient||providerId} onChange={event=>updateForm(pack.id,{recipient:event.target.value})}><option value="">请选择实际服务商档案</option>
              {providers.map(item=><option key={item.id} value={item.id}>{item.name||item.id} · {item.id}{item.status!=="reviewed"?` · ${item.status}`:""}</option>)}</select></label>
            <label>可选的单案限制<select value={form.caseId} onChange={event=>updateForm(pack.id,{caseId:event.target.value})}><option value="">全部符合条件的 labor 案件（逐案门禁仍适用）</option>
              {cases.map(item=><option key={item.id} value={item.id}>{item.name} · {item.reference_code||item.id}</option>)}</select></label>
            <label>发布范围<input value={`${form.caseId?`案件 ${form.caseId}`:(pack.pack?.domain_id||pack.pack?.id||"labor")} · R_fact_summary · ${form.recipient||providerId||"待选择服务商档案"}`} readOnly/></label>
          </div>}
          {!first&&<p className="small-note">该规则可供同案由的正式案件复用；可额外锁定单案。接收方必须是服务商档案中的实际 provider ID，不能用“primary”代表通配。具体请求正文、逐案复核和审批仍由各请求独立门禁核验。</p>}
          <div className="governance-form runtime-weights">{runtimeRiskKinds.map(key=><label key={key}>{({entity:"主体识别",density:"信息密度",context:"上下文识别",combination:"组合风险",cross_round:"跨轮次风险"} as Record<string,string>)[key]}
            <input type="number" min="0" max="1" step="0.01" value={form.weights[key]} onChange={event=>updateForm(pack.id,{weights:{...form.weights,[key]:event.target.value}})}/></label>)}</div>
          <label>法源/依据引用（一行一项）<textarea rows={2} value={form.references} onChange={event=>updateForm(pack.id,{references:event.target.value})}/></label>
          <label className="confirm-line"><input type="checkbox" checked={form.dispatchAllowed} onChange={event=>updateForm(pack.id,{dispatchAllowed:event.target.checked})}/>
            我已完成法学核验，并明确允许该规则在所列范围进入后续门禁</label>
          <p className="small-note">此处授权仅供下游门禁评估，不批准某个请求，不签发一次性许可。</p>
          <Button variant="primary" disabled={busy} onClick={()=>review(pack)}>保存法学复核（不发布）</Button>
        </div>}
        {canRetire&&pack.status==="published"&&<div className="panel-actions"><label>退役原因<input value={form.retireReason} onChange={event=>updateForm(pack.id,{retireReason:event.target.value})}/></label>
          <button className="danger-text" disabled={busy||!form.retireReason.trim()} onClick={()=>retire(pack)}>登记退役</button></div>}
      </Panel>;
    })}
    {activations.length>0&&<Panel title="激活记录（只读）"><DataTable rowKey={row=>row.id} rows={activations} columns={[
      {key:"pack_id",label:"工作台规则包"},{key:"runtime_pack_id",label:"源运行库"},{key:"runtime_pack_hash",label:"内容哈希"},{key:"actor_user_id",label:"操作人"},{key:"activated_at",label:"激活时间"},
    ]}/></Panel>}
    {notice&&<p className="notice" role="status">{notice}</p>}{error&&<p className="error" role="alert">{error}</p>}
  </section>;
}

export function LegalPackCenter({packs=[],tasks=[],cases=[],providers=[],runtimeConfig={},request,runtimeProfile,role}:{packs?:Obj[];tasks?:Obj[];cases?:Obj[];providers?:Obj[];runtimeConfig?:Obj;request:RequestFn;runtimeProfile?:string;role?:string}) {
  const [reports,setReports]=useState<Record<string,Obj>>({});
  const realCases=cases.filter(item=>item.mode!=="demo"&&item.runtime_profile!=="demo");
  return <div className="content governance-page"><div className="section-heading"><div><div className="eyebrow">可扩展设计</div>
    <h1>法学规则中心</h1><p>规则草稿、具名法学复核与正式发布分步完成；未发布规则始终阻断外发。</p></div><ServerCog/></div>
    {runtimeProfile==="production"&&<RuntimePackWorkflow cases={realCases} providers={providers} runtimeConfig={runtimeConfig} request={request} role={role}/ >}
    <h2 className="subheading">任务能力</h2><div className="capability-grid">{tasks.map(task=><Panel key={task.id} title={task.name}>
      <StatusBadge tone={task.status==="available"||task.available?"green":"neutral"}>{task.status||"unimplemented"}</StatusBadge>
      <p>{task.id} · {task.version}</p></Panel>)}</div>
    <h2 className="subheading">案由知识包</h2>{packs.map(pack=>{
      const fields=(pack.fact_fields||[]).map((field:any)=>typeof field==="string"?field:field.id);
      const expected=Math.max(1,(pack.task_ids||[]).length*fields.length);
      const matrix=Math.round(((pack.task_field_matrix||[]).length/expected)*100);
      const blockers=[pack.status!=="published"&&"规则未发布",pack.legal_status!=="reviewed"&&"法学状态待审",
        !pack.dispatch_allowed&&"正式外发未授权",!(pack.risk_protocols||[]).length&&"未绑定攻击协议"].filter(Boolean);
      return <Panel key={pack.id} title={pack.name} actions={<Tag tone={pack.status==="published"?"green":"amber"}>{pack.status}</Tag>}>
        <dl className="metadata"><dt>版本</dt><dd>{pack.version}</dd><dt>字段矩阵</dt><dd>{matrix}%（只表示结构完成度）</dd>
          <dt>法学发布</dt><dd>{pack.legal_status||"pending_legal_review"}</dd><dt>攻击协议</dt><dd>{(pack.risk_protocols||[]).length} 项引用</dd></dl>
        <div className="blocker-list">{blockers.map(String).map(item=><span className="blocker" key={item}><ShieldAlert size={13}/>{item}</span>)}</div>
        <div className="panel-actions"><button onClick={async()=>setReports({...reports,[pack.id]:await request("/packs/"+pack.id+"/validate","POST")})}>校验结构与合成回归</button></div>
        {reports[pack.id]&&<pre>{JSON.stringify(reports[pack.id],null,2)}</pre>}
      </Panel>})}
  </div>;
}
