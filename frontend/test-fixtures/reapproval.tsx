import React, {useState} from "react";
import ReactDOM from "react-dom/client";
import "../src/design-tokens.css";
import "../src/style.css";
import {ReapprovalControl} from "../src/workspaces/ReapprovalControl";
import {RiskWorkspace} from "../src/workspaces/RiskWorkspace";

function Fixture() {
  const params = new URLSearchParams(location.search);
  const [task, setTask] = useState<any>({id:"synthetic-task",status:params.get("status") || "approved",
    transport:"cloud",request_hash:"a".repeat(64),request:{mode:"formal",target:"https://example.invalid",body:{model:"synthetic"}},
    formal_release:{grant:{id:"synthetic-grant"}}, review_status:"cleared",version:1,
    risk:{disposition:"allowed",system_readiness:"ready",completion:"complete",blockers:[],findings:[],attacks:[],gates:[]},
    product_release:{state:"blocked"}});
  const [sent, setSent] = useState("");
  const request = async (path:string, method?:string, body?:any) => {
    if (method !== "POST") return [];
    setSent(JSON.stringify({path,method,body}));
    if (params.get("mode") === "error") throw new Error("模拟服务器拒绝");
    return {status:"review",approval:null};
  };
  const refresh = async () => {
    if (params.get("mode") === "refresh-error") throw new Error("刷新失败");
    setTask((old:any)=>({...old,status:"review",approval:null}));
  };
  return <main style={{maxWidth:760,margin:"24px auto",padding:"0 16px"}}>
    <p className="small-note">合成夹具，不代表真实审批。</p>
    {params.get("workspace") === "1" ? <RiskWorkspace task={task} role={params.get("role") || "approver"}
      runtimeProfile={params.get("profile") || "production"} busy={false} request={request} onRefreshCase={refresh}
      label={s=>s} attackLabels={{}} onAction={()=>{}} onApprove={()=>{}} onResult={()=>{}}
      onRunAttacks={()=>{}} onLegalReview={()=>{}} onTechnicalIssue={()=>{}} onSuccessor={()=>{}}/> :
      <ReapprovalControl task={task} role={params.get("role") || "approver"} runtimeProfile={params.get("profile") || "production"}
        busy={false} request={request} onRefreshCase={refresh}/>}
    {params.get("mode") === "reapprove" && <button onClick={()=>setTask((old:any)=>({...old,status:"approved",formal_release:{grant:{id:"new-synthetic-grant"}}}))}>模拟签发新许可</button>}
    <output data-testid="request">{sent}</output><output data-testid="task-state">{task.status}</output>
  </main>;
}
ReactDOM.createRoot(document.getElementById("root")!).render(<Fixture/>);
