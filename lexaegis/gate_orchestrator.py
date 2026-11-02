"""Non-authoritative V3 four-gate projection of existing formal decisions.

Never validates evidence, grants authorization, or decides to send. Missing
hits do not prove a gate passed: the legacy decision only exposes blockers.
"""
from copy import deepcopy

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
