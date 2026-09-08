import { useEffect, useState } from "react";
import { FlaskConical, Plus, ServerCog, ShieldAlert, Users } from "lucide-react";
import { Button, DataTable, Panel, StatusBadge, Tag } from "../components/ui";

type Obj = Record<string, any>;
type RequestFn = (path:string,method?:string,body?:any)=>Promise<any>;

const split = (value:string) => value.split(/[,，\n]/).map(item=>item.trim()).filter(Boolean);
const providerDefault = {
  id:"",name:"",role:"unknown",processing_regions:"",retention:"",training_use:"unknown",
  human_access:"unknown",subprocessors:"",subprocessor_status:"unknown",deletion_mechanism:"",
  contract_reference:"",impact_assessment_reference:"",valid_until:"",allowed_tasks:"fact_summary",
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
        contract_reference:form.contract_reference||null,impact_assessment_reference:form.impact_assessment_reference||null,
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
        {["id","name","processing_regions","retention","deletion_mechanism","contract_reference","impact_assessment_reference","valid_until","subprocessors","allowed_tasks","allowed_domains","allowed_fields"].map(key=>
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
        {["admin","case_operator","legal_reviewer","approver"].map(value=><option key={value}>{value}</option>)}</select>},
      {key:"status",label:"状态",render:row=><Tag tone={row.status==="active"?"green":"amber"}>{row.status}</Tag>},
      {key:"action",label:"操作",render:row=><button disabled={row.username==="admin"} onClick={async()=>{try{
        await request("/users/"+row.username,"PUT",{status:row.status==="active"?"disabled":"active"});load()
      }catch(e){setError((e as Error).message)}}}>{row.status==="active"?"停用":"启用"}</button>}]}/>
    <Panel title="创建本地账户"><div className="governance-form">
      <label>用户名<input value={form.username} onChange={e=>setForm({...form,username:e.target.value})}/></label>
      <label>显示名称<input value={form.display_name} onChange={e=>setForm({...form,display_name:e.target.value})}/></label>
      <label>角色<select value={form.role} onChange={e=>setForm({...form,role:e.target.value})}>
        {["admin","case_operator","legal_reviewer","approver"].map(value=><option key={value}>{value}</option>)}</select></label>
      <label>初始口令<input type="password" minLength={12} value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></label>
    </div>{error&&<p className="error">{error}</p>}<Button variant="primary" onClick={create}>创建账户</Button></Panel>
  </div>;
}

export function LegalPackCenter({packs=[],tasks=[],request}:{packs?:Obj[];tasks?:Obj[];request:RequestFn}) {
  const [reports,setReports]=useState<Record<string,Obj>>({});
  return <div className="content governance-page"><div className="section-heading"><div><div className="eyebrow">可扩展设计</div>
    <h1>法学规则中心</h1><p>技术结构可继续建设；未发布的法学规则始终保持正式外发阻断。</p></div><ServerCog/></div>
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
