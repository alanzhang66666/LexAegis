"""Walk ten stable IDs through D-path evaluate. Never send."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / ".data" / "real_cases" / "runs" / "pilot-2026-09"
PUBLIC = ROOT / "docs" / "legal" / "十案D路径走一遍记录-2026-09-14.md"
RUNTIME_DB = PILOT / "runtime" / "app.sqlite"
WAREHOUSE_PACK = "pack:labor:2.0.0-draft.3"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_public_record(rows: list[dict], source: str) -> None:
    counts = {
        "local_only": sum(1 for item in rows if item.get("status") == "local_only"),
        "blocked": sum(1 for item in rows if item.get("status") == "blocked"),
        "candidate": sum(1 for item in rows if item.get("status") == "candidate"),
        "approval_allowed": sum(1 for item in rows if item.get("approval_allowed")),
        "http_send": 0,
    }
    lines = [
        "# 十案 D 路径走一遍记录（2026-09-14）",
        "",
        "- 来源：" + source,
        "- 安排：[十案上云安排-D-2026-09-14.md](十案上云安排-D-2026-09-14.md)",
        "- 走一遍 ≠ 已发送。仓库包仍 draft，`dispatch_allowed=false`。",
        "- 公开只记计数与状态。当事人姓名、案号、事实原文不进本页。",
        "- 现状：**10 案层 A 评估完成，0 案真实发送。**",
        "",
        "| 计数 | 值 |",
        "| --- | --- |",
        f"| local_only | {counts['local_only']} |",
        f"| blocked | {counts['blocked']} |",
        f"| candidate | {counts['candidate']} |",
        f"| 本地草稿 approval_allowed（非发送） | {counts['approval_allowed']} |",
        f"| 真实案 HTTP | {counts['http_send']} |",
        "",
        "| 案号 | 批次 | 传输 | 子目的 | 状态 | 云端可批准 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in rows:
        purpose = item.get("sub_purpose") or "（本地/默认）"
        cloud_ok = item.get("approval_allowed") if item.get("transport") != "local" else "不适用（本地）"
        lines.append(
            f"| {item['case_id']} | {item.get('batch')} | {item.get('transport')} | {purpose} | "
            f"{item.get('status')} | {cloud_ok} |"
        )
    lines.extend(["", "**10 案层 A 评估完成，0 案真实发送。**", ""])
    PUBLIC.write_text("\n".join(lines), encoding="utf-8")


def synthetic_walk() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from lexaegis.d_path import WALK_BATCHES, public_walk_row
    from lexaegis.disclosure import GENERAL_SUB_PURPOSE
    from lexaegis.local_rules import decide_facts
    from lexaegis.policy import assess
    from lexaegis.registry import validate_pack

    raw = json.loads((ROOT / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
    pack = validate_pack(raw).model_dump()
    assert pack["dispatch_allowed"] is False
    mappings = [{"original_value": "甲", "wire_token": "[[LEX:P0001]]"}]
    rows = []
    for batch in WALK_BATCHES:
        facts = [
            {"id": "r1", "field": "relation", "value": "[[LEX:P0001]]与相对方存在劳动关系", "confirmed": True, "stale": False, "source_ids": []},
            {"id": "e1", "field": "event", "value": "[[LEX:P0001]]主张争议经过", "confirmed": True, "stale": False, "source_ids": []},
        ]
        decisions = decide_facts(facts, pack, mappings, batch["sub_purpose"] or GENERAL_SUB_PURPOSE)
        case = {"mode": "formal", "ledger_version": 0, "mapping_entries": mappings, "source_case_id": batch["case_id"]}
        docs = [{"status": "ready", "ir": {"needs_review": False, "blocks": []}}]
        risk = assess(case, pack, facts, decisions, docs, [], batch["transport"])
        rows.append(public_walk_row(batch, risk, {"pack_id": WAREHOUSE_PACK, "result": "synthetic"}))
    return rows


def _bind_source(repo, case, source_id):
    if case.get("source_case_id") == source_id:
        return case
    updated = dict(case)
    updated["source_case_id"] = source_id
    repo.put("case", updated)
    return updated


def _evaluate_one(repo, batch, case):
    from lexaegis.d_path import public_walk_row
    from lexaegis.service import DomainError, approve_task, create_task, evaluate_task

    case = _bind_source(repo, case, batch["case_id"])
    facts = repo.list("fact", case["id"])
    extra = {
        "n_facts": len(facts),
        "n_confirmed": sum(1 for item in facts if item.get("confirmed")),
        "result": "evaluated",
        "send": "not_called",
        "http_send": 0,
    }
    task = create_task(repo, case["id"], batch["transport"], "fact_summary", None, batch["sub_purpose"])
    task = evaluate_task(repo, task["id"])
    risk = task.get("risk") or {}
    policy = (task.get("request") or {}).get("policy") or {}
    extra["n_outputs"] = sum(1 for item in task.get("decisions") or [] if item.get("output"))
    extra["n_wire"] = len(((task.get("request") or {}).get("wire_payload") or {}).get("facts") or [])
    extra["pack_id"] = task.get("pack_id")
    extra["demo_exception"] = bool(policy.get("demo_exception") or risk.get("demo_exception"))
    extra["n_blockers"] = len(risk.get("blockers") or [])
    if extra["demo_exception"]:
        raise RuntimeError("demo_exception must not attach to LA/SMP formal cases")
    if batch["transport"] == "cloud":
        try:
            approve_task(repo, task["id"], task.get("request_hash") or "")
            extra["approve_http"] = 200
        except DomainError:
            extra["approve_http"] = 409
    row = public_walk_row(batch, risk, extra)
    row["blocker_kinds"] = list(risk.get("blockers") or [])
    return row


def pilot_walk() -> dict:
    if not RUNTIME_DB.exists():
        return {"result": "pilot_store_absent", "send": "not_called", "http_send": 0, "rows": []}

    sys.path.insert(0, str(ROOT))
    os.environ["LEX_CLOUD_PATH"] = "D"
    from lexaegis.d_path import WALK_BATCHES, pick_walk_case, public_walk_row
    from lexaegis.storage import Store

    store = Store(RUNTIME_DB)
    with store.read() as repo:
        cases = repo.list("case")
        facts_by = {item["id"]: repo.list("fact", item["id"]) for item in cases}

    rows = []
    for batch in WALK_BATCHES:
        picked = pick_walk_case(cases, batch["case_id"], facts_by)
        if picked is None:
            row = public_walk_row(batch, {"approval_allowed": False, "demo_exception": False}, {
                "result": "case_not_in_store",
                "pack_id": WAREHOUSE_PACK,
            })
            row["status"] = "blocked"
            rows.append(row)
            write_json(PILOT / "cases" / batch["case_id"] / "d-path.summary.json", row)
            continue
        with store.transaction() as repo:
            row = _evaluate_one(repo, batch, repo.get(picked["id"], "case"))
        write_json(PILOT / "cases" / batch["case_id"] / "d-path.summary.json", row)
        rows.append(row)

    return {
        "result": "pilot_store_evaluated",
        "send": "not_called",
        "http_send": 0,
        "rows": rows,
    }


def main() -> int:
    sys.path.insert(0, str(ROOT))
    synthetic = synthetic_walk()
    pilot = pilot_walk()
    if pilot.get("result") == "pilot_store_evaluated" and len(pilot.get("rows") or []) == 10:
        rows = pilot["rows"]
        source = "隔离库 Path A 候选（公开计数，无当事人姓名/案号）"
    else:
        rows = synthetic
        source = (
            "合成 token 卡（无真实姓名/案号；隔离库不存在或不足十案）"
            if pilot.get("result") == "pilot_store_absent"
            else "合成 token 卡（无真实姓名/案号）"
        )
    write_public_record(rows, source)
    coverage = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pack_id": WAREHOUSE_PACK,
        "dispatch_allowed": False,
        "send": "not_called",
        "http_send": 0,
        "source": source,
        "pilot": {key: pilot[key] for key in ("result", "send", "http_send")},
        "cases": rows,
    }
    write_json(PILOT / "coverage" / "d-path-walk.json", coverage)
    print(json.dumps({
        "rows": len(rows),
        "source": source,
        "send": "not_called",
        "http_send": 0,
        "pilot": coverage["pilot"]["result"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
