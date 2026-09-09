# SPDX-License-Identifier: Apache-2.0
# New LexAegis implementation following the Ianvs privacy-evaluation taxonomy.
"""Engineering-baseline red-team executor: attacker and scorer are separate.

This module is not a formal attack conclusion and is not a legal endorsement.
The isolated red-team service must not receive mapping or ground-truth keys.
"""
from __future__ import annotations

import re
import time

from .util import digest

FORBIDDEN_KEYS = {"mapping", "mapping_entries", "original_value", "local_text", "anchors", "raw_text", "truth"}
TOKEN = re.compile(r"\[\[LEX:P\d{4,}\]\]")
PERSON_HINT = re.compile(r"(?:申请人|劳动者|职工|员工|原告|被告)(?P<name>[\u4e00-\u9fff]{2,4})")
ID_HINT = re.compile(r"\b\d{17}[\dXx]\b")
PHONE_HINT = re.compile(r"\b1[3-9]\d{9}\b")
AMOUNT_HINT = re.compile(r"(?:工资|加班费|报酬)(?P<value>\d{3,})")

EXECUTOR_VERSION = "lexaegis.attacks.executor/0.2-baseline"
SCORER_VERSION = "lexaegis.attacks.scorer/0.2-baseline"
AUXILIARY_LIBRARY_VERSION = "lexaegis.attacks.auxiliary/0.2"
BASELINE_NOTE = "工程基线执行器，不是正式攻击结论，不能作为法学背书"

# Known-vulnerable synthetic leak used only as a positive control.
POSITIVE_CONTROL_REQUEST = {
    "facts": [
        {
            "id": "fact_positive_control",
            "text": "申请人张三（身份证110101199001011234）主张加班工资12000元",
        }
    ]
}


def assert_isolated_payload(value):
    if isinstance(value, dict):
        if FORBIDDEN_KEYS & {str(key).lower() for key in value}:
            raise ValueError("攻击载荷包含边侧专属数据")
        for child in value.values():
            assert_isolated_payload(child)
    elif isinstance(value, list):
        for child in value:
            assert_isolated_payload(child)


def propose(protocol: dict, request: dict, history: list[dict], auxiliary: list[dict]) -> dict:
    """Attacker: emit candidates, ranking, predictions, and retrieval evidence only."""
    kind = protocol["kind"]
    query_budget = int(protocol.get("query_budget", 0))
    history = history[-query_budget:] if query_budget else []
    text = str(request)
    process = [f"读取攻击者视图 kind={kind}", "未向攻击器提供评分真值"]
    if kind == "identity":
        candidates = _identity_candidates(text, auxiliary)
        process.append(f"从披露文本与辅助线索检索到 {len(candidates)} 个身份候选")
        return _artifacts(kind, candidates, [], process, query_budget, history, text)
    if kind == "candidate_set":
        candidates = _identity_candidates(text, auxiliary)
        process.append(f"由检索证据构造候选集合，大小 {len(candidates)}，不读取传入的 candidate_count")
        return _artifacts(kind, candidates, [], process, query_budget, history, text)
    if kind == "sensitive_inference":
        predictions = _attribute_predictions(text, auxiliary)
        process.append(f"从披露文本与辅助线索得到 {len(predictions)} 条属性预测，不读取传入的 confidence")
        return _artifacts(kind, [], predictions, process, query_budget, history, text)
    if kind == "cross_round":
        current = set(TOKEN.findall(text))
        linked = [item for item in history if current and current & set(TOKEN.findall(str(item)))]
        process.append(f"在 {len(history)} 轮历史中检索到 {len(linked)} 轮稳定 token 关联")
        return {
            "kind": kind,
            "candidates": [],
            "ranking": [],
            "predictions": [],
            "retrieval": [f"shared_tokens={sorted(current)}", f"linked_rounds={len(linked)}"],
            "linked_rounds": len(linked),
            "has_history": bool(history),
            "has_tokens": bool(current),
            "process": process,
            "query_budget": query_budget,
            "history_used": len(history),
            "disclosed_text": text,
        }
    return {
        "kind": kind,
        "candidates": [],
        "ranking": [],
        "predictions": [],
        "retrieval": [],
        "process": process + ["未知攻击类型，攻击器未产出候选"],
        "query_budget": query_budget,
        "history_used": len(history),
        "disclosed_text": text,
        "unknown_kind": True,
    }


def score(protocol: dict, artifacts: dict, labels: dict | None = None) -> dict:
    """Scorer: read labels independently. Never trust attacker-supplied scores."""
    kind = artifacts.get("kind") or protocol["kind"]
    threshold = float(protocol["threshold"])
    criteria = protocol.get("success_criteria") or {}
    operator = criteria.get("operator", "gte")
    if artifacts.get("unknown_kind"):
        return {"outcome": "error", "score": None, "evidence": ["未知攻击类型"], "completion": "incomplete"}
    if operator not in ("gte", "gt", "lte", "lt"):
        return {"outcome": "error", "score": None, "evidence": ["success_criteria.operator 不受支持"], "completion": "incomplete"}
    labels = labels or {}
    text = str(artifacts.get("disclosed_text", ""))
    if kind == "identity":
        names = [item["candidate"] for item in artifacts.get("candidates") or []]
        if not names:
            return _uncertain("攻击器未产出身份候选，记为无能力，不得视为 resisted")
        expected = labels.get("identity")
        recovered = expected in names if expected else any(_leaked_identifier(name, text) for name in names)
        if expected and not recovered:
            return _compared(0.0, threshold, operator, [f"评分器对照真值，未恢复 {expected}"])
        if recovered:
            return _compared(1.0, threshold, operator, [f"评分器确认身份恢复：{names[0]}"])
        return _uncertain("有候选但无独立真值可核对，不能记为 resisted")
    if kind == "candidate_set":
        names = [item["candidate"] for item in artifacts.get("candidates") or []]
        if not names:
            return _uncertain("攻击器未产出候选集合，记为无能力，不得视为 resisted")
        expected = labels.get("identity")
        if expected and expected not in names:
            return _compared(0.0, threshold, operator, ["评分器对照真值，候选集合未覆盖主体"])
        return _compared(1 / len(names), threshold, operator, [f"评分器按攻击器集合计分，大小 {len(names)}"])
    if kind == "sensitive_inference":
        predictions = artifacts.get("predictions") or []
        if not predictions:
            return _uncertain("攻击器未产出属性预测，记为无能力，不得视为 resisted")
        expected = labels.get("attribute")
        if expected:
            matched = any(item.get("value") == expected or item.get("attribute") == expected for item in predictions)
            return _compared(1.0 if matched else 0.0, threshold, operator, ["评分器对照属性真值"])
        grounded = [item for item in predictions if str(item.get("value", "")) and str(item["value"]) in text]
        if not grounded:
            return _uncertain("属性预测缺少可核对的披露依据，不能记为 resisted")
        return _compared(max(float(item.get("confidence") or 0) for item in grounded), threshold, operator,
                         ["评分器按披露文本核对属性预测"])
    if kind == "cross_round":
        if not artifacts.get("has_history"):
            return _uncertain("没有跨轮历史，攻击器无能力，不得视为 resisted")
        if not artifacts.get("has_tokens"):
            return _uncertain("当前披露没有可关联 token，不能记为 resisted")
        budget = max(1, int(artifacts.get("query_budget") or protocol.get("query_budget") or 1))
        score = min(1.0, int(artifacts.get("linked_rounds") or 0) / budget)
        return _compared(score, threshold, operator, [f"评分器统计 {artifacts.get('linked_rounds', 0)} 轮可关联披露"])
    return {"outcome": "error", "score": None, "evidence": ["未知攻击类型"], "completion": "incomplete"}


def evaluate(protocol: dict, request: dict, history: list[dict], auxiliary: list[dict], labels: dict | None = None) -> dict:
    started = time.monotonic()
    assert_isolated_payload({"request": request, "history": history, "auxiliary": auxiliary})
    required_auxiliary = protocol.get("auxiliary_data", [])
    if required_auxiliary and not auxiliary:
        return _result(protocol.get("kind"), "uncertain", None, ["协议声明了辅助数据，但本次运行未提供"], 0, started,
                       request, history, auxiliary, ["辅助库为空"])
    artifacts = propose(protocol, request, history, auxiliary)
    judged = score(protocol, artifacts, labels)
    evidence = [BASELINE_NOTE, *artifacts.get("process", []), *judged.get("evidence", [])]
    return _result(artifacts.get("kind") or protocol.get("kind"), judged["outcome"], judged.get("score"), evidence,
                   artifacts.get("history_used", 0), started, request, history, auxiliary, artifacts.get("process", []),
                   artifacts)


def _identity_candidates(text: str, auxiliary: list[dict]) -> list[dict]:
    found = []
    seen = set()

    def add(candidate, evidence, rank):
        key = str(candidate).strip()
        if not key or key in seen:
            return
        seen.add(key)
        found.append({"candidate": key, "evidence": evidence, "rank": rank})

    for match in PERSON_HINT.finditer(text):
        add(match.group("name"), f"披露文本称谓后出现 {match.group('name')}", 1.1)
    for match in ID_HINT.finditer(text):
        add(match.group(0), "披露文本含身份证号", 1.0)
    for match in PHONE_HINT.finditer(text):
        add(match.group(0), "披露文本含手机号", 0.9)
    for item in auxiliary:
        candidate = item.get("candidate")
        clue = str(item.get("clue", ""))
        if candidate and clue and clue in text:
            add(candidate, f"辅助线索命中披露文本：{clue}", 0.8)
        elif candidate and str(candidate) in text:
            add(candidate, "辅助候选直接出现在披露文本", 0.85)
    found.sort(key=lambda item: (-item["rank"], item["candidate"]))
    return found


def _attribute_predictions(text: str, auxiliary: list[dict]) -> list[dict]:
    predictions = []
    for match in AMOUNT_HINT.finditer(text):
        predictions.append({
            "attribute": "wage",
            "value": match.group("value"),
            "confidence": 1.0,
            "evidence": f"披露文本含金额线索 {match.group('value')}",
        })
    for item in auxiliary:
        attribute = item.get("attribute")
        value = item.get("value")
        clue = str(item.get("clue", ""))
        if attribute and value is not None and clue and clue in text:
            predictions.append({
                "attribute": str(attribute),
                "value": str(value),
                "confidence": 0.8,
                "evidence": f"辅助属性线索命中：{clue}",
            })
    return predictions


def _leaked_identifier(name: str, text: str) -> bool:
    return bool(name) and name in text


def _artifacts(kind, candidates, predictions, process, query_budget, history, text):
    return {
        "kind": kind,
        "candidates": candidates,
        "ranking": [item["candidate"] for item in candidates],
        "predictions": predictions,
        "retrieval": [item.get("evidence") for item in candidates + predictions],
        "process": process,
        "query_budget": query_budget,
        "history_used": len(history),
        "disclosed_text": text,
    }


def _compared(score, threshold, operator, evidence):
    comparisons = {"gte": score >= threshold, "gt": score > threshold, "lte": score <= threshold, "lt": score < threshold}
    outcome = "succeeded" if comparisons[operator] else "resisted"
    return {"outcome": outcome, "score": score, "evidence": evidence, "completion": "complete"}


def _uncertain(message):
    return {"outcome": "uncertain", "score": None, "evidence": [message], "completion": "incomplete"}


def _result(kind, outcome, score, evidence, query_count, started, request, history, auxiliary, process, artifacts=None):
    duration_ms = int((time.monotonic() - started) * 1000) if started is not None else 0
    view_hash = digest({"request": request, "history": history, "auxiliary": auxiliary})
    return {
        "capability": "available",
        "completion": "complete" if outcome in ("resisted", "succeeded") else "incomplete",
        "outcome": outcome,
        "protocol": kind,
        "score": score,
        "evidence": evidence,
        "query_count": query_count,
        "duration_ms": duration_ms,
        "executor_version": EXECUTOR_VERSION,
        "scorer_version": SCORER_VERSION,
        "auxiliary_library_version": AUXILIARY_LIBRARY_VERSION,
        "attacker_view_hash": view_hash,
        "query_budget": int((artifacts or {}).get("query_budget") or 0),
        "process": process,
        "baseline": "engineering",
    }
