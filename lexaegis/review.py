"""Shared, transaction-friendly workflow for technical and legal review.

The caller owns the repository transaction. Review records are append-only; the
task carries only a compatibility pointer to the latest legal review.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import uuid

from . import orchestrator


TERMINAL_TASK_STATES = {"sending", "unknown", "complete", "failed", "stopped", "rejected"}
LEGAL_CONCLUSIONS = {
    "allow_processing", "allow_after_minimization", "needs_further_verification",
    "prohibit_external_processing", "reject_current_request",
}
NEGATIVE_CONCLUSIONS = {"allow_after_minimization", "needs_further_verification", "prohibit_external_processing", "reject_current_request"}
RESOLVING_CONCLUSIONS = {"allow_processing"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def _actor(actor):
    if not isinstance(actor, dict):
        raise ValueError("必须提供复核人员身份")
    ident = str(actor.get("user_id") or actor.get("id") or "").strip()
    role = str(actor.get("actor_role") or actor.get("role") or "").strip()
    display = str(actor.get("display_name") or actor.get("actor") or actor.get("name") or ident).strip()
    if not ident or not role or not display:
        raise ValueError("复核人员身份信息不完整")
    return {"user_id": ident, "actor_role": role, "display_name": display}


def _event(repo, case_id, task_id, event_type, actor, payload):
    item = {"id": _id("review_event"), "case_id": case_id, "task_id": task_id,
            "event_type": event_type, "actor_user_id": actor["user_id"],
            "actor_role": actor["actor_role"], "actor": actor["display_name"],
            "at": _now(), **deepcopy(payload)}
    repo.put("review_event", item, case_id)
    return item


def list_open_issues(repo, case_id):
    """Return unresolved case issues, in repository insertion order."""
    return [i for i in repo.list("review_issue", case_id)
            if i.get("status") == "open" and i.get("case_id") == case_id]


def _case(repo, task):
    return repo.get(task["case_id"], "case")


def initialize_task_review(repo, task, parent_task_id=None):
    """Initialize review status and bind any unresolved case issues to a task."""
    case = _case(repo, task)
    opens = list_open_issues(repo, case["id"])
    if parent_task_id:
        parent = repo.get(parent_task_id, "task")
        if parent.get("case_id") != case["id"]:
            raise ValueError("后继任务必须属于同一案件")
        task["parent_task_id"] = parent_task_id
    task["inherited_review_issue_ids"] = sorted({
        *task.get("inherited_review_issue_ids", []),
        *(i["id"] for i in opens),
    })
    external = task.get("transport") not in {"local", "local_deterministic"} and task.get("execution_type") != "local_deterministic"
    task["review_status"] = "blocked" if opens else ("pending" if external else "not_required")
    task.setdefault("review_events", [])
    task.setdefault("legal_review_history", [])
    return task


def _require_current_request(repo, task, request_hash):
    current = str(task.get("request_hash") or "")
    if not current or not request_hash or str(request_hash) != current:
        raise ValueError("复核必须绑定当前冻结请求")
    case = _case(repo, task)
    material_version = int(case.get("revision") or 0)
    supplied = task.get("case_revision", material_version)
    if int(supplied) != material_version:
        raise ValueError("材料版本已变化，须重新生成请求")
    return case, material_version


def _validate_evidence_refs(repo, case_id, task, evidence_ids):
    ids = [str(x) for x in evidence_ids]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("须提供不重复的证据引用")
    blocks = set()
    for doc in repo.list("document", case_id):
        ir = doc.get("ir") or {}
        blocks.update(b.get("id") for b in ir.get("blocks", []) if b.get("id"))
    facts = {f["id"] for f in repo.list("fact", case_id)
             if not f.get("stale") and f.get("source_ids") and set(f["source_ids"]) <= blocks}
    supplemental = {str(x.get("id")) for x in task.get("supplemental_evidence", []) if isinstance(x, dict) and x.get("id")}
    supplemental.update(str(x) for x in task.get("supplemental_evidence_ids", []))
    if not set(ids) <= facts | blocks | supplemental:
        raise ValueError("证据引用必须属于本案当前事实、材料段落或本任务补充证据")
    return ids


def _idempotent_existing(repo, case_id, task_id, key, event_type, payload):
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    matches = [e for e in repo.list("review_event", case_id)
               if e.get("task_id") == task_id and e.get("idempotency_key") == key]
    if not matches:
        return None
    old = matches[0]
    if old.get("event_type") != event_type or old.get("payload_hash") != fingerprint:
        raise ValueError("幂等键已用于不同的复核内容")
    return old


def _record_idempotent(repo, task, event_type, actor, payload, idempotency_key):
    data = deepcopy(payload)
    data.pop("idempotency_key", None)
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    event = _event(repo, task["case_id"], task["id"], event_type, actor,
                   {"idempotency_key": idempotency_key, "payload_hash": digest, "payload": data})
    return event


def _terminal(task):
    if task.get("status") in TERMINAL_TASK_STATES:
        raise ValueError("任务已进入不可复核状态")


def _stop_unstarted_sends(repo, task, reason="human_review_blocked"):
    if task.get("status") in {"sending", "unknown", "complete"}:
        raise ValueError("请求已进入发送或结果核对阶段，不能标记为发送前否决")
    task["approval"] = None
    request_id = (task.get("request") or {}).get("request_id")
    if request_id:
        try:
            disclosure = repo.get(request_id, "disclosure")
        except KeyError:
            disclosure = None
        if disclosure and disclosure.get("status") == "reserved":
            disclosure.update(status="cancelled", cancellation_reason=reason)
            repo.put("disclosure", disclosure, task["case_id"])
    for job in repo.list("job", task["case_id"]):
        if job.get("kind") == "send" and job.get("payload", {}).get("task_id") == task["id"] and job.get("status") in {"pending", "running"}:
            job.update(status="cancelled", cancelled_at=_now(), cancel_reason=reason)
            repo.put("job", job, task["case_id"])


def _pause_case_siblings(repo, task, actor):
    """A case concern invalidates earlier sibling approvals permanently."""
    from .release_service import revoke
    for sibling in repo.list("task", task["case_id"]):
        if sibling["id"] == task["id"] or sibling.get("status") in TERMINAL_TASK_STATES:
            continue
        _stop_unstarted_sends(repo, sibling)
        revoke(repo, sibling, "本案出现新的人工复核事项", actor["user_id"])
        orchestrator.transition_task(repo, sibling, "review_blocked", "HUMAN",
                                     review_status="blocked", actor=actor["user_id"])
        sibling["inherited_review_issue_ids"] = sorted({
            *sibling.get("inherited_review_issue_ids", []),
            *(i["id"] for i in list_open_issues(repo, task["case_id"])),
        })
        repo.put("task", sibling, task["case_id"])
        _event(repo, task["case_id"], sibling["id"], "case_issue_paused_request", actor,
               {"origin_task_id": task["id"], "request_hash": sibling.get("request_hash")})


def submit_issue(repo, task, body, actor):
    """Append a technical concern and atomically suspend all unstarted sends."""
    actor = _actor(actor)
    if actor["actor_role"] != "technical_reviewer":
        raise ValueError("只有 technical_reviewer 可以提交技术复核问题")
    case, material_version = _require_current_request(repo, task, body.get("request_hash"))
    key = str(body.get("idempotency_key") or "").strip()
    reason = str(body.get("reason") or "").strip()
    evidence = _validate_evidence_refs(repo, case["id"], task, body.get("evidence_ids") or [])
    if not key or not reason:
        raise ValueError("技术问题必须包含幂等键和问题说明")
    normalized = {"request_hash": task["request_hash"], "reason": reason, "evidence_ids": evidence,
                  "material_version": material_version, "actor_user_id": actor["user_id"]}
    found = _idempotent_existing(repo, case["id"], task["id"], key, "technical_issue_submitted", normalized)
    if found:
        return task
    _terminal(task)
    issue = {"id": _id("review_issue"), "case_id": case["id"], "task_id": task["id"],
             "request_hash": task["request_hash"], "material_version": material_version,
             "reason": reason, "evidence_ids": evidence, "status": "open", "created_at": _now(),
             "created_by_user_id": actor["user_id"], "created_by_role": actor["actor_role"]}
    _stop_unstarted_sends(repo, task)
    repo.put("review_issue", issue, case["id"])
    _pause_case_siblings(repo, task, actor)
    task.setdefault("inherited_review_issue_ids", []).append(issue["id"])
    task["review_status"] = "blocked"
    orchestrator.transition_task(repo, task, "review_blocked", "HUMAN",
                                 actor=actor["user_id"])
    task["approval"] = None
    _record_idempotent(repo, task, "technical_issue_submitted", actor, normalized, key)
    repo.put("task", task, case["id"])
    return task


def _pack_refs(repo, task):
    pack = repo.get(task["pack_id"], "pack")
    from .util import digest
    expected = ((task.get("request") or {}).get("dependencies") or {}).get("pack_hash")
    if expected and expected != digest(pack):
        raise ValueError("规则包已变化，当前请求的复核依据已失效")
    legal_sources = {str(x.get("id")) for x in pack.get("legal_sources", []) if isinstance(x, dict) and x.get("id")}
    conditions = {str(x.get("id")) for x in pack.get("manual_review_conditions", []) if isinstance(x, dict) and x.get("id")}
    # Some packs express review conditions as records inside task rules.
    for rule in pack.get("rules", []):
        conditions.update(str(x.get("id")) for x in rule.get("conditions", []) if isinstance(x, dict) and x.get("id"))
    return pack, legal_sources, conditions


def record_review(repo, task, body, actor):
    """Append a legal conclusion, resolving issues only with explicit legal basis."""
    actor = _actor(actor)
    if actor["actor_role"] != "legal_reviewer":
        raise ValueError("只有 legal_reviewer 可以作出法学复核结论")
    key = str(body.get("idempotency_key") or "").strip()
    if not key:
        raise ValueError("复核必须提供幂等键")
    replay_payload = {k: deepcopy(body.get(k)) for k in (
        "request_hash", "material_version", "conclusion", "reason", "reviewed_condition_ids", "legal_source_ids",
        "prohibition_findings", "minimization_actions", "acknowledged_risk_notices", "scope_note", "fact_premise",
        "authority_judgment", "external_processing_note", "minimization_note", "final_basis", "resolved_issue_ids", "resolution_reason", "evidence_ids")
        if k in body}
    replay_payload["actor_user_id"] = actor["user_id"]
    if _idempotent_existing(repo, task["case_id"], task["id"], key, "legal_review_recorded", replay_payload):
        return task
    _terminal(task)
    case, material_version = _require_current_request(repo, task, body.get("request_hash"))
    evidence_ids = _validate_evidence_refs(repo, case["id"], task, body.get("evidence_ids") or [])
    if body.get("material_version") is not None and int(body["material_version"]) != material_version:
        raise ValueError("材料版本已变化，须重新核实")
    conclusion = str(body.get("conclusion") or "")
    if conclusion not in LEGAL_CONCLUSIONS:
        raise ValueError("未知法学复核结论")
    reason = str(body.get("reason") or "").strip()
    required = ("reason", "fact_premise", "authority_judgment", "external_processing_note", "minimization_note", "final_basis", "scope_note")
    if any(not str(body.get(k) or "").strip() for k in required):
        raise ValueError("复核理由、事实前提、权限判断、外部处理条件、最小化措施、最终依据和适用边界均须填写")
    if not body.get("acknowledged_risk_notices"):
        raise ValueError("须确认已阅读风险提示")
    source_ids = [str(x) for x in body.get("legal_source_ids") or []]
    condition_ids = [str(x) for x in body.get("reviewed_condition_ids") or []]
    if not source_ids or not condition_ids:
        raise ValueError("须引用适用法源和复核事项")
    pack, valid_sources, valid_conditions = _pack_refs(repo, task)
    if not set(source_ids) <= valid_sources:
        raise ValueError("法源引用不属于当前规则包")
    if not set(condition_ids) <= valid_conditions:
        raise ValueError("复核事项不属于当前规则包")
    open_issues = list_open_issues(repo, case["id"])
    resolved_ids = [str(x) for x in body.get("resolved_issue_ids") or []]
    normalized = {k: deepcopy(body.get(k)) for k in (
        "request_hash", "material_version", "conclusion", "reason", "reviewed_condition_ids", "legal_source_ids",
        "prohibition_findings", "minimization_actions", "acknowledged_risk_notices", "scope_note", "fact_premise",
        "authority_judgment", "external_processing_note", "minimization_note", "final_basis", "resolved_issue_ids", "resolution_reason", "evidence_ids")
        if k in body}
    normalized["actor_user_id"] = actor["user_id"]
    found = _idempotent_existing(repo, case["id"], task["id"], key, "legal_review_recorded", normalized)
    if found:
        return task
    if conclusion in RESOLVING_CONCLUSIONS and open_issues:
        if not str(body.get("resolution_reason") or "").strip() or not resolved_ids:
            raise ValueError("解决未完成复核事项须提供法学理由和 resolved_issue_ids")
        current_ids = {i["id"] for i in open_issues}
        if not set(resolved_ids) <= current_ids:
            raise ValueError("只能解决本案当前未完成的复核事项")
        task_issue_ids = {i["id"] for i in repo.list("review_issue", case["id"])
                          if i.get("task_id") == task["id"]}
        task_issue_ids.update(task.get("inherited_review_issue_ids", []))
        if not set(resolved_ids) <= task_issue_ids:
            raise ValueError("只能解决本任务明确继承或提请的复核事项")
    elif resolved_ids:
        raise ValueError("只有允许处理的结论可以解决复核事项")
    record = {"id": _id("legal_review"), "case_id": case["id"], "task_id": task["id"],
              "request_hash": task["request_hash"], "material_version": material_version,
              "conclusion": conclusion, "reason": reason, "reviewed_condition_ids": condition_ids,
              "legal_source_ids": source_ids, "prohibition_findings": deepcopy(body.get("prohibition_findings") or []),
              "minimization_actions": deepcopy(body.get("minimization_actions") or []),
              "acknowledged_risk_notices": True, "reviewer": actor["display_name"],
              "reviewer_user_id": actor["user_id"], "reviewer_role": actor["actor_role"], "reviewed_at": _now(),
              "evidence_ids": evidence_ids,
              **{k: str(body[k]).strip() for k in required if k != "reason"}}
    if conclusion in NEGATIVE_CONCLUSIONS:
        _stop_unstarted_sends(repo, task)
        # Even a legal decision without a prior technical issue must survive
        # reevaluation and independently created successor tasks.
        issue = {"id": _id("review_issue"), "case_id": case["id"], "task_id": task["id"],
                 "request_hash": task["request_hash"], "material_version": material_version,
                 "reason": reason, "evidence_ids": evidence_ids, "status": "open", "created_at": _now(),
                 "created_by_user_id": actor["user_id"], "created_by_role": actor["actor_role"],
                 "legal_review_id": record["id"]}
        repo.put("review_issue", issue, case["id"])
        _pause_case_siblings(repo, task, actor)
        task.setdefault("inherited_review_issue_ids", []).append(issue["id"])
        task["review_status"] = "rejected" if conclusion in {"prohibit_external_processing", "reject_current_request"} else "blocked"
        orchestrator.transition_task(
            repo, task,
            "rejected" if task["review_status"] == "rejected" else "review_blocked",
            "HUMAN", actor=actor["user_id"])
        task["approval"] = None
    else:
        for issue_id in resolved_ids:
            issue = repo.get(issue_id, "review_issue")
            if issue.get("case_id") != case["id"] or issue.get("status") != "open":
                raise ValueError("复核事项已解决或不属于本案")
            issue.update(status="resolved", resolved_at=_now(), resolved_by_user_id=actor["user_id"],
                         resolved_by_role=actor["actor_role"], resolution_reason=body["resolution_reason"].strip(),
                         resolving_review_id=record["id"])
            repo.put("review_issue", issue, case["id"])
        task["review_status"] = "pending" if list_open_issues(repo, case["id"]) else "cleared"
        if task.get("status") == "review_blocked":
            orchestrator.transition_task(
                repo, task,
                "review" if (task.get("risk") or {}).get("approval_allowed") else "blocked",
                "HUMAN", actor=actor["user_id"])
    task["review_request_hash"] = task["request_hash"]
    task.setdefault("legal_review_history", []).append(record["id"])
    task["legal_review"] = deepcopy(record)
    _record_idempotent(repo, task, "legal_review_recorded", actor, normalized, key)
    repo.put("legal_review_record", record, case["id"])
    repo.put("task", task, case["id"])
    return task


def assert_review_allows(repo, task):
    status = task.get("review_status", "pending" if task.get("transport") not in {"local", "local_deterministic"} else "not_required")
    if status not in {"cleared", "not_required"}:
        raise ValueError("人工复核尚未允许当前请求继续")
    if status == "cleared" and task.get("review_request_hash") != task.get("request_hash"):
        raise ValueError("人工复核不适用于当前请求")
    open_issues = list_open_issues(repo, task["case_id"])
    if open_issues:
        raise ValueError("本案仍有未解决的人工复核事项")
    return True


def review_state(repo, task):
    events = [e for e in repo.list("review_event", task["case_id"]) if e.get("task_id") == task["id"]]
    issues = [i for i in repo.list("review_issue", task["case_id"])
              if i.get("case_id") == task["case_id"] and (i.get("task_id") == task["id"] or i.get("id") in task.get("inherited_review_issue_ids", []))]
    return {"review_status": task.get("review_status", "pending"), "open_issues": [i for i in issues if i.get("status") == "open"],
            "issues": issues, "events": events, "latest_legal_review": deepcopy(task.get("legal_review"))}
