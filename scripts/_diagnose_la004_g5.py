"""Diagnose LA-004 empty outputs and registered-name hits without printing names."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lexaegis.disclosure import GENERAL_SUB_PURPOSE
from lexaegis.local_rules import decide_facts, fallback_for
from lexaegis.registry import validate_pack
from lexaegis.storage import Store

PILOT = ROOT / ".data" / "real_cases" / "runs" / "pilot-2026-09"


def workbench_id(case_id="LA-004"):
    for name in ("run.reextract.json", "run.path-a.finish.json", "run.json"):
        path = PILOT / "cases" / case_id / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workbench_case", "workbench_case_a"):
            if payload.get(key):
                return payload[key]
    raise SystemExit("no workbench case")


def main() -> None:
    pack = validate_pack(json.loads((ROOT / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))).model_dump()
    store = Store(PILOT / "runtime" / "app.sqlite")
    case_id = workbench_id()
    with store.read() as repo:
        facts = list(repo.list("fact", case_id))
        case = repo.get(case_id, "case")
        mappings = case.get("mapping_entries") or []
    decisions = decide_facts(facts, pack, mappings, GENERAL_SUB_PURPOSE)
    names = []
    for entry in mappings:
        names.append(entry.get("original_value") or "")
        names.extend(entry.get("aliases") or [])
    names = [name for name in names if name]
    usable = [name for name in names if len(name) >= 2]
    empty_fields = Counter()
    empty_reasons = Counter()
    hit_name_lens = Counter()
    hit_fields = Counter()
    for fact, decision in zip(facts, decisions):
        output = decision.get("output") or ""
        if not output:
            empty_fields[fact.get("field")] += 1
            reasons = decision.get("block_reasons") or ["no_reason"]
            empty_reasons[reasons[0][:80] if reasons else "none"] += 1
            continue
        for name in usable:
            if name in output:
                hit_name_lens[len(name)] += 1
                hit_fields[fact.get("field")] += 1
                break
    report = {
        "case_id": "LA-004",
        "n_facts": len(facts),
        "n_mappings": len(mappings),
        "n_registered_names": len(names),
        "n_usable_names": len(usable),
        "n_usable_name_hits": sum(
            1 for item in decisions
            if item.get("output") and any(name in (item.get("output") or "") for name in usable)
        ),
        "name_len_min": min((len(name) for name in names), default=0),
        "name_len_max": max((len(name) for name in names), default=0),
        "n_short_names_lt2": sum(1 for name in names if len(name) < 2),
        "n_short_names_lt3": sum(1 for name in names if len(name) < 3),
        "n_output": sum(1 for item in decisions if item.get("output")),
        "empty_by_field": dict(empty_fields),
        "empty_reason_top": empty_reasons.most_common(8),
        "hit_name_lens": dict(hit_name_lens),
        "hit_fields": dict(hit_fields),
        "send": "not_called",
    }
    out = PILOT / "coverage" / "la004-g5-diagnose.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
