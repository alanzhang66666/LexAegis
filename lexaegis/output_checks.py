"""Return-side output verification (C3): what the cloud wrote back must not
commit the five legally-material distortion classes against the wire payload
that was actually sent.

Each check mirrors an outbound-side rule already enforced in
``disclosure.constraint_reasons`` but compares the returned claim text
against the disclosed decision outputs instead of the local originals.
Severity is declared by the pack (``return_check_severity``); the default for
every class is ``block`` — the legal ruling on date truncation is
unconditional, and a pack may only downgrade a class to ``review``
explicitly.
"""
from __future__ import annotations

import re

from .policy import TOKEN
from .disclosure import (
    HOLDER_VALUES,
    _flattens_dispute,
    _holder_flipped,
    _keeps_negation,
    _negated,
    _upgrades_to_finding,
    fact_attr,
    month_truncated,
    shifted_calendar,
)

CHECKS = (
    "month_truncation", "calendar_shift", "claim_flattening",
    "finding_upgrade", "subject_swap", "negation_loss", "holder_flip",
)

MESSAGES = {
    "month_truncation": "阻断：截月导致期限或先后关系错误（一般整理与加班同一等级）",
    "calendar_shift": "禁止整体平移日历，以免改变星期、节假日或法规范生效日",
    "claim_flattening": "主张或否认被写成无争议事实",
    "finding_upgrade": "主张或文书记载被提升为法院认定",
    "subject_swap": "主体归属被改写为其他主体",
    "negation_loss": "否认或抗辩被删成肯定陈述",
    "holder_flip": "证据持有人被改挂",
}


def severities(pack) -> dict:
    declared = (pack or {}).get("return_check_severity") or {}
    unknown = set(declared) - set(CHECKS)
    if unknown:
        raise ValueError("未知返回校核项：" + "、".join(sorted(unknown)))
    levels = {}
    for name in CHECKS:
        level = declared.get(name, "block")
        if level not in {"block", "review", "off"}:
            raise ValueError(f"返回校核 {name} 的级别必须为 block/review/off")
        levels[name] = level
    return levels


def _clause_tokens(text):
    tokens = []
    for clause in re.split(r"[，。；;,.!?\n、（）()\s]+", text or ""):
        tokens.append(TOKEN.findall(clause))
    return tokens


def _subject_swap(supports, claim_text):
    """A token pair ordered A→B in a source clause that appears B→A in the
    claim reassigns who did what to whom."""
    claim_clauses = _clause_tokens(claim_text)
    for output in supports:
        for source in _clause_tokens(output):
            if len(source) < 2:
                continue
            for clause in claim_clauses:
                if set(source) - set(clause):
                    continue
                positions = [clause.index(t) for t in source]
                if positions != sorted(positions):
                    return True
    return False


def apply_return_checks(claims, decisions, facts, pack) -> dict:
    """Annotate each claim with distortion issues; returns block/review counts.

    ``blocked`` claims cannot be confirmed by the review endpoint — the task
    must be redone rather than adopted.
    """
    levels = severities(pack)
    decisions = {d["fact_id"]: d for d in (decisions or [])}
    facts = {f["id"]: f for f in (facts or [])}
    counts = {"block": 0, "review": 0}
    for claim in claims:
        outputs = [decisions[i]["output"] for i in claim.get("source_ids") or []
                   if i in decisions and decisions[i].get("output")]
        if not outputs:
            continue
        text = claim.get("text") or ""
        hits = set()
        if levels["month_truncation"] != "off" and any(
                month_truncated(output, text) for output in outputs):
            hits.add("month_truncation")
        if levels["calendar_shift"] != "off" and any(
                shifted_calendar(output, text) for output in outputs):
            hits.add("calendar_shift")
        anchored = [facts.get(i) for i in claim.get("source_ids") or []]
        anchored = [f for f in anchored if f]
        for fact, output in zip(anchored,
                                [decisions[f["id"]]["output"] for f in anchored
                                 if f["id"] in decisions]):
            stance = fact_attr(fact, "claim_stance") or fact.get("statement_status") \
                or fact.get("dispute_status")
            if levels["claim_flattening"] != "off" and stance in {
                    "claim", "deny", "claimed", "denied", "disputed"} and text \
                    and _flattens_dispute(output, text, stance):
                hits.add("claim_flattening")
            if levels["finding_upgrade"] != "off" and text \
                    and _upgrades_to_finding(fact, output, text):
                hits.add("finding_upgrade")
            if levels["negation_loss"] != "off" and text \
                    and _negated(fact, output) and not _keeps_negation(output, text):
                hits.add("negation_loss")
            if levels["holder_flip"] != "off" and text:
                holder = fact_attr(fact, "evidence_holder")
                if holder in set(HOLDER_VALUES.values()) and \
                        _holder_flipped(holder, output, text, fact):
                    hits.add("holder_flip")
        if levels["subject_swap"] != "off" and _subject_swap(outputs, text):
            hits.add("subject_swap")
        for name in sorted(hits):
            level = levels[name]
            message = MESSAGES[name] if level == "block" \
                else "须人工修改：" + MESSAGES[name].removeprefix("阻断：")
            if message not in claim["issues"]:
                claim["issues"].append(message)
            counts[level] += 1
        if any(levels[name] == "block" for name in hits):
            claim["status"] = "blocked"
            claim["blocked"] = True
        elif hits and claim.get("status") not in {"needs_review", "blocked"}:
            claim["status"] = "needs_review"
    return counts
