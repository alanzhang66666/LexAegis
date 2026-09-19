import { useEffect, useMemo, useRef, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { Tag } from "../components/ui";

type Obj = Record<string, any>;

const CONCLUSIONS = [
  ["allow_processing", "允许处理（不授予发送权）"],
  ["allow_after_minimization", "补充脱敏后允许"],
  ["needs_further_verification", "补充核实"],
  ["prohibit_external_processing", "禁止外部处理"],
  ["reject_current_request", "否决本次请求"],
] as const;

const KIND_LABEL: Record<string, string> = {
  prohibition: "法律禁止",
  verification: "待人工核实",
  minimization: "可脱敏后重验",
  engineering: "工程未就绪",
};

const DISPOSITION_LABEL: Record<string, string> = {
  allowed: "法律层面未形成禁止",
  needs_minimization: "需补充脱敏后重新校验",
  needs_verification: "需人工核实后重新判断",
  prohibited: "禁止当前外部处理",
};

const CONFIRM_TEXT = "我已阅读风险提示，并基于当前可得事实和页面展示信息作出本次审批判断。系统负责识别与提示，最终审批结论由审批人员就待核实事项作出。本次结论仅适用于当前材料版本、处理目的和处理方式。本页不授予发送权。";
const SCOPE_DEFAULT = "本次结论仅适用于当前材料版本、当前处理目的和当前处理方式。不授予发送权。";

function relatedLegalSources(task: Obj, pack?: Obj) {
  const sources: Obj[] = pack?.legal_sources || [];
  const byId = Object.fromEntries(sources.map((item: Obj) => [item.id, item]));
  const ids: string[] = [];
  const cats = new Set((task.risk?.detection_findings || []).map((item: Obj) => item.category));
  for (const rule of pack?.sensitive_object_rules || []) {
    if ((rule.detector_categories || []).some((category: string) => cats.has(category))) {
      ids.push(...(rule.legal_source_ids || []));
    }
  }
  for (const decision of task.decisions || []) {
    ids.push(...(decision.legal_source_ids || []));
  }
  for (const finding of task.prohibition_findings || []) {
    ids.push(...(finding.legal_source_ids || []));
  }
  return [...new Set(ids)].map(id => byId[id]).filter(Boolean);
}

function idempotencyKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function stableKey(keys: Map<string, string>, payload: Obj) {
  const signature = JSON.stringify(payload);
  if (!keys.has(signature)) keys.set(signature, idempotencyKey());
  return keys.get(signature)!;
}

export function ApprovalWorkspace({ task, pack, busy, role, onSubmit, onTechnicalIssue }:{
  task: Obj; pack?: Obj; busy: boolean; role?: string;
  onSubmit:(body:Obj)=>Promise<any>|void; onTechnicalIssue:(body:Obj)=>Promise<any>|void;
}) {
  const risk = task.risk || {};
  const gates: Obj[] = risk.gates || [];
  const verification = gates.filter(hit => hit.kind === "verification");
  const conditions: Obj[] = pack?.manual_review_conditions || [];
  const sources: Obj[] = pack?.legal_sources || [];
  const related = useMemo(() => relatedLegalSources(task, pack).slice(0, 3), [task, pack]);
  const [conclusion, setConclusion] = useState<(typeof CONCLUSIONS)[number][0]>("needs_further_verification");
  const [reason, setReason] = useState("");
  const [factPremise, setFactPremise] = useState("");
  const [authorityJudgment, setAuthorityJudgment] = useState("");
  const [externalNote, setExternalNote] = useState("");
  const [minimizationNote, setMinimizationNote] = useState("");
  const [finalBasis, setFinalBasis] = useState("");
  const [scopeNote, setScopeNote] = useState(SCOPE_DEFAULT);
  const [pickedConditions, setPickedConditions] = useState<string[]>(() => verification.slice(0, 2).map((_, index) => conditions[index]?.id).filter(Boolean));
  const [pickedSources, setPickedSources] = useState<string[]>(() => related.map((item: Obj) => item.id));
  const [sourceQuery, setSourceQuery] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [issueReason, setIssueReason] = useState("");
  const [issueEvidence, setIssueEvidence] = useState<string[]>([]);
  const [resolvedIssueIds, setResolvedIssueIds] = useState<string[]>([]);
  const [reviewEvidenceIds, setReviewEvidenceIds] = useState<string[]>([]);
  const [resolutionReason, setResolutionReason] = useState("");
  const technicalKeys = useRef(new Map<string, string>());
  const legalKeys = useRef(new Map<string, string>());
  const openIssues: Obj[] = (task.review_issues || []).filter((item: Obj) => item.status === "open");
  const evidenceOptions = useMemo(() => {
    const rows: {id:string; label:string}[] = [];
    for (const fact of task.fact_snapshot || []) {
      if (fact.id) rows.push({id:fact.id, label:`事实 ${fact.field || ""} · ${fact.id}`});
      for (const id of fact.source_ids || []) rows.push({id, label:`材料段落 · ${id}`});
    }
    for (const item of task.supplemental_evidence || []) {
      if (item.id) rows.push({id:item.id, label:item.label || item.title || `补充证据 · ${item.id}`});
    }
    const distinct = new Map(rows.map(item=>[item.id,item]));
    return [...distinct.values()];
  }, [task.fact_snapshot, task.supplemental_evidence]);
  useEffect(() => {
    if (pickedSources.length || !related.length) return;
    setPickedSources(related.map((item: Obj) => item.id));
  }, [related, pickedSources.length]);
  const processed = useMemo(() => {
    const decisions = task.decisions || [];
    const done = decisions.filter((item: Obj) => item.transform && item.transform !== "keep").map((item: Obj) => `${item.field}:${item.transform}`);
    const kept = decisions.filter((item: Obj) => item.output).map((item: Obj) => item.field);
    return { done, kept };
  }, [task.decisions]);
  const grouped = ["prohibition", "verification", "minimization", "engineering"].map(kind => ({
    kind, items: gates.filter(hit => hit.kind === kind),
  })).filter(group => group.items.length);
  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLowerCase();
    const filtered = !query ? sources : sources.filter((item: Obj) => {
      const haystack = `${item.title || ""} ${(item.articles || []).join(" ")} ${item.id || ""}`.toLowerCase();
      return haystack.includes(query);
    });
    const extras = sources.filter((item: Obj) => pickedSources.includes(item.id) && !filtered.some((row: Obj) => row.id === item.id));
    return extras.concat(filtered);
  }, [sources, sourceQuery, pickedSources]);
  const reply = (pack?.reply_templates || []).find((item: Obj) => item.disposition === (risk.disposition || "needs_verification"));
  const complete = Boolean(
    acknowledged && reason.trim() && factPremise.trim() && authorityJudgment.trim()
    && externalNote.trim() && minimizationNote.trim() && finalBasis.trim() && scopeNote.trim()
    && pickedConditions.length && pickedSources.length && reviewEvidenceIds.length > 0
    && (resolvedIssueIds.length === 0 || resolutionReason.trim())
    && (!(openIssues.length && ["allow_processing", "allow_after_minimization"].includes(conclusion)) || resolvedIssueIds.length > 0)
  );
  const toggle = (value: string, list: string[], setList:(next:string[])=>void) => {
    setList(list.includes(value) ? list.filter(item => item !== value) : [...list, value]);
  };
  return (
    <section className="legal-review">
      <h4 className="subheading">人工复核与审批</h4>
      <p className="finding">技术复核提交问题会立即暂停当前请求；法学复核可以否决本次请求。允许处理只解除相应复核限制，最终发送仍须由具名审批人批准。</p>
      <div className="review-state-card">
        <b>当前复核状态：{({pending:"待人工复核",blocked:"已暂停，等待复核",rejected:"人工复核已否决",cleared:"人工复核已完成",not_required:"无需人工复核"} as Record<string,string>)[task.review_status] || task.review_status || "待人工复核"}</b>
        <span>系统初检与人工复核分别记录；本区域的否决针对当前请求。</span>
      </div>
      {openIssues.length > 0 && <div className="review-issue-list" aria-label="待处理人工复核问题">
        <h5>待处理复核问题</h5>
        {openIssues.map((item:Obj)=><article key={item.id}><b>{item.reason}</b>
          <small>{item.created_by_role === "legal_reviewer" ? "法学复核" : item.created_by_role === "technical_reviewer" ? "技术复核" : item.created_by_role || "人工复核"} · {item.created_by_user_id || "具名复核"} · {item.created_at || "时间未记录"}</small>
          {!!item.evidence_ids?.length&&<small>关联证据：{item.evidence_ids.join("、")}</small>}</article>)}
      </div>}
      {role === "technical_reviewer" && <details className="technical-review" open={openIssues.length===0}>
        <summary>技术人员提交复核问题</summary>
        <p>请指出当前请求中的具体风险，并关联本案事实、材料段落或补充证据。提交后请求立即暂停。</p>
        <label className="stack-label">问题说明
          <textarea rows={3} value={issueReason} onChange={event=>setIssueReason(event.target.value)} aria-label="技术复核问题说明"/>
        </label>
        <fieldset className="review-evidence-options"><legend>关联证据</legend>
          {evidenceOptions.map(item=><label key={item.id}><input type="checkbox" checked={issueEvidence.includes(item.id)}
            onChange={()=>setIssueEvidence(old=>old.includes(item.id)?old.filter(id=>id!==item.id):[...old,item.id])}/>{item.label}</label>)}
          {!evidenceOptions.length&&<small>当前任务没有可引用的事实或补充证据。</small>}
        </fieldset>
        <button className="secondary" disabled={busy||!issueReason.trim()||!issueEvidence.length||!task.request_hash||["sending","unknown","complete","review_blocked","rejected","stopped"].includes(task.status)||["blocked","rejected"].includes(task.review_status)}
          onClick={()=>{
            const payload={request_hash:task.request_hash,reason:issueReason.trim(),evidence_ids:issueEvidence};
            onTechnicalIssue({...payload,idempotency_key:stableKey(technicalKeys.current,payload)});
          }}>
          暂停请求并提交技术问题
        </button>
      </details>}
      {role === "legal_reviewer" && <>
      <div className="review-blocks">
        <details open>
          <summary>为什么需要我看</summary>
          {(verification.slice(0, 2).length ? verification.slice(0, 2) : gates.slice(0, 2)).map((hit: Obj) => (
            <p key={hit.message}><Tag tone="amber">{KIND_LABEL[hit.kind] || hit.id}</Tag>{hit.message}</p>
          ))}
        </details>
        <details>
          <summary>关键材料片段</summary>
          {(task.decisions || []).filter((item: Obj) => item.output).slice(0, 6).map((item: Obj) => (
            <p key={item.fact_id || item.output}>{item.output}</p>
          ))}
          <small>本页仅展示判断所需的已处理片段，不是原文全文。</small>
        </details>
        <details>
          <summary>系统已做处理</summary>
          <p>已处理：{processed.done.join("、") || "无"}</p>
          <p>仍保留：{processed.kept.join("、") || "无"}</p>
          <small>删除直接标识不等于匿名化，组合信息仍可能识别特定主体。</small>
        </details>
        <details>
          <summary>法律依据与风险提示</summary>
          {related.length ? related.map((item: Obj) => (
            <p key={item.id}>
              <b>{item.title}</b> {(item.articles || []).join("、")}
              {item.rule_nature && item.rule_nature !== "statutory" ? <Tag>非法律强制</Tag> : null}
              <small>{item.provision_text || item.norm_summary || item.snapshot || ""}</small>
            </p>
          )) : <p>尚无与本工单绑定的法源，请在下拉中检索选择。</p>}
          {reply ? (
            <p className="reply-template"><b>对应回复口径（只展示）</b> {reply.title}。{reply.body}</p>
          ) : null}
          <ul className="risk-notices">
            <li>材料包含敏感信息，并不等于应当直接禁止外部处理。</li>
            <li>拥有查阅权限，不等于可以把材料向第三方提供。</li>
            <li>事实或法律适用存疑，应当暂停核实，而不是写成法律禁止。</li>
            <li>去标识处理不等于匿名化。</li>
            <li>服务商具备境外背景，不等于已经发生数据出境。</li>
          </ul>
        </details>
        <details>
          <summary>不得仅凭类别认定禁止</summary>
          {(pack?.not_hard_ban_categories || []).map((item: Obj) => (
            <p key={item.id}><b>{item.category}</b> {item.why_not_automatic_ban}<small>须判断：{(item.what_to_judge || []).join("、")}</small></p>
          ))}
          <small>命中类别不改变 disposition，也不产生新的 blocker。</small>
        </details>
        <details>
          <summary>冲突核实清单（不自动放行）</summary>
          <ol className="conflict-checklist">
            {(pack?.conflict_checklist || []).map((item: Obj) => (
              <li key={item.id}>{item.prompt}</li>
            ))}
          </ol>
          <small>六步仍在修订版原文中；运行库不执行，勾选或阅读都不改变 approval_allowed。</small>
        </details>
        <details>
          <summary>拟进行的外部处理</summary>
          <p>目标 {task.request?.target || "未冻结"} · 传输 {task.transport}</p>
          <p>数据流向以实际传输、存储和访问为准，不以品牌背景推定出境。</p>
        </details>
        <details open>
          <summary>复核结论（不发送）</summary>
          {grouped.map(group => (
            <div key={group.kind} className="gate-kind-group">
              <h5>{KIND_LABEL[group.kind]}</h5>
              {group.items.map((hit: Obj) => <p key={hit.id + hit.message}>{hit.message}</p>)}
            </div>
          ))}
          <fieldset>
            <legend>结论</legend>
            {CONCLUSIONS.map(([value, label]) => (
              <label key={value}><input type="radio" name="legal-review-conclusion" checked={conclusion===value}
                onChange={()=>setConclusion(value)}/>{label}</label>
            ))}
          </fieldset>
          {openIssues.length > 0 && <fieldset className="review-evidence-options">
            <legend>本次已解决的复核事项</legend>
            {openIssues.map((item:Obj)=><label key={item.id}><input type="checkbox" checked={resolvedIssueIds.includes(item.id)}
              onChange={()=>setResolvedIssueIds(old=>old.includes(item.id)?old.filter(id=>id!==item.id):[...old,item.id])}/>
              {item.reason}</label>)}
            <label className="stack-label">解决依据<textarea rows={2} value={resolutionReason}
              onChange={event=>setResolutionReason(event.target.value)} aria-label="复核事项解决依据"/></label>
            <small>只有“允许处理”或“补充脱敏后允许”可以关闭复核事项；仍须单独检验和审批。</small>
          </fieldset>}
          <fieldset className="review-evidence-options">
            <legend>本次复核证据（必选）</legend>
            {evidenceOptions.map(item=><label key={item.id}><input type="checkbox" checked={reviewEvidenceIds.includes(item.id)}
              onChange={()=>setReviewEvidenceIds(old=>old.includes(item.id)?old.filter(id=>id!==item.id):[...old,item.id])}/>{item.label}</label>)}
            {!evidenceOptions.length&&<small>当前任务没有可引用的事实、材料段落或补充证据。</small>}
          </fieldset>
          <label className="stack-label">待核实事项对应的审批理由
            <textarea rows={3} value={reason} onChange={event=>setReason(event.target.value)} aria-label="审批理由"/>
          </label>
          <label className="stack-label">事实前提
            <textarea rows={2} value={factPremise} onChange={event=>setFactPremise(event.target.value)} aria-label="事实前提"/>
          </label>
          <label className="stack-label">权限判断
            <textarea rows={2} value={authorityJudgment} onChange={event=>setAuthorityJudgment(event.target.value)} aria-label="权限判断"/>
          </label>
          <label className="stack-label">外部处理条件
            <textarea rows={2} value={externalNote} onChange={event=>setExternalNote(event.target.value)} aria-label="外部处理条件"/>
          </label>
          <label className="stack-label">最小化措施
            <textarea rows={2} value={minimizationNote} onChange={event=>setMinimizationNote(event.target.value)} aria-label="最小化措施"/>
          </label>
          <label className="stack-label">最终依据
            <textarea rows={2} value={finalBasis} onChange={event=>setFinalBasis(event.target.value)} aria-label="最终依据"/>
          </label>
          <label className="stack-label">适用边界
            <textarea rows={2} value={scopeNote} onChange={event=>setScopeNote(event.target.value)} aria-label="适用边界"/>
          </label>
          <div className="check-grid">
            {conditions.map((item: Obj) => (
              <label key={item.id}>
                <input type="checkbox" checked={pickedConditions.includes(item.id)}
                  onChange={()=>toggle(item.id, pickedConditions, setPickedConditions)}/>
                {item.trigger}
              </label>
            ))}
          </div>
          <label className="stack-label">法源（可检索全量）
            <input value={sourceQuery} onChange={event=>setSourceQuery(event.target.value)} aria-label="检索法源" placeholder="按名称、条款或标识检索"/>
            <select multiple size={6} value={pickedSources} aria-label="法源"
              onChange={event=>setPickedSources(Array.from(event.target.selectedOptions).map(option=>option.value))}>
              {filteredSources.map((item: Obj) => (
                <option key={item.id} value={item.id}>{item.title} {(item.articles||[]).join(" ")}</option>
              ))}
            </select>
          </label>
          <label className="confirm-line">
            <input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>
            {CONFIRM_TEXT}
          </label>
          {task.legal_review && (
            <p className="finding">已有复核记录：{task.legal_review.conclusion} · {task.legal_review.reviewer}。材料或请求变化后须重做。</p>
          )}
          <button className="secondary" disabled={busy || !complete || !task.request_hash || ["sending","unknown","complete","rejected","stopped"].includes(task.status)}
            onClick={()=>{
              const payload={
              request_hash: task.request_hash,
              material_version: task.request?.dependencies?.case_revision,
              conclusion, reason: reason.trim(),
              resolved_issue_ids: resolvedIssueIds,
              ...(resolvedIssueIds.length ? {resolution_reason:resolutionReason.trim()} : {}),
              evidence_ids: reviewEvidenceIds,
              reviewed_condition_ids: pickedConditions,
              legal_source_ids: pickedSources,
              acknowledged_risk_notices: true,
              fact_premise: factPremise.trim(),
              authority_judgment: authorityJudgment.trim(),
              external_processing_note: externalNote.trim(),
              minimization_note: minimizationNote.trim(),
              final_basis: finalBasis.trim(),
              scope_note: scopeNote.trim(),
              };
              onSubmit({...payload,idempotency_key:stableKey(legalKeys.current,payload)});
            }}>
            <ShieldAlert size={14}/>{conclusion === "reject_current_request" || conclusion === "prohibit_external_processing" ? "提交否决并阻断本次请求" : "提交法律复核结论"}
          </button>
        </details>
      </div>
      </>}
      {role === "approver" && <p className="small-note">审批人可在风险检验区批准当前版本；法学复核结论本身不会授予发送权。</p>}
      {!(["technical_reviewer","legal_reviewer","approver"].includes(role || "")) && <p className="small-note">当前角色不具备技术提请、法学否决或外发批准权限。</p>}
      {!!(task.review_events || []).length && <details className="review-history">
        <summary>人工复核留痕（{task.review_events.length}）</summary>
        <ol>{task.review_events.slice().reverse().map((event:Obj)=><li key={event.id}>
          <b>{event.event_type === "technical_issue_submitted" ? "技术复核提请" : event.event_type === "legal_review_recorded" ? "法学复核结论" : event.event_type}</b>
          <span>{event.actor || event.actor_user_id || "未知复核人"} · {event.actor_role || "未知角色"} · {event.at || "时间未记录"}</span>
          {event.payload?.reason&&<small>{event.payload.reason}</small>}
        </li>)}</ol>
      </details>}
    </section>
  );
}

export function dispositionCopy(risk: Obj) {
  const disposition = risk.disposition || (risk.blockers?.length ? "needs_verification" : "allowed");
  const legal = DISPOSITION_LABEL[disposition] || DISPOSITION_LABEL.needs_verification;
  const ready = risk.system_readiness === "ready" ? "工程条件就绪" : "工程或治理条件未就绪，不是法律禁止";
  return { disposition, legal, ready, blocked: Boolean(risk.blockers?.length) };
}
