import { useEffect, useRef, useState } from "react";

type Obj = Record<string, any>;
type RequestFn = (path: string, method?: string, body?: any) => Promise<any>;

/** An explicit cancellation and return to review, never an approval or send. */
export function ReapprovalControl({task, role, runtimeProfile, busy, request, onRefreshCase}:{
  task: Obj; role?: string; runtimeProfile?: string; busy: boolean;
  request: RequestFn; onRefreshCase: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [working, setWorking] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  useEffect(() => { setReason(""); setCompleted(false); setMessage(""); setError(""); }, [task.id, task.request_hash, task.formal_release?.grant?.id]);

  if (runtimeProfile !== "production" || role !== "approver" || task.status !== "approved"
      || task.request?.mode !== "formal" || task.transport !== "cloud" || !task.request_hash
      || !task.formal_release?.grant?.id) return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleaned = reason.trim();
    if (!cleaned || busy || completed || inFlight.current) return;
    inFlight.current = true; setWorking(true); setError(""); setMessage("");
    try {
      await request(`/tasks/${encodeURIComponent(task.id)}/formal-release/reapproval`, "POST", {
        request_hash: task.request_hash, reason: cleaned,
      });
      setCompleted(true);
      setReason("");
      try {
        await onRefreshCase();
        setMessage("已撤销旧许可并返回人工复核；仍需重新检查和由审批人批准。");
      } catch {
        setMessage("已准备重新审批，但页面刷新失败；请手动刷新查看状态，不要重复提交。");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "准备重新审批失败，请核对当前状态。");
    } finally {
      inFlight.current = false; setWorking(false);
    }
  };
  return <details className="request-detail">
    <summary>撤销旧许可并准备重新审批</summary>
    <p className="small-note">仅适用于尚未排队的当前请求。此操作不会批准或发送；已领取或有发送记录的请求不能使用此操作。原因会写入审计，请勿填写案情原文。</p>
    <form onSubmit={submit}>
      <div><label htmlFor="reapproval-reason">重新审批原因</label></div>
      <div><textarea id="reapproval-reason" rows={3} maxLength={1000} value={reason}
        style={{width:"100%", maxWidth:560}} onChange={event => setReason(event.target.value)} disabled={busy || working || completed}/></div>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="small-note" role="status">{message}</p>}
      <button className="secondary" type="submit" disabled={busy || working || completed || !reason.trim()}>
        {working ? "正在处理" : "撤销旧许可并返回复核"}
      </button>
    </form>
  </details>;
}
