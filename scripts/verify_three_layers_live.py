"""Verify the three progressive review layers against a running demo workbench.

The script uses only bundled synthetic scenarios and mock execution.  It requires
LEX_DEMO_LIVE_EDGE_REVIEW=1 on the running workbench and refuses to count a fixed
fixture as model evidence.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def require(response: httpx.Response, expected=(200,)):
    if response.status_code not in expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url}: "
            f"HTTP {response.status_code}: {response.text[:500]}"
        )
    return response.json() if response.content else None


class ThreeLayerVerifier:
    def __init__(self, base_url: str, password: str, timeout: float):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, trust_env=False,
            follow_redirects=False,
        )
        self.password = password
        self.users: dict[str, tuple[str, str]] = {}
        self.results: list[dict] = []

    def close(self):
        self.client.close()

    def login_admin(self):
        self.client.post("/api/v1/logout")
        require(self.client.post("/api/v1/login", json={"password": self.password}))

    def ensure_user(self, role: str):
        username = f"three-layer.{role}"
        password = f"three-layer-{role}-password-123"
        self.login_admin()
        response = self.client.post("/api/v1/users", json={
            "username": username, "display_name": username,
            "role": role, "password": password,
        })
        if response.status_code not in (200, 409):
            require(response)
        self.users[role] = (username, password)

    def login_as(self, role: str):
        username, password = self.users[role]
        self.client.post("/api/v1/logout")
        require(self.client.post(
            "/api/v1/login", json={"username": username, "password": password}
        ))

    def create_task(self, scenario: str):
        self.login_admin()
        case = require(self.client.post("/api/v1/demos", json={"scenario": scenario}))
        task = require(self.client.post(
            f"/api/v1/cases/{case['id']}/tasks", json={"transport": "mock"}
        ))
        evaluated = require(self.client.post(f"/api/v1/tasks/{task['id']}/evaluate"))
        review = evaluated.get("edge_review") or {}
        if not str(review.get("source") or "").startswith("live_edge_model") or review.get("status") != "complete":
            raise RuntimeError(
                f"{scenario}: edge review is not completed live-model evidence: {review}"
            )
        return case, evaluated

    def pack_refs(self, task: dict):
        packs = require(self.client.get("/api/v1/domains"))
        pack = next(item for item in packs if item["id"] == task["pack_id"])
        conditions = pack.get("manual_review_conditions") or [
            condition for rule in pack.get("rules", [])
            for condition in rule.get("conditions", [])
        ]
        return conditions, pack.get("legal_sources") or []

    def review_body(self, case_id: str, task: dict, conclusion: str, suffix: str):
        detail = require(self.client.get(f"/api/v1/cases/{case_id}"))
        conditions, sources = self.pack_refs(task)
        return {
            "request_hash": task["request_hash"],
            "material_version": detail["case"]["revision"],
            "idempotency_key": f"three-layer-{suffix}-{task['id']}",
            "conclusion": conclusion,
            "reason": (
                "组合线索仍可识别特定主体，人工否决本次合成请求。"
                if conclusion == "reject_current_request" else
                "已核对合成事实和最小化范围，允许本次离线模拟处理。"
            ),
            "evidence_ids": [task["fact_snapshot"][0]["id"]],
            "reviewed_condition_ids": [conditions[0]["id"]],
            "legal_source_ids": [sources[0]["id"]],
            "acknowledged_risk_notices": True,
            "scope_note": "仅适用于当前合成请求，不授予正式发送权。",
            "fact_premise": "材料为随包合成场景。",
            "authority_judgment": "人工复核结论仅约束当前请求。",
            "external_processing_note": "只执行本地 mock，不调用外部服务。",
            "minimization_note": "原文留在本地，仅处理最小化候选事实。",
            "final_basis": "结合当前材料版本、模型审核及所选合成证据判断。",
        }

    @staticmethod
    def evidence(layer: str, scenario: str, task: dict, human: str, final: str):
        review = task["edge_review"]
        return {
            "layer": layer,
            "scenario": scenario,
            "edge_decision": review["decision"],
            "model_decision": review.get("model_decision", review["decision"]),
            "edge_source": review["source"],
            "edge_status": review["status"],
            "edge_model": review.get("model"),
            "edge_response_hash": review.get("response_hash"),
            "safety_floor_applied": bool((review.get("safety_floor") or {}).get("applied")),
            "human_review": human,
            "final_state": final,
            "request_hash": task.get("request_hash"),
        }

    def layer_one(self):
        _case, task = self.create_task("linkage")
        review = task["edge_review"]
        if review["decision"] != "block_external":
            raise RuntimeError("layer 1: final edge review did not block")
        if review.get("model_decision", review["decision"]) != "block_external":
            raise RuntimeError("layer 1: model itself did not block; policy-floor-only evidence is insufficient")
        if task["risk"]["approval_allowed"] is not False:
            raise RuntimeError("layer 1: approval unexpectedly allowed")
        self.results.append(self.evidence(
            "1_edge_blocks", "linkage", task, "not_reached", task["status"]
        ))

    def layer_two(self):
        case, task = self.create_task("human_veto")
        if task["edge_review"]["decision"] != "allow_human_review":
            raise RuntimeError("layer 2: live edge model did not allow human review")
        self.login_as("legal_reviewer")
        rejected = require(self.client.post(
            f"/api/v1/tasks/{task['id']}/legal-review",
            json=self.review_body(case["id"], task, "reject_current_request", "reject"),
        ))
        self.login_as("approver")
        approval = self.client.post(
            f"/api/v1/tasks/{task['id']}/approve",
            json={"request_hash": task["request_hash"]},
        )
        self.login_admin()
        sending = self.client.post(f"/api/v1/tasks/{task['id']}/send")
        if approval.status_code != 409 or sending.status_code != 409:
            raise RuntimeError(
                f"layer 2: veto bypass: approve={approval.status_code}, send={sending.status_code}"
            )
        rejected["edge_review"] = task["edge_review"]
        rejected["request_hash"] = task["request_hash"]
        self.results.append(self.evidence(
            "2_human_rejects", "human_veto", rejected,
            "reject_current_request", rejected["status"],
        ))

    def layer_three(self):
        case, task = self.create_task("success")
        if task["edge_review"]["decision"] != "allow_human_review":
            raise RuntimeError("layer 3: live edge model did not allow human review")
        self.login_as("legal_reviewer")
        require(self.client.post(
            f"/api/v1/tasks/{task['id']}/legal-review",
            json=self.review_body(case["id"], task, "allow_processing", "allow"),
        ))
        self.login_as("approver")
        require(self.client.post(
            f"/api/v1/tasks/{task['id']}/approve",
            json={"request_hash": task["request_hash"]},
        ))
        self.login_admin()
        require(self.client.post(f"/api/v1/tasks/{task['id']}/send"))
        final = None
        for _ in range(120):
            detail = require(self.client.get(f"/api/v1/cases/{case['id']}"))
            final = next(item for item in detail["tasks"] if item["id"] == task["id"])
            if final["status"] not in {"queued", "sending"}:
                break
            time.sleep(0.5)
        if not final or final["status"] != "complete":
            raise RuntimeError(f"layer 3: offline result did not complete: {final}")
        if (final.get("artifact") or {}).get("provenance") != "simulation":
            raise RuntimeError("layer 3: result is not the expected offline simulation")
        final["edge_review"] = task["edge_review"]
        final["request_hash"] = task["request_hash"]
        self.results.append(self.evidence(
            "3_model_and_human_allow", "success", final,
            "allow_processing", final["status"],
        ))


def main(argv=None):
    parser = argparse.ArgumentParser(description="验证真实边侧模型驱动的三层比赛流程")
    parser.add_argument("--base-url", default="http://127.0.0.1:48765")
    parser.add_argument("--password", required=True)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    verifier = ThreeLayerVerifier(args.base_url, args.password, args.timeout)
    try:
        health = require(verifier.client.get("/api/v1/health"))
        for role in ("legal_reviewer", "approver"):
            verifier.ensure_user(role)
        verifier.layer_one()
        verifier.layer_two()
        verifier.layer_three()
        report = {
            "schema_version": 1,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "runtime_profile": health.get("runtime_profile") or health.get("profile"),
            "formal_dispatch": "blocked",
            "three_layers": verifier.results,
            "status": "passed",
        }
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0
    finally:
        verifier.close()


if __name__ == "__main__":
    raise SystemExit(main())
