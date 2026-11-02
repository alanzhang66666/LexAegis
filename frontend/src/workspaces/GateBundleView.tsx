import { ChevronRight } from "lucide-react";

type Hit = {gate_id: string; message?: string; reason_code?: string; status?: string};
type Group = {id: string; state: string; hits: Hit[]};
type GateBundle = {schema_version: number; authoritative: boolean; request_hash: string; groups: Group[]; global_hits: Hit[]};
type ScopeItem = {fingerprint: string | null; missing_dependencies: string[]; validated: false; authoritative: false};
type ScopeReceipt = {gate_id: string; legacy_binding_matches: boolean; changed_dependencies: string[]; validated: false; authoritative: false};
type ScopeDiagnostics = {schema_version: number; state: string; request_hash: string; validated: false; authoritative: false;
  dependencies: Record<string, ScopeItem>; receipt_binding_shadow: ScopeReceipt[]};

const ORDER = ["G-L", "G-D", "G-H", "G-S"] as const;
const LABELS: Record<string, string> = {
  "G-L": "法律与接收方", "G-D": "最小披露与风险",
  "G-H": "请求冻结与审批", "G-S": "网关与部署",
};
const SCOPE_ORDER = ["G3", "G5", "G8", "G9"] as const;
const DEPENDENCY_LABELS: Record<string, string> = {
  materials: "材料版本", rules: "规则版本", task: "任务版本", mapping: "身份映射版本",
  ledger: "累计披露版本", combination: "组合风险版本", deployment_identity: "部署身份",
};

function validHit(value: unknown): value is Hit {
  if (!value || typeof value !== "object") return false;
  const hit = value as Partial<Hit>;
  return typeof hit.gate_id === "string" && hit.gate_id.length > 0 &&
    (hit.message === undefined || typeof hit.message === "string") &&
    (hit.reason_code === undefined || typeof hit.reason_code === "string");
}

function isBundle(value: unknown): value is GateBundle {
  if (!value || typeof value !== "object") return false;
  const bundle = value as Partial<GateBundle>;
  if (bundle.schema_version !== 1 || bundle.authoritative !== false ||
      typeof bundle.request_hash !== "string" || !Array.isArray(bundle.groups) ||
      bundle.groups.length !== ORDER.length || !Array.isArray(bundle.global_hits) ||
      !bundle.global_hits.every(validHit)) return false;
  return ORDER.every(id => {
    const matches = bundle.groups!.filter(group => group?.id === id);
    if (matches.length !== 1 || !Array.isArray(matches[0].hits) || !matches[0].hits.every(validHit)) return false;
    return (matches[0].state === "has_blockers" && matches[0].hits.length > 0) ||
      (matches[0].state === "not_individually_verified" && matches[0].hits.length === 0);
  });
}

function isScopeDiagnostics(value: unknown, requestHash: string): value is ScopeDiagnostics {
  if (!value || typeof value !== "object") return false;
  const scope = value as Partial<ScopeDiagnostics>;
  if (scope.schema_version !== 1 || scope.state !== "diagnostic_only" || scope.request_hash !== requestHash ||
      scope.validated !== false || scope.authoritative !== false || !scope.dependencies ||
      !Array.isArray(scope.receipt_binding_shadow)) return false;
  if (!SCOPE_ORDER.every(id => {
    const item = scope.dependencies![id];
    return item && item.validated === false && item.authoritative === false &&
      (item.fingerprint === null || typeof item.fingerprint === "string") &&
      Array.isArray(item.missing_dependencies) && item.missing_dependencies.every(name => typeof name === "string") &&
      ((item.fingerprint === null && item.missing_dependencies.length > 0) ||
       (typeof item.fingerprint === "string" && item.fingerprint.length > 0 && item.missing_dependencies.length === 0));
  })) return false;
  return scope.receipt_binding_shadow.every(item => item && ["G3", "G5"].includes(item.gate_id) &&
    typeof item.legacy_binding_matches === "boolean" && Array.isArray(item.changed_dependencies) &&
    item.changed_dependencies.every(name => typeof name === "string") &&
    item.legacy_binding_matches === (item.changed_dependencies.length === 0) &&
    item.validated === false && item.authoritative === false);
}

function ScopeDiagnosticsView({value, requestHash}: {value: unknown; requestHash: string}) {
  if (!isScopeDiagnostics(value, requestHash)) return <p className="gate-scope-note">证据版本诊断当前不可用；仍按原有门禁核验。</p>;
  return <details className="gate-bundle-scope">
    <summary>上次检查的证据版本诊断（仅供查看）</summary>
    <p>以下为上次检查的结果；证据变更后请重新检查。指纹只用于提示版本变化，未验证签署、效期或法律适用性，不能作为批准或证据复用依据。</p>
    <ul>{SCOPE_ORDER.map(id => <li key={id}><b>{id}</b> {value.dependencies[id].fingerprint ? "已生成诊断指纹，未经认证" : "诊断信息不完整，未生成指纹"}</li>)}</ul>
    {value.receipt_binding_shadow.length > 0 && <><b>同范围旧收据版本差异</b><ul>
      {value.receipt_binding_shadow.map((item, index) => <li key={`${item.gate_id}-${index}`}>
        {item.gate_id}：{item.legacy_binding_matches ? "版本字段一致，仍需独立核验" : `版本差异：${item.changed_dependencies.map(key => DEPENDENCY_LABELS[key] || key).join("、")}`}
      </li>)}
    </ul></>}
  </details>;
}

/** A diagnostic-only view; it must never drive approval or send controls. */
export function GateBundleView({bundle, scopeDiagnostics, requestHash, stale = false}: {bundle: unknown; scopeDiagnostics?: unknown; requestHash?: string; stale?: boolean}) {
  if (!isBundle(bundle)) return <section className="gate-bundle" aria-label="四门复核概览">
    <h4>四门复核概览</h4><p>当前未取得完整的门禁概览，请重新检查当前请求。</p>
  </section>;
  if (stale || !requestHash || bundle.request_hash !== requestHash) return <section className="gate-bundle" aria-label="四门复核概览">
    <h4>四门复核概览</h4><p role="status">门禁概览与当前请求不一致或已过期，请重新检查当前请求。</p>
  </section>;
  const groups = ORDER.map(id => bundle.groups.find(group => group.id === id)!);
  return <section className="gate-bundle" aria-label="四门复核概览">
    <header><h4>四门复核概览</h4><span>仅供查看，不构成外发批准</span></header>
    <p>以下仅汇总当前返回的阻断项；没有列出阻断项不代表该门已通过。</p>
    <div className="gate-bundle-grid">
      {groups.map(group => <details className="gate-bundle-group" key={group.id}>
        <summary><span><ChevronRight className="gate-bundle-chevron" size={14} aria-hidden="true"/><b>{group.id}</b> {LABELS[group.id]}</span>
          <span className="gate-bundle-state">{group.hits.length ? `待处理 ${group.hits.length} 项` : "未单项验证"}</span></summary>
        {group.hits.length > 0 ? <ul>{group.hits.map((hit, index) => <li key={`${hit.gate_id}-${index}`}>
          <b>{hit.gate_id}</b> {hit.message || hit.reason_code || "需补充核验"}
        </li>)}</ul> : <p>当前未返回该组的阻断明细，仍需按原流程核验。</p>}
      </details>)}
    </div>
    {bundle.global_hits.length > 0 && <div className="gate-bundle-global"><b>其他或全局阻断</b>
      <ul>{bundle.global_hits.map((hit, index) => <li key={`${hit.gate_id}-${index}`}>
        <b>{hit.gate_id}</b> {hit.message || hit.reason_code || "需补充核验"}
      </li>)}</ul></div>}
    <ScopeDiagnosticsView value={scopeDiagnostics} requestHash={requestHash}/>
  </section>;
}
