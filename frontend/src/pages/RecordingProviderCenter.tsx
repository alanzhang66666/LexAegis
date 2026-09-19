import { useState } from "react";
import { Panel, Tag } from "../components/ui";
import type { RecordingProvider } from "../recordingProviders";
const labels = {name:"档案名称",model:"模型名称",endpoint:"API 根地址",purpose:"处理目的",regions:"处理地区",retention:"留存约定",notes:"复核备注"};
export function RecordingProviderCenter({providers,onSave}:{providers:RecordingProvider[];onSave:(rows:RecordingProvider[])=>void}) {
  const [draft,setDraft]=useState<RecordingProvider|null>(null);
  const [notice,setNotice]=useState("");
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">服务商档案</div><h1>服务商治理</h1>
      <p>维护模型服务、处理范围和复核备注，供运行配置选择。</p></div>
      <button className="primary" onClick={()=>setDraft({id:crypto.randomUUID(),name:"",model:"",endpoint:"",purpose:"",regions:"",retention:"",notes:"",status:"页面已配置"})}>新建档案</button></div>
    <div className="governance-grid">{providers.map(provider=><Panel key={provider.id} title={provider.name} actions={<Tag tone="green">已配置 · 1.0</Tag>}>
      <dl className="metadata"><dt>模型</dt><dd>{provider.model||"未填写"}</dd><dt>处理目的</dt><dd>{provider.purpose||"未填写"}</dd>
        <dt>API 地址</dt><dd>••••••••••••••••</dd><dt>处理地区</dt><dd>{provider.regions||"未填写"}</dd><dt>留存约定</dt><dd>{provider.retention||"未填写"}</dd>
        <dt>复核备注</dt><dd>{provider.notes||"未填写"}</dd></dl>
      <button onClick={()=>{setNotice("");setDraft({...provider});}}>查看与编辑档案</button>
    </Panel>)}</div>
    {draft&&<Panel title="编辑服务商档案"><form onSubmit={event=>{event.preventDefault();onSave([...providers.filter(row=>row.id!==draft.id),draft]);setDraft(null);setNotice("页面档案已保存，可在运行配置中选择。");}}>
      <div className="governance-form">{Object.entries(labels).map(([key,label])=><label key={key}>{label}<input required={key==="name"} type={key==="endpoint"?"password":"text"} autoComplete="off" value={draft[key as keyof typeof labels]} onChange={event=>setDraft({...draft,[key]:event.target.value})}/></label>)}</div>
      <div className="panel-actions"><button type="submit" className="primary">保存档案</button><button type="button" onClick={()=>setDraft(null)}>取消</button></div>
    </form></Panel>}
    {notice&&<p role="status">{notice}</p>}
  </div>;
}
