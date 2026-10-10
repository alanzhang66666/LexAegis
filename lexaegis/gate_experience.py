"""Read-only, user-facing summary of existing formal release gate decisions.

This module never grants permission. Authoritative gating remains in
formal_release.evaluate_release and release_service.assert_allowed.
"""

GATE_AREAS = {
    "G1": "case", "G2": "case", "G3": "governance",
    "G5": "governance", "G6": "request", "G7": "request",
    "G8": "request", "G9": "environment", "G10": "request",
    "G-product": "system",
}

AREA_LABELS = {
    "case": "案件与法源", "governance": "规则与服务商",
    "request": "本次披露与授权", "environment": "运行环境",
    "system": "产品放行",
}

def summarize_gate_decision(decision):
    """Group blockers by user concern without changing authorization semantics.

    An empty hit list is not a permission by itself: only the authoritative
    approval_eligible flag can produce a ready summary.
    """
    hits = decision.get("hits") or []
    groups = {}
    for hit in hits:
        gate_id = hit.get("gate_id") or hit.get("id") or "unknown"
        area = GATE_AREAS.get(gate_id, "system")
        group = groups.setdefault(area, {
            "area": area, "label": AREA_LABELS[area], "items": [],
        })
        group["items"].append({
            "gate_id": gate_id,
            "reason_code": hit.get("reason_code"),
            "message": hit.get("message") or "需补充验证",
            "kind": hit.get("kind"),
        })
    ready = decision.get("approval_eligible") is True and not hits
    return {
        "state": "ready_for_approval" if ready else "blocked",
        "user_action": "review_request" if ready else "resolve_blockers",
        "groups": [groups[key] for key in ("system", "environment", "governance", "case", "request") if key in groups],
        "authoritative": False,
    }
