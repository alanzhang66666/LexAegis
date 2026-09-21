"""LexAegis contract adaptation for the pinned Unsloth Qwen3-4B GRPO recipe.

This module rewards output-contract compliance and evidence grounding only. It does
not reward legal conclusions, and it must never be trained on real case material.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lexaegis.task_engine import request_system_prompt, validate_cloud_result


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = ROOT / "data" / "mock_labor_v1" / "records.jsonl"
TOKEN = re.compile(r"\[\[LEX:[A-Z]+\d+\]\]")


def _assert_safe_record(record: dict[str, Any]) -> None:
    if record.get("synthetic") is not True:
        raise ValueError("GRPO 适配只接受 synthetic=true 的记录")
    provenance = record.get("provenance") or {}
    if provenance.get("contains_real_case_content") is not False:
        raise ValueError("GRPO 适配拒绝真实案件或来源不明记录")
    if (record.get("task") or {}).get("id") != "fact_summary":
        raise ValueError("GRPO 适配仅支持 fact_summary v2")


def project_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project one frozen synthetic record into prompt, facts and a format target."""
    _assert_safe_record(record)
    facts = [
        {
            "id": item["id"],
            "field": item["field"],
            "value": item["text"],
            "source_ids": list(item.get("source_ids") or []),
        }
        for item in record.get("facts") or []
    ]
    if not facts:
        raise ValueError("GRPO 适配记录没有事实")
    wire = {
        "contract_version": 2,
        "task": {"id": "fact_summary", "version": "2.0"},
        "facts": facts,
    }
    target = {
        "claims": [
            {"text": fact["value"], "source_ids": [fact["id"]]}
            for fact in facts
        ],
        "unused_fact_ids": [],
        "gaps": [],
    }
    return {
        "record_id": record["id"],
        "prompt": [
            {"role": "system", "content": request_system_prompt("fact_summary")},
            {"role": "user", "content": json.dumps(wire, ensure_ascii=False, sort_keys=True)},
        ],
        "facts": facts,
        "reference_completion": json.dumps(target, ensure_ascii=False, sort_keys=True),
        "data_origin": "bundled_fully_synthetic",
        "training_scope": "output_contract_and_evidence_grounding_only",
        "legal_annotation_status": (record.get("annotations") or {}).get("status", "unknown"),
    }


def load_projected_records(path: Path = DEFAULT_RECORDS) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(project_record(json.loads(line)))
    return rows


def _completion_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("content", ""))
    if isinstance(value, list) and value:
        return _completion_text(value[-1])
    return ""


def _parse_completion(value: Any) -> dict[str, Any]:
    text = _completion_text(value).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("completion 不是 JSON object")
    return result


def _task_and_facts(facts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = [
        {
            "id": item["id"],
            "field": item.get("field", "event"),
            "value": item["value"],
            "source_ids": list(item.get("source_ids") or []),
        }
        for item in facts
    ]
    task = {
        "decisions": [
            {"fact_id": item["id"], "output": item["value"]}
            for item in normalized
        ]
    }
    return task, normalized


def score_completion(completion: Any, facts: list[dict[str, Any]]) -> float:
    """Return a deterministic 0..1 contract/grounding reward."""
    try:
        raw = _parse_completion(completion)
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    score = 0.1
    try:
        task, normalized = _task_and_facts(facts)
        checked = validate_cloud_result("fact_summary", raw, task, normalized)
    except (KeyError, TypeError, ValueError):
        return score
    score += 0.2
    claims = checked.get("claims") or []
    if claims:
        matched = sum(item.get("status") == "source_matched" for item in claims) / len(claims)
        score += 0.5 * matched
    if not checked.get("feedback_issues"):
        score += 0.1
    input_tokens = set(TOKEN.findall("\n".join(item["value"] for item in normalized)))
    output_tokens = set(TOKEN.findall(json.dumps(raw, ensure_ascii=False)))
    if output_tokens <= input_tokens:
        score += 0.1
    return round(min(score, 1.0), 6)


def contract_grounding_reward(completions, facts, **_kwargs) -> list[float]:
    """TRL/Unsloth-compatible batch reward function."""
    return [score_completion(completion, sample_facts) for completion, sample_facts in zip(completions, facts)]
