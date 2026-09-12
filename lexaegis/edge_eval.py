"""Engineering-only edge extract probe. Does not score legal availability."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .data_registry import find_dataset
from .dataset import read_records_jsonl
from .providers import FACT_FIELDS, FACT_ROLES, EdgeClient
from .util import app_dir, now, restrict_mode

NUMBERS = re.compile(r"\d+(?:\.\d+)?")
ENGINEERING_CHECKS = (
    "json_valid",
    "source_ids_in_blocks",
    "quote_is_substring",
    "numbers_from_source",
    "aliases_no_conflict",
    "field_in_enum",
    "role_in_enum",
)


def default_probe_path(dataset_id: str) -> Path:
    return Path(".data") / "edge-probe" / f"{dataset_id}.json"


def _block_index(blocks):
    return {block["id"]: block.get("text") or "" for block in blocks}


def aliases_conflict(facts) -> bool:
    claimed: dict[str, str] = {}
    for fact in facts:
        value = fact.get("value") or ""
        names = [value, *(fact.get("aliases") or [])]
        for name in names:
            if not name:
                continue
            previous = claimed.get(name)
            if previous is not None and previous != value:
                return True
            claimed[name] = value
    return False


def numbers_from_source(fact, texts) -> bool:
    blob = " ".join(filter(None, [fact.get("value"), fact.get("normalized"), fact.get("quote")]))
    source = "".join(texts.get(source_id, "") for source_id in fact.get("source_ids") or [])
    return all(number in source for number in NUMBERS.findall(blob))


def quote_is_substring(fact, texts) -> bool:
    quote = fact.get("quote")
    if not quote:
        return False
    return any(quote in texts.get(source_id, "") for source_id in fact.get("source_ids") or [])


def role_in_enum(fact) -> bool:
    role = fact.get("role", "unknown")
    return role in FACT_ROLES


def score_extract(blocks, facts) -> dict:
    texts = _block_index(blocks)
    valid_ids = set(texts)
    issues = []
    source_ok = True
    quote_ok = True
    numbers_ok = True
    role_ok = True
    if not isinstance(facts, list):
        return {
            "json_valid": False,
            "source_ids_in_blocks": False,
            "quote_is_substring": False,
            "numbers_from_source": False,
            "aliases_no_conflict": False,
            "field_in_enum": False,
            "role_in_enum": False,
            "fact_count": 0,
            "issues": ["返回不是 facts 数组"],
        }
    field_ok = True
    for fact in facts:
        if not isinstance(fact, dict):
            issues.append("事实条目不是对象")
            source_ok = quote_ok = numbers_ok = field_ok = role_ok = False
            continue
        if fact.get("field") not in FACT_FIELDS:
            field_ok = False
            issues.append("field 不是允许枚举")
        ids = fact.get("source_ids") or []
        if not ids or not set(ids) <= valid_ids:
            source_ok = False
            issues.append("source_ids 未落在输入块内")
        if not quote_is_substring(fact, texts):
            quote_ok = False
            issues.append("quote 缺失或不是来源块子串")
        if not role_in_enum(fact):
            role_ok = False
            issues.append("role 不是允许枚举")
        if not numbers_from_source(fact, texts):
            numbers_ok = False
            issues.append("数字未出现在来源块原文")
    alias_ok = not aliases_conflict(facts)
    if not alias_ok:
        issues.append("别名与其他主体冲突")
    return {
        "json_valid": True,
        "source_ids_in_blocks": source_ok,
        "quote_is_substring": quote_ok,
        "numbers_from_source": numbers_ok,
        "aliases_no_conflict": alias_ok,
        "field_in_enum": field_ok,
        "role_in_enum": role_ok,
        "fact_count": len(facts),
        "issues": list(dict.fromkeys(issues)),
    }


def _unconfigured_report(dataset_id, manifest, records, detail):
    return {
        "kind": "edge_extract_engineering_probe",
        "status": "unconfigured",
        "dataset_id": dataset_id,
        "dataset_version": manifest.version,
        "record_count": len(records),
        "scoring": {"kind": "engineering_only", "legal_availability": "not_scored"},
        "legal_availability": "not_scored",
        "detail": detail,
        "checks": ENGINEERING_CHECKS,
        "records": [],
        "probed_at": now(),
        "output_dir": str(app_dir()),
    }


def probe_edge(dataset_id="mock_labor", extract=None, timeout=120) -> dict:
    path, manifest = find_dataset(dataset_id)
    records = read_records_jsonl(path.parent / manifest.records_path)
    model = os.getenv("LEX_EDGE_MODEL", "")
    url = os.getenv("LEX_EDGE_URL", "http://127.0.0.1:8080/v1")
    if extract is None:
        if not model:
            return _unconfigured_report(dataset_id, manifest, records, "边侧未配置，跳过抽取探测")
        client = EdgeClient(url, model)
        health = client.health()
        if health.get("status") != "available":
            return _unconfigured_report(dataset_id, manifest, records, health.get("detail") or "边侧服务未启动")
        extract = lambda blocks, _timeout=timeout: client.extract(blocks, timeout=_timeout)
    rows = []
    for record in records:
        blocks = record["document"]["blocks"]
        try:
            facts = extract(blocks)
            score = score_extract(blocks, facts)
        except Exception as error:
            message = str(error)
            score = {
                "json_valid": False,
                "source_ids_in_blocks": False,
                "quote_is_substring": False,
                "numbers_from_source": False,
                "aliases_no_conflict": False,
                "field_in_enum": False,
                "role_in_enum": False,
                "fact_count": 0,
                "issues": [message[:300]],
            }
        rows.append({"id": record["id"], **score, "legal_availability": "not_scored"})
    totals = {name: sum(1 for row in rows if row.get(name)) for name in ENGINEERING_CHECKS}
    return {
        "kind": "edge_extract_engineering_probe",
        "status": "complete",
        "dataset_id": dataset_id,
        "dataset_version": manifest.version,
        "record_count": len(records),
        "scoring": {"kind": "engineering_only", "legal_availability": "not_scored"},
        "legal_availability": "not_scored",
        "checks": ENGINEERING_CHECKS,
        "totals": totals,
        "records": rows,
        "probed_at": now(),
    }


def write_probe_report(report, destination=None) -> Path:
    path = Path(destination) if destination else default_probe_path(report["dataset_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    restrict_mode(path, 0o600)
    return path
