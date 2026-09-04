# SPDX-License-Identifier: Apache-2.0
# Modified for LexAegis from concepts in kubeedge/ianvs PR #283 at 8150672e.
"""Deterministic, anchor-aware privacy signals.

Inspired by the detector/risk structure in kubeedge/ianvs PR #283 (Apache-2.0),
but intentionally excludes NLP model calls and legal conclusions.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .util import digest


DEFAULT_PATTERNS = [
    {"category": "身份证号", "pattern": r"(?<!\d)\d{17}[\dXx](?!\d)", "risk": "critical"},
    {"category": "手机号", "pattern": r"(?<!\d)1[3-9]\d{9}(?!\d)", "risk": "high"},
    {"category": "电子邮箱", "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "risk": "high"},
    {"category": "银行卡或长编号", "pattern": r"(?<!\d)\d{16,19}(?!\d)", "risk": "critical"},
    {"category": "姓名", "pattern": r"(?<=劳动者)[\u4e00-\u9fff]{2,4}(?=主张|诉称|称|，|。|\s|$)", "risk": "high"},
    {"category": "姓名", "pattern": r"(?<=申请人)[\u4e00-\u9fff]{2,4}(?=主张|诉称|称|，|。|\s|$)", "risk": "high"},
    {"category": "姓名", "pattern": r"(?<=被申请人)[\u4e00-\u9fff]{2,4}(?=主张|辩称|称|，|。|\s|$)", "risk": "high"},
]


def _patterns(pack: dict | None) -> list[dict]:
    configured = (pack or {}).get("direct_identifier_patterns") or []
    return DEFAULT_PATTERNS + [p for p in configured if {"category", "pattern"} <= p.keys()]


def detect_text(text: str, anchor_id: str | None = None, pack: dict | None = None) -> list[dict]:
    findings = []
    for spec in _patterns(pack):
        try:
            matches = re.finditer(spec["pattern"], text)
        except re.error:
            continue
        for match in matches:
            finding = {
                "category": str(spec["category"]), "value": match.group(0),
                "start": match.start(), "end": match.end(),
                "risk": spec.get("risk", "high"),
                "source_anchor_id": anchor_id,
                "source_anchor_ids": [anchor_id] if anchor_id else [],
                "source_spans": [],
                "coordinate_space": "disclosure",
                "locator_status": "located" if anchor_id else "warning",
                "explanation": "由冻结的确定性模式命中；结果不是法律结论。",
            }
            finding["id"] = "finding_" + digest(finding)[:16]
            findings.append(finding)
    return merge_overlaps(findings)


def bind_source_spans(findings: list[dict], source_ids: list[str], anchors: dict[str, dict]) -> list[dict]:
    """Bind disclosure-space matches to every exact occurrence in cited sources."""
    bound = []
    for finding in findings:
        item = dict(finding)
        spans = []
        for anchor_id in source_ids:
            source = anchors.get(anchor_id)
            if not source or not finding["value"]:
                continue
            offset = 0
            while True:
                start = source.get("text", "").find(finding["value"], offset)
                if start < 0:
                    break
                spans.append({"anchor_id": anchor_id, "start": start, "end": start + len(finding["value"]),
                              "document_version": source.get("document_version")})
                offset = start + max(1, len(finding["value"]))
        item["source_anchor_ids"] = list(dict.fromkeys(source_ids))
        item["source_spans"] = spans
        item["source_anchor_id"] = spans[0]["anchor_id"] if spans else (source_ids[0] if source_ids else None)
        item["locator_status"] = "located" if spans else "warning"
        bound.append(item)
    return bound


def merge_overlaps(findings: list[dict]) -> list[dict]:
    """Merge overlapping spans on the same anchor, retaining the highest risk."""
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    ordered = sorted(findings, key=lambda f: (f.get("source_anchor_id") or "", f["start"], -f["end"]))
    result = []
    for finding in ordered:
        if result and result[-1].get("source_anchor_id") == finding.get("source_anchor_id") and finding["start"] < result[-1]["end"]:
            current = result[-1]
            current["end"] = max(current["end"], finding["end"])
            if rank.get(finding["risk"], 0) > rank.get(current["risk"], 0):
                current["risk"] = finding["risk"]
            if finding["category"] not in current["category"].split("+"):
                current["category"] += "+" + finding["category"]
            current["id"] = "finding_" + digest({k: v for k, v in current.items() if k != "id"})[:16]
        else:
            result.append(dict(finding))
    return result


def sensitivity_signals(findings: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for finding in findings:
        grouped[finding["category"]].append(finding)
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return [{
        "category": category,
        "severity": max(items, key=lambda item: rank.get(item["risk"], 0))["risk"],
        "source_anchor_ids": sorted({item["source_anchor_id"] for item in items if item.get("source_anchor_id")}),
        "explanation": f"{len(items)} 处确定性命中；仅表示敏感性信号，不自动判断能否传输。",
    } for category, items in grouped.items()]


def risk_signals(texts: list[tuple[str | None, str]], pack: dict | None, ledger_count: int = 0, findings=None) -> list[dict]:
    findings = findings if findings is not None else [finding for anchor_id, text in texts for finding in detect_text(text, anchor_id, pack)]
    total = max(1, sum(len(text) for _, text in texts))
    weights = (pack or {}).get("risk_weights") or {}
    identifier_score = min(1.0, len(findings) / 3)
    density_score = min(1.0, sum(f["end"] - f["start"] for f in findings) / total * 10)
    context_hits = sum(text.count(term) for _, text in texts for term in (pack or {}).get("forbidden_terms", []))
    context_score = min(1.0, context_hits / 2)
    combination_score = min(1.0, (identifier_score + density_score + context_score) / 2)
    cross_round_score = min(1.0, ledger_count / 5)
    scores = {"entity": identifier_score, "density": density_score, "context": context_score, "combination": combination_score, "cross_round": cross_round_score}
    anchors = sorted({f["source_anchor_id"] for f in findings if f.get("source_anchor_id")})
    return [{"kind": kind, "score": round(score, 6), "weight": float(weights.get(kind, 0)),
             "source_anchor_ids": anchors,
             "explanation": ("冻结权重下的工程风险信号，不代表合规结论。" if kind in weights
                             else "风险权重尚未冻结；当前分项不得用于正式门禁结论。")} for kind, score in scores.items()]
