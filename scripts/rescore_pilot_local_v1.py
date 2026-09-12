"""Rescore isolated 10-case layer-A artifacts with G-2026-09-12-v1.0 local rules.

Does not send, approve, or print party names or judgment excerpts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lexaegis.disclosure import GENERAL_SUB_PURPOSE, GUIDE_VERSION
from lexaegis.local_rules import decide_facts, evaluate_path_c, evaluate_syn_local_001, task_result_status
from lexaegis.registry import validate_pack

PILOT = ROOT / ".data" / "real_cases" / "runs" / "pilot-2026-09"
RUNTIME = PILOT / "runtime" / "app.sqlite"
CASE_IDS = [
    "LA-001", "LA-002", "LA-003", "LA-004", "LA-005",
    "SMP-001", "SMP-002", "SMP-003", "SMP-004", "SMP-005",
]
RUN_FILES = ("run.reextract.json", "run.path-a.finish.json", "run.json")


def load_pack():
    raw = json.loads((ROOT / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
    pack = validate_pack(raw).model_dump()
    if pack.get("dispatch_allowed"):
        raise SystemExit("refusing to rescore with dispatch_allowed=true")
    return pack


def _facts_from_extract(payload):
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("facts") or payload.get("proposed_facts") or []
    else:
        items = []
    facts = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("value") or not item.get("field"):
            continue
        facts.append({
            "id": item.get("id") or f"x{index+1}",
            "field": item["field"],
            "value": item["value"],
            "source_ids": item.get("source_ids") or ["unknown"],
            "confirmed": bool(item.get("confirmed")),
            "quote": item.get("quote"),
        })
    return facts


def workbench_case_id(case_id):
    folder = PILOT / "cases" / case_id
    for name in RUN_FILES:
        path = folder / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workbench_case", "workbench_case_a"):
            value = payload.get(key)
            if value:
                return value, name
    return None, None


def load_case_facts(store, case_id):
    workbench_id, source = workbench_case_id(case_id)
    if workbench_id and store is not None:
        with store.read() as repo:
            facts = [dict(item) for item in repo.list("fact", workbench_id)]
            case = repo.get(workbench_id, "case")
            mappings = case.get("mapping_entries") or []
        if facts:
            return facts, mappings, source, "runtime"
    folder = PILOT / "cases" / case_id
    for name in ("extract.raw.json", "run.reextract.json", "run.json"):
        path = folder / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        facts = _facts_from_extract(payload)
        if facts:
            return facts, [], name, "file"
    return [], [], source, "not_run"


def rescore_case(pack, store, case_id):
    facts, mappings, source, status = load_case_facts(store, case_id)
    if status == "not_run":
        return {
            "case_id": case_id,
            "result_status": "not_run",
            "n_facts": 0,
            "n_output": 0,
            "source": source,
            "send": "not_called",
        }
    decisions = decide_facts(facts, pack, mappings, GENERAL_SUB_PURPOSE)
    registered = [
        entry.get("original_value") for entry in mappings
        if entry.get("original_value") and len(entry.get("original_value") or "") >= 2
    ]
    name_hits = 0
    for decision in decisions:
        output = decision.get("output") or ""
        if any(name and name in output for name in registered):
            name_hits += 1
    return {
        "case_id": case_id,
        "result_status": task_result_status(decisions, facts),
        "n_facts": len(facts),
        "n_output": sum(1 for item in decisions if item.get("output")),
        "n_restricted": sum(1 for item in decisions if item.get("status") == "restricted"),
        "n_registered_name_hits": name_hits,
        "n_confirmed": sum(1 for item in facts if item.get("confirmed")),
        "source": source,
        "origin": status,
        "send": "not_called",
        "dispatch_allowed": False,
    }


def main():
    pack = load_pack()
    store = None
    if RUNTIME.exists():
        from lexaegis.storage import Store
        store = Store(RUNTIME)
    syn = evaluate_syn_local_001(pack)
    path_c = evaluate_path_c(pack)
    cases = [rescore_case(pack, store, case_id) for case_id in CASE_IDS]
    report = {
        "guide_version": GUIDE_VERSION,
        "pack_version": pack["version"],
        "pack_status": pack["status"],
        "dispatch_allowed": False,
        "send": "not_called",
        "syn_local_001": {key: syn[key] for key in syn if key != "failures" or syn["failures"]},
        "path_c": [
            {
                "id": item["id"],
                "name": item["name"],
                "passed": item["passed"],
                "result_status": item["result_status"],
                "cloud": False,
                "dispatch_allowed": False,
                **({"failures": item["failures"]} if item.get("failures") else {}),
            }
            for item in path_c
        ],
        "pilot_cases": cases,
        "counts": {
            "pilot_complete": sum(1 for item in cases if item["result_status"] == "complete"),
            "pilot_partial": sum(1 for item in cases if item["result_status"] == "partial"),
            "pilot_blocked": sum(1 for item in cases if item["result_status"] == "blocked"),
            "pilot_not_run": sum(1 for item in cases if item["result_status"] == "not_run"),
            "path_c_passed": sum(1 for item in path_c if item["passed"]),
            "path_c_total": len(path_c),
            "syn_passed": syn["passed"],
        },
    }
    out_dir = PILOT / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "local-v1-rescore.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"] | {"out": str(path), "send": "not_called"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
