# SPDX-License-Identifier: Apache-2.0
# New LexAegis implementation following the Ianvs privacy-evaluation taxonomy.
"""Deterministic red-team evaluators operating only on attacker-visible data."""
from __future__ import annotations

import re


FORBIDDEN_KEYS = {"mapping", "mapping_entries", "original_value", "local_text", "anchors", "raw_text", "truth"}
TOKEN = re.compile(r"\[\[LEX:P\d{4,}\]\]")


def _assert_isolated_payload(value):
    if isinstance(value, dict):
        if FORBIDDEN_KEYS & {str(key).lower() for key in value}:
            raise ValueError("攻击载荷包含边侧专属数据")
        for child in value.values():
            _assert_isolated_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_isolated_payload(child)


def evaluate(protocol: dict, request: dict, history: list[dict], auxiliary: list[dict]) -> dict:
    _assert_isolated_payload({"request": request, "history": history, "auxiliary": auxiliary})
    kind = protocol["kind"]
    threshold = float(protocol["threshold"])
    text = str(request)
    if kind == "identity":
        guesses = sorted({str(item.get("candidate")) for item in auxiliary if item.get("candidate") and str(item.get("clue", "")) in text})
        score = 1 / len(guesses) if guesses else 0.0
        evidence = [f"由攻击者辅助数据得到 {len(guesses)} 个候选"]
    elif kind == "candidate_set":
        populations = [int(item["candidate_count"]) for item in auxiliary if str(item.get("candidate_count", "")).isdigit()]
        if not populations:
            return _result(kind, "uncertain", None, ["没有候选集合基线"])
        score = 1 / min(populations)
        evidence = [f"最小候选集合为 {min(populations)}"]
    elif kind == "sensitive_inference":
        scores = [float(item["confidence"]) for item in auxiliary if isinstance(item.get("confidence"), (int, float))]
        if not scores:
            return _result(kind, "uncertain", None, ["没有真实攻击器置信度"])
        score = max(scores)
        evidence = ["使用攻击者可见辅助数据中的真实置信度"]
    elif kind == "cross_round":
        current = set(TOKEN.findall(text))
        linked = sum(bool(current & set(TOKEN.findall(str(item)))) for item in history)
        score = min(1.0, linked / max(1, int(protocol.get("query_budget", 1))))
        evidence = [f"稳定 token 与 {linked} 轮历史披露可关联"]
    else:
        return _result(kind, "error", None, ["未知攻击类型"])
    return _result(kind, "succeeded" if score >= threshold else "resisted", score, evidence)


def _result(kind, outcome, score, evidence):
    return {"capability": "available", "completion": "complete" if outcome in ("resisted", "succeeded") else "incomplete",
            "outcome": outcome, "protocol": kind, "score": score, "evidence": evidence}
