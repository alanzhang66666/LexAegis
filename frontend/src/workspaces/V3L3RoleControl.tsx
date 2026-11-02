import { useEffect, useRef, useState } from "react";

type Obj = Record<string, any>;
type RequestFn = (path: string, method?: string, body?: any) => Promise<any>;

/** A role action is not a release approval or a PIA/CTIA determination. */
export function V3L3RoleControl({task, role, runtimeProfile, busy, request, onRefreshCase}:{
  task: Obj; role?: string; runtimeProfile?: string; busy: boolean;
  request: RequestFn; onRefreshCase: () => Promise<void>;
}) {
  const [working, setWorking] = useState(false);
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  useEffect(() => { setDone(false); setMessage(""); setError(""); }, [task.id, task.request_hash]);
  const guard = task.product_release?.v3_grade_guard;
  const roles = guard?.l3_roles;
  if (runtimeProfile !== "production" || !["legal_reviewer", "approver"].includes(role || "")
      || task.status !== "review" || task.request?.mode !== "formal" || task.transport !== "cloud"
      || !task.request_hash || guard?.grade !== "L3" || !roles) return null;
  const organizationRole = role === "legal_reviewer" ? "legal_partner" : "data_protection_officer";
  const recorded = Boolean(roles[organizationRole]);
  const submit = async () => {
    if (busy || working || done || recorded || roles.state === "unconfigured" || inFlight.current) return;
    inFlight.current = true; setWorking(true); setMessage(""); setError("");
    try {
      await request(`/tasks/${encodeURIComponent(task.id)}/v3-l3-role-action`, "POST", {
        request_hash: task.request_hash, organization_role: organizationRole,
      });
      setDone(true);
      try {
        await request(`/tasks/${encodeURIComponent(task.id)}/formal-release/check`, "POST");
        await onRefreshCase();
        setMessage("角色动作已登记；L3 外发仍处于阻断状态。");
      } catch {
        setMessage("角色动作已登记，但状态刷新未完成；请手动刷新核对。");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登记失败，请核对签名规则包和账户。");
    } finally { inFlight.current = false; setWorking(false); }
  };
  return <details className="request-detail">
    <summary>L3 双人角色记录</summary>
    <p className="small-note">合伙人：{roles.legal_partner ? "已登记" : "待登记"}；数据保护负责人：{roles.data_protection_officer ? "已登记" : "待登记"}。须由签名规则包指定的不同账户操作。</p>
    <p className="small-note">仅记录角色动作，不代表资质已核实，也不批准或发送；L3 法域、PIA/CTIA 与原有门禁仍须核验。</p>
    {roles.state === "unconfigured" && <p className="error" role="alert">签名规则包中的 L3 角色配置未就绪：{roles.reason}</p>}
    <button className="secondary" type="button" onClick={submit}
      disabled={busy || working || done || recorded || roles.state === "unconfigured"}>
      {working ? "正在登记" : recorded || done ? "当前角色已登记" : "登记当前角色，不发送"}
    </button>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="small-note" role="status">{message}</p>}
  </details>;
}
