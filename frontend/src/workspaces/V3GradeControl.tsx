import { useEffect, useRef, useState } from "react";

type Obj = Record<string, any>;
type RequestFn = (path: string, method?: string, body?: any) => Promise<any>;

/** Records a supplemental legal assessment; never approves or sends. */
export function V3GradeControl({task, role, runtimeProfile, busy, request, onRefreshCase}:{
  task: Obj; role?: string; runtimeProfile?: string; busy: boolean;
  request: RequestFn; onRefreshCase: () => Promise<void>;
}) {
  const [grade, setGrade] = useState("");
  const [working, setWorking] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  useEffect(() => { setGrade(""); setCompleted(false); setMessage(""); setError(""); }, [task.id, task.request_hash]);

  if (runtimeProfile !== "production" || role !== "legal_reviewer" || task.status !== "review"
      || task.request?.mode !== "formal" || task.transport !== "cloud" || !task.request_hash
      || (!task.product_release?.v3_grade_guard && !task.v3_grade_assessment_id)) return null;
  const assessmentExists = Boolean(task.v3_grade_assessment_id
    && task.v3_grade_assessment_request_hash === task.request_hash);
  const reviewReady = Boolean(task.legal_review?.id && task.review_status === "cleared");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!grade || busy || working || completed || assessmentExists || !reviewReady || inFlight.current) return;
    inFlight.current = true; setWorking(true); setError(""); setMessage("");
    try {
      await request(`/tasks/${encodeURIComponent(task.id)}/v3-grade-assessment`, "POST", {
        request_hash: task.request_hash, grade,
      });
      setCompleted(true);
      let checked = true;
      try { await request(`/tasks/${encodeURIComponent(task.id)}/formal-release/check`, "POST"); }
      catch { checked = false; }
      try {
        await onRefreshCase();
        setMessage(checked ? "等级已登记，仍需通过正式门禁和具名审批；此操作不发送。"
          : "等级已登记，但正式门禁检查未完成；请重新检查当前请求。");
      } catch {
        setMessage("等级已登记，但页面刷新失败；请手动刷新后检查，不要重复提交。");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "等级登记失败，请核对规则包和法学复核。");
    } finally {
      inFlight.current = false; setWorking(false);
    }
  };

  return <details className="request-detail">
    <summary>登记当前请求的法学等级</summary>
    <p className="small-note">由本请求的法学复核人按已签规则判断；登记不等于批准或发送。L0 与 L3 尚需额外证明，L4 和未知等级禁止外发。</p>
    {!reviewReady && <p className="small-note">请先由本人完成当前请求的法学复核。</p>}
    {assessmentExists && <p className="small-note">当前请求已有等级记录；需修改时请重新生成并复核请求。</p>}
    <form onSubmit={submit}>
      <label htmlFor="v3-grade">法学等级</label>{" "}
      <select id="v3-grade" value={grade} onChange={event => setGrade(event.target.value)}
        disabled={busy || working || completed || assessmentExists || !reviewReady}>
        <option value="">请选择</option>
        <option value="L0">L0 - 公开内容</option>
        <option value="L1">L1 - 常规确认</option>
        <option value="L2">L2 - 具名专业复核</option>
        <option value="L3">L3 - 需双人角色及法域评估</option>
        <option value="L4">L4 - 禁止外发</option>
        <option value="UNKNOWN">未知 - 禁止外发</option>
      </select>{" "}
      <button className="secondary" type="submit"
        disabled={busy || working || completed || assessmentExists || !reviewReady || !grade}>
        {working ? "正在登记" : "登记等级，不发送"}
      </button>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="small-note" role="status">{message}</p>}
    </form>
  </details>;
}
