import React from "react";
import ReactDOM from "react-dom/client";
import "../src/design-tokens.css";
import "../src/style.css";
import {GateBundleView} from "../src/workspaces/GateBundleView";
import {RiskWorkspace} from "../src/workspaces/RiskWorkspace";

const kind = new URLSearchParams(location.search).get("case") || "blocked";
const bundle: any = {
  schema_version: 1, authoritative: false, request_hash: "req-synthetic",
  summary_state: "ready_for_approval",
  groups: [
    {id:"G-L",state:"has_blockers",hits:[{gate_id:"G3",message:"服务商复核记录缺失"}]},
    {id:"G-D",state:"has_blockers",hits:[{gate_id:"G8",message:"攻击结果未完成"}]},
    {id:"G-H",state:"not_individually_verified",hits:[]},
    {id:"G-S",state:"not_individually_verified",hits:[]},
  ],
  global_hits: [{gate_id:"G-product",message:"当前请求缺少有效隔离收据"}],
};
if (kind === "empty") {
  bundle.groups = bundle.groups.map((g: any) => ({...g,state:"not_individually_verified",hits:[]}));
  bundle.global_hits = [];
}
if (kind === "malformed") bundle.groups.pop();
const scopeDiagnostics: any = {
  schema_version:1,state:"diagnostic_only",request_hash:"req-synthetic",validated:false,authoritative:false,
  dependencies:{
    G3:{fingerprint:"aaa",missing_dependencies:[],validated:false,authoritative:false},
    G5:{fingerprint:"bbb",missing_dependencies:[],validated:false,authoritative:false},
    G8:{fingerprint:"ccc",missing_dependencies:[],validated:false,authoritative:false},
    G9:{fingerprint:null,missing_dependencies:["deployment_identity"],validated:false,authoritative:false},
  },
  receipt_binding_shadow:[{gate_id:"G5",legacy_binding_matches:false,changed_dependencies:["rules"],validated:false,authoritative:false}],
};
if (kind === "scope-stale") scopeDiagnostics.request_hash = "old-request";
if (kind === "scope-forged") scopeDiagnostics.validated = true;
const task: any = {
  id:"synthetic", status:"review", review_status:"cleared", type:"fact_summary", version:1,
  request_hash:"req-synthetic", transport:"cloud", stale:false,
  request:{mode:"formal",target:"https://example.test",body:{model:"synthetic",messages:[]}},
  risk:{disposition:"allowed",system_readiness:"ready",completion:"complete",blockers:[],findings:[],attacks:[],gates:[]},
  product_release:{state:"blocked",reason:"正式外发待核验",gate_bundle:bundle,scope_diagnostics:scopeDiagnostics},
};
if (kind === "workspace-auto" || kind === "workspace-auto-legal") task.product_release.auto_policy_candidate = true;
const noop = () => {};
const props = {task,busy:false,role:kind === "workspace-auto-legal" ? "legal_reviewer" : "approver",runtimeProfile:"production",label:(s:string)=>s,
  attackLabels:{},request:async()=>[],onRefreshCase:async()=>{},onAction:noop,onApprove:noop,
  onResult:noop,onRunAttacks:noop,onLegalReview:noop,onTechnicalIssue:noop,onSuccessor:noop};
ReactDOM.createRoot(document.getElementById("root")!).render(<main style={{maxWidth:860, margin:"24px auto",padding:"0 12px"}}>
  <p className="small-note">合成 UI 测试数据，不代表正式放行。</p>
  {kind.startsWith("workspace") ? <RiskWorkspace {...props}/> : <GateBundleView bundle={kind === "missing" ? null : bundle}
    scopeDiagnostics={scopeDiagnostics} requestHash={kind === "wrong-hash" ? "other-request" : "req-synthetic"} stale={kind === "stale"}/>}
</main>);
