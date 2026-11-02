import React, {useState} from "react";
import ReactDOM from "react-dom/client";
import "../src/design-tokens.css";
import "../src/style.css";
import {V3GradeControl} from "../src/workspaces/V3GradeControl";
import {RiskWorkspace} from "../src/workspaces/RiskWorkspace";

function Fixture() {
  const params = new URLSearchParams(location.search);
  const [task, setTask] = useState<any>({id:"synthetic-task",status:"review",transport:"cloud",
    request_hash:"a".repeat(64),request:{mode:"formal",target:"https://example.invalid",body:{model:"synthetic"}},
    version:1,risk:{disposition:"allowed",system_readiness:"ready",completion:"complete",blockers:[],findings:[],attacks:[],gates:[]},
    review_status:params.get("unreviewed") ? "pending" : "cleared",
    legal_review:params.get("unreviewed") ? null : {id:"synthetic-review"},
    product_release:params.get("no-guard") ? {} : {v3_grade_guard:{state:"blocked"}},
    ...(params.get("old") ? {v3_grade_assessment_id:"old-grade",v3_grade_assessment_request_hash:"b".repeat(64)} : {})});
  const [calls,setCalls] = useState<any[]>([]);
  const request = async (path:string,method?:string,body?:any) => {
    setCalls(old=>[...old,{path,method,body}]);
    if (params.get("error") && path.endsWith("v3-grade-assessment")) throw new Error("模拟拒绝");
    if (params.get("check-error") && path.endsWith("formal-release/check")) throw new Error("模拟检查失败");
    return {id:"synthetic-grade"};
  };
  const refresh = async () => {
    if (params.get("refresh-error")) throw new Error("模拟刷新失败");
    setTask((old:any)=>({...old,v3_grade_assessment_id:"synthetic-grade",v3_grade_assessment_request_hash:old.request_hash}));
  };
  return <main style={{maxWidth:760,margin:"24px auto"}}>
    <p>合成夹具，不代表真实审批。</p>
    {params.get("workspace") ? <RiskWorkspace task={task} role={params.get("role") || "legal_reviewer"}
      runtimeProfile={params.get("profile") || "production"} busy={false} request={request} onRefreshCase={refresh}
      label={s=>s} attackLabels={{}} onAction={()=>{}} onApprove={()=>{}} onResult={()=>{}}
      onRunAttacks={()=>{}} onLegalReview={()=>{}} onTechnicalIssue={()=>{}} onSuccessor={()=>{}}/> :
      <V3GradeControl task={task} role={params.get("role") || "legal_reviewer"}
        runtimeProfile={params.get("profile") || "production"} busy={false} request={request} onRefreshCase={refresh}/>}
    <pre data-testid="calls">{JSON.stringify(calls)}</pre>
  </main>;
}
ReactDOM.createRoot(document.getElementById("root")!).render(<Fixture/>);
