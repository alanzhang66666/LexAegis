"""Re-run layer A evaluate on isolated 10-case store with draft.2 pack. Never send."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / ".data" / "real_cases" / "runs" / "pilot-2026-09"
RUNTIME = PILOT / "runtime"
PASSWORD = "pilot-calibrate-local-only"
CASE_IDS = [
    "LA-001", "LA-002", "LA-003", "LA-004", "LA-005",
    "SMP-001", "SMP-002", "SMP-003", "SMP-004", "SMP-005",
]
PACK_ID = "pack:labor:2.0.0-draft.2"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def workbench_case_id(case_id: str):
    folder = PILOT / "cases" / case_id
    for name in ("run.reextract.json", "run.path-a.finish.json", "run.json"):
        path = folder / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workbench_case", "workbench_case_a"):
            if payload.get(key):
                return payload[key]
    return None


def public_eval(task: dict) -> dict:
    risk = task.get("risk") or {}
    request = task.get("request") or {}
    deps = request.get("dependencies") or {}
    decisions = task.get("decisions") or []
    transforms = {}
    for item in decisions:
        key = item.get("transform") or "unknown"
        transforms[key] = transforms.get(key, 0) + 1
    return {
        "task_id": task.get("id"),
        "status": task.get("status"),
        "transport": task.get("transport"),
        "pack_id": task.get("pack_id") or deps.get("pack"),
        "approval_allowed": risk.get("approval_allowed"),
        "completion": risk.get("completion"),
        "blockers": risk.get("blockers") or [],
        "n_blockers": len(risk.get("blockers") or []),
        "has_g5_residual": any("未替换的登记主体" in item for item in (risk.get("blockers") or [])),
        "findings": risk.get("findings") or [],
        "request_hash": task.get("request_hash"),
        "target": request.get("target"),
        "n_wire_facts": len(((request.get("wire_payload") or {}).get("facts")) or []),
        "decision_transforms": transforms,
        "n_decisions": len(decisions),
        "n_outputs": sum(1 for item in decisions if item.get("output")),
        "guide_version": "G-2026-09-12-v1.0",
        "send": "not_called",
    }


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from lexaegis.api import create_app
    from lexaegis.registry import import_pack, seed_packs
    from lexaegis.task_engine import run_fact_summary_draft

    app = create_app(RUNTIME, password=PASSWORD)
    rows = []
    with TestClient(app) as client:
        assert client.post("/api/v1/login", json={"password": PASSWORD}).status_code == 200
        with app.state.store.transaction() as repo:
            seed_packs(repo)
            raw = json.loads((ROOT / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
            if not any(item["id"] == PACK_ID for item in repo.list("pack")):
                import_pack(repo, raw)
        for case_id in CASE_IDS:
            dest = PILOT / "cases" / case_id
            workbench = workbench_case_id(case_id)
            row = {"case_id": case_id, "workbench_case": workbench, "send": "not_called"}
            if not workbench:
                row["result"] = "not_run"
                rows.append(row)
                continue
            created = client.post(
                f"/api/v1/cases/{workbench}/tasks",
                json={"transport": "cloud", "task_type": "fact_summary", "pack_id": PACK_ID},
            )
            if created.status_code != 200:
                row["result"] = "task_failed"
                row["http"] = created.status_code
                rows.append(row)
                continue
            task = created.json()
            evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
            if evaluated.status_code != 200:
                row["result"] = "evaluate_failed"
                row["http"] = evaluated.status_code
                rows.append(row)
                continue
            body = evaluated.json()
            summary = public_eval(body)
            write_json(dest / "cloud.A2.v1.summary.json", summary)
            write_json(dest / "cloud.A2.v1.full.json", {
                "risk": body.get("risk"),
                "request_hash": body.get("request_hash"),
                "status": body.get("status"),
                "request": {
                    "target": (body.get("request") or {}).get("target"),
                    "transport": (body.get("request") or {}).get("transport"),
                    "wire_payload": (body.get("request") or {}).get("wire_payload"),
                    "dependencies": (body.get("request") or {}).get("dependencies"),
                },
            })
            draft = run_fact_summary_draft(body.get("decisions") or task.get("decisions") or [])
            write_json(dest / "local.summary.A2.v1.json", {
                "provenance": "local_deterministic",
                "n_claims": len(draft.get("claims") or []),
                "n_unused": len(draft.get("unused_fact_ids") or []),
                "n_gaps": len(draft.get("gaps") or []),
                "guide_version": "G-2026-09-12-v1.0",
            })
            approve = client.post(
                f"/api/v1/tasks/{task['id']}/approve",
                json={"request_hash": body.get("request_hash")},
            )
            row.update({
                "result": "evaluated",
                "pack_id": summary["pack_id"],
                "status": summary["status"],
                "approval_allowed": summary["approval_allowed"],
                "n_blockers": summary["n_blockers"],
                "has_g5_residual": summary["has_g5_residual"],
                "n_wire_facts": summary["n_wire_facts"],
                "n_outputs": summary["n_outputs"],
                "n_claims": len(draft.get("claims") or []),
                "approve_http": approve.status_code,
            })
            rows.append(row)
            print(json.dumps({k: row[k] for k in row if k != "workbench_case"}, ensure_ascii=False), flush=True)
    report = {
        "guide_version": "G-2026-09-12-v1.0",
        "pack_id": PACK_ID,
        "dispatch_allowed": False,
        "send": "not_called",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cases": [{k: item[k] for k in item if k != "workbench_case"} for item in rows],
        "counts": {
            "evaluated": sum(1 for item in rows if item.get("result") == "evaluated"),
            "approve_409": sum(1 for item in rows if item.get("approve_http") == 409),
            "approval_allowed": sum(1 for item in rows if item.get("approval_allowed")),
            "g5_residual": sum(1 for item in rows if item.get("has_g5_residual")),
        },
    }
    write_json(PILOT / "coverage" / "layer-a-v1.json", report)
    print(json.dumps(report["counts"] | {"send": "not_called"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
