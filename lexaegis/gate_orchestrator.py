"""V3 four-gate orchestration over the existing formal G0-G10 decision.

``build_gate_bundle`` is the legacy, non-authoritative display projection.
``evaluate_gate_bundle`` derives per-gate states from a completed server-side
``evaluate_release`` decision and is an additional fail-closed prerequisite
for approval and dispatch. Neither grants authorization: the one-time grant
and the gateway claim remain the only send authority.
"""
from copy import deepcopy

from .util import digest, now

# G2 contributes both legal and disclosure checks in the ADR.
GATE_GROUPS = {
    "G-L": ("G1", "G2", "G3", "G5"),
    "G-D": ("G0", "G2", "G7", "G8"),
    "G-H": ("G6", "G10"),
    "G-S": ("G9",),
}
LABELS = {
    "G-L": "法律与接收方", "G-D": "最小披露与风险",
    "G-H": "请求冻结与具名审批", "G-S": "网关与部署核验",
}


def build_gate_bundle(decision):
    """Project a legacy decision without changing it or asserting per-gate pass."""
    if not isinstance(decision, dict) or not isinstance(decision.get("hits"), list):
        raise ValueError("四门展示需要完整的原始门禁结果")
    hits = decision["hits"]
    if any(not isinstance(hit, dict) or not isinstance(hit.get("gate_id"), str) for hit in hits):
        raise ValueError("四门展示的门禁项格式无效")
    groups = []
    covered = {gate for ids in GATE_GROUPS.values() for gate in ids}
    for group_id, gate_ids in GATE_GROUPS.items():
        group_hits = [deepcopy(hit) for hit in hits if hit["gate_id"] in gate_ids]
        groups.append({
            "id": group_id, "label": LABELS[group_id],
            "legacy_gate_ids": list(gate_ids),
            "state": "has_blockers" if group_hits else "not_individually_verified",
            "hits": group_hits,
        })
    global_hits = [deepcopy(hit) for hit in hits if hit["gate_id"] not in covered]
    eligible = decision.get("approval_eligible") is True
    return {
        "schema_version": 1, "authoritative": False,
        "description": "仅展示既有门禁命中项；未列出的门禁不代表通过或可以发送。",
        "request_hash": decision.get("request_hash") or None,
        "snapshot_hash": decision.get("snapshot_hash") or None,
        "phase": decision.get("phase") or "unknown",
        "legacy_approval_eligible": eligible,
        "summary_state": "ready_for_approval" if eligible and not hits else "blocked",
        "groups": groups, "global_hits": global_hits,
    }


# Receipt-backed gates checked by formal_release.evaluate_release. A gate is
# "pass" only when that completed evaluation found valid evidence for it.
RECEIPT_GATES = ("G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10")
AUTHORITATIVE_GROUPS = {
    "G-L": ("G1", "G2", "G3", "G5"),
    "G-D": ("G0", "G2", "G7", "G8"),
    "G-H": ("G6", "G10"),
    "G-S": ("G9", "isolation"),
}
_ABORTED = "formal_release_blocked"
_ISOLATION_MISSING = "isolation_receipt_missing"
BUNDLE_KIND = "gate_evaluation_bundle"


def _group_state(states):
    if all(state == "pass" for state in states):
        return "pass"
    for state in ("fail", "unknown"):
        if state in states:
            return state
    return "pending"


def evaluate_gate_bundle(decision, task, case, phase="approve"):
    """Derive the authoritative four-gate state from a completed evaluation.

    Fail closed: an aborted evaluation leaves every receipt gate "unknown",
    an unrecognised hit blocks, and G0 passes only when the persisted risk
    result allows approval for the expected disclosure ledger. Before enqueue
    that is the assessed ledger; at send it is the ledger recorded at enqueue,
    matching ``service.authorize_dispatch``. The phase is not hashed.
    """
    if hasattr(decision, "model_dump"):
        decision = decision.model_dump(mode="json")
    if (not isinstance(decision, dict) or decision.get("phase") != "evaluate"
            or not isinstance(decision.get("hits"), list) or not decision.get("request_hash")
            or not decision.get("snapshot_hash")):
        raise ValueError("四门评估需要完整的服务端正式评估结果")
    hits = decision["hits"]
    if any(not isinstance(hit, dict) or not isinstance(hit.get("gate_id"), str) for hit in hits):
        raise ValueError("四门评估的门禁项格式无效")
    aborted = any(hit["gate_id"] == "G-product" and hit.get("reason_code") == _ABORTED for hit in hits)
    gates = {}
    for gate_id in RECEIPT_GATES:
        own = [hit for hit in hits if hit["gate_id"] == gate_id]
        if aborted:
            gates[gate_id] = "unknown"
        elif any(hit.get("status") == "fail" for hit in own):
            gates[gate_id] = "fail"
        else:
            gates[gate_id] = "pending" if own else "pass"
    isolation_hits = [hit for hit in hits if hit["gate_id"] == "G-product"
                      and hit.get("reason_code") == _ISOLATION_MISSING]
    gates["isolation"] = "unknown" if aborted else ("pending" if isolation_hits else "pass")
    risk = (task or {}).get("risk") or {}
    if not risk:
        gates["G0"] = "unknown"
    else:
        expected = risk.get("ledger_version")
        if phase == "send":
            expected = (task or {}).get("dispatch_ledger_version")
        current = (case or {}).get("ledger_version")
        ledger_ok = (expected is None and phase == "send") or expected == current
        gates["G0"] = "pass" if risk.get("approval_allowed") is True and ledger_ok else "fail"
    known = set(RECEIPT_GATES) | {"G-product"}
    global_hits = [deepcopy(hit) for hit in hits if hit["gate_id"] not in known
                   or (hit["gate_id"] == "G-product" and hit.get("reason_code") != _ISOLATION_MISSING)]
    groups = []
    for group_id, members in AUTHORITATIVE_GROUPS.items():
        member_hits = [deepcopy(hit) for hit in hits if hit["gate_id"] in members
                       or ("isolation" in members and hit in isolation_hits)]
        groups.append({"id": group_id, "label": LABELS[group_id], "legacy_gate_ids": list(members),
                       "state": _group_state([gates[gate] for gate in members]), "hits": member_hits})
    eligible = (decision.get("approval_eligible") is True and not global_hits
                and all(group["state"] == "pass" for group in groups))
    body = {
        "schema_version": 2, "authoritative": True,
        "task_id": (task or {}).get("id"), "request_hash": decision["request_hash"],
        "snapshot_hash": decision["snapshot_hash"], "risk_ledger_version": risk.get("ledger_version"),
        "legacy_gates": {gate: gates[gate] for gate in ("G0", *RECEIPT_GATES, "isolation")},
        "groups": groups, "global_hits": global_hits,
        "approval_eligible": eligible, "dispatch_allowed": False,
    }
    return {**body, "bundle_hash": "sha256:" + digest({"domain": "lexaegis.v3.GateEvaluationBundle",
                                                        "value": body})}


def persist_gate_bundle(repo, bundle, scope=""):
    """Record an approval-time bundle server-side; the client never supplies it."""
    if bundle.get("authoritative") is not True or bundle.get("approval_eligible") is not True:
        raise ValueError("只能登记服务端判定全部满足的四门评估")
    record = {**deepcopy(bundle), "id": "gate-bundle-" + bundle["bundle_hash"].removeprefix("sha256:"),
              "status": "current", "recorded_at": now()}
    repo.put(BUNDLE_KIND, record, scope)
    return record


def require_bound_bundle(repo, task, bundle):
    """At enqueue/send the recomputed bundle must equal the approved record."""
    binding = ((task or {}).get("formal_release") or {}).get("gate_evaluation") or {}
    try:
        record = repo.get(binding.get("id", ""), BUNDLE_KIND)
    except KeyError:
        raise ValueError("缺少服务端登记的四门评估，请重新评估并批准") from None
    if (record.get("status") != "current" or record.get("bundle_hash") != binding.get("bundle_hash")
            or record.get("task_id") != task.get("id") or record.get("request_hash") != task.get("request_hash")):
        raise ValueError("四门评估登记已失效或不属于当前请求")
    if not bundle.get("approval_eligible") or bundle.get("bundle_hash") != record["bundle_hash"]:
        raise ValueError("四门评估已变化，请重新评估并批准")
    return record


def retire_bound_bundle(repo, task, reason):
    binding = ((task or {}).get("formal_release") or {}).get("gate_evaluation") or {}
    try:
        record = repo.get(binding.get("id", ""), BUNDLE_KIND)
    except KeyError:
        return False
    if record.get("status") != "current":
        return False
    repo.put(BUNDLE_KIND, {**record, "status": "retired", "retired_reason": reason, "retired_at": now()},
             task.get("case_id", ""))
    return True
