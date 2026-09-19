"""Two real service-created synthetic cases traverse one published domain pack.

All evidence and provider responses are local controlled test fixtures. This
test never makes an internet request and proves that the reusable rule scope
does not reuse either request's one-time send permission.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from lexaegis import release_service, service
from lexaegis.demo import synthetic_protocols
from lexaegis.contracts import IsolationReceipt
from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
from lexaegis.formal_release import FormalReleaseError, reserve_grant
from lexaegis.gateway import create_gateway
from lexaegis.util import digest
from lexaegis.worker import process_one
from tests.conftest import login_admin, login_as
from tests.test_release_service_integration import (
    MODEL, SECRET, TARGET, _Provider, _identities, _manifest, _register_receipt,
)
from tests.test_runtime_pack_workflow import RISK_WEIGHTS, SOURCE_PACK


def _provider():
    return {
        "id": "deepseek-product", "name": "受控合成测试服务商", "role": "processor",
        "endpoint": TARGET, "model": MODEL, "processing_regions": ["test"],
        "retention": "synthetic test", "training_use": "forbidden", "human_access": "forbidden",
        "subprocessor_status": "none", "deletion_mechanism": "synthetic test",
        "contract_reference": "TEST-CONTRACT", "impact_assessment_reference": "TEST-PIA",
        "allowed_tasks": ["fact_summary"], "allowed_domains": ["labor"],
        "allowed_fields": ["event"], "allowed_transports": ["cloud"],
        "status": "reviewed", "reviewed_by": "fixture", "reviewed_at": "2026-09-19T00:00:00Z",
    }


def _legal_review_body(task, pack):
    conditions = pack.get("manual_review_conditions") or [
        condition for rule in pack.get("rules", []) for condition in rule.get("conditions", [])]
    sources = pack.get("legal_sources") or []
    assert conditions and sources
    return {
        "request_hash": task["request_hash"], "material_version": task["case_revision"],
        "idempotency_key": f"multi-case-review-{task['id']}", "conclusion": "allow_processing",
        "reason": "对本条合成材料及当前请求完成法学复核。",
        "evidence_ids": [task["fact_snapshot"][0]["id"]],
        "reviewed_condition_ids": [conditions[0]["id"]], "legal_source_ids": [sources[0]["id"]],
        "acknowledged_risk_notices": True, "scope_note": "仅适用于本次合成请求。",
        "fact_premise": "材料为本地合成测试事实。", "authority_judgment": "本次复核不扩展授权范围。",
        "external_processing_note": "仅为受控本地集成测试。", "minimization_note": "仅披露任务结果。",
        "final_basis": "本次请求与复核依据一致。",
    }


def _add_case_and_fact(repo, index):
    case = service.create_case(repo, f"合成多案 {index}", reference_code=f"SYN-{index:03d}")
    document_id = f"synthetic-document-{index}"
    block_id = f"{document_id}:v1:b1"
    repo.put("document", {
        "id": document_id, "case_id": case["id"], "name": f"合成材料 {index}", "version": 1,
        "status": "ready", "ir": {"blocks": [{"id": block_id, "kind": "paragraph",
                                                   "text": f"合成劳动事实 {index}。"}]},
    }, case["id"])
    fact = service.save_fact(repo, case["id"], {
        "field": "event", "value": f"合成劳动事实 {index}。", "source_ids": [block_id], "confirmed": True,
    })
    return case, fact


def test_published_domain_pack_supports_two_independent_service_created_releases(env, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", SECRET)
    monkeypatch.setenv("LEX_REDTEAM_SECRET", "local-redteam-test-secret-32-characters")
    app, client, store, root = env["app"], env["client"], env["app"].state.store, env["root"]
    provider = _provider()
    with store.transaction() as repo:
        repo.put("provider", provider)
        settings = repo.get("settings")
        settings.update(cloud_url=TARGET.rsplit("/chat/completions", 1)[0], cloud_model=MODEL,
                        provider_id=provider["id"],
                        cloud_primary={"url": TARGET.rsplit("/chat/completions", 1)[0],
                                       "model": MODEL, "provider_id": provider["id"]},
                        cloud_standby={"url": "", "model": "", "provider_id": None},
                        isolation_verified=True)
        repo.put("settings", settings)
        cases = [_add_case_and_fact(repo, i) for i in (1, 2)]

    protocols = synthetic_protocols()
    with store.transaction() as repo:
        for protocol in protocols:
            repo.put("risk_protocol", protocol)
    source_pack = json.loads(Path(SOURCE_PACK).read_text())
    source_pack["risk_protocols"] = [{"id": item["id"], "version": item["version"]}
                                      for item in protocols]
    login_as(env, "technical_reviewer")
    prepared = client.post("/api/v1/formal-release/runtime-packs", json={
        "source_pack": source_pack, "import_report": {"status": "controlled_synthetic_test"},
        "scope_kind": "request",
    })
    assert prepared.status_code == 200, prepared.text
    draft = prepared.json()
    evidence = client.post("/api/v1/formal-release/evidence", params={"template_kind": "法05"},
        files={"file": ("synthetic-law05.txt", b"local synthetic domain rules review", "text/plain")})
    assert evidence.status_code == 200, evidence.text
    review = {
        "review_record": "SYNTHETIC-DOMAIN-RULES", "law_05_evidence_id": evidence.json()["id"],
        "published_scope": {"domain": "labor", "purpose": "R_fact_summary", "recipient": provider["id"]},
        "risk_weights": RISK_WEIGHTS, "references": ["synthetic-test-only"], "dispatch_allowed": True,
    }
    login_as(env, "legal_reviewer")
    response = client.post(f"/api/v1/formal-release/runtime-packs/{draft['id']}/review", json=review)
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/formal-release/runtime-packs/{draft['id']}/publish")
    assert response.status_code == 200, response.text
    active_pack = response.json()["active_pack"]
    runtime_pack_id = response.json()["runtime_pack"]["id"]
    exported = client.get(f"/api/v1/formal-release/runtime-packs/{runtime_pack_id}/export")
    assert exported.status_code == 200

    manifest = _manifest().model_copy(update={
        "runtime_pack_hash": "sha256:" + hashlib.sha256(exported.content).hexdigest(),
    })
    context = {"build_manifest": manifest, "runtime_identities": _identities(manifest),
               "evidence_intake": EvidenceIntakeService(EvidenceStore(store, root / "release-evidence"))}
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
    gateway_provider = _Provider()
    gateway = create_gateway(env["temp"] / "gateway-multi-case", secret=SECRET,
                             provider=gateway_provider, build_manifest=manifest)

    # The service itself constructs and evaluates each request from current
    # facts and the same activated domain rule pack.
    tasks = []
    for case, _fact in cases:
        with store.transaction() as repo:
            task = service.create_task(repo, case["id"], "cloud", "fact_summary", pack_id=active_pack["id"])
            evaluated = service.evaluate_task(repo, task["id"], release_context=context)
            tasks.append(evaluated)
    assert all(task["request"] and task["request_hash"] == digest(task["request"]) for task in tasks)
    assert tasks[0]["request_hash"] != tasks[1]["request_hash"]

    # This is an integration fixture for release scoping, so bind explicit
    # synthetic attack receipts to each generated input instead of claiming a
    # real red-team result. The independent G evidence receipts below remain
    # required before either task can be approved.
    with store.transaction() as repo:
        protocols_by_pack = {item["kind"]: item for item in repo.list("risk_protocol")}
        for index, task in enumerate(tasks):
            case = repo.get(task["case_id"], "case")
            case["combination_judgment"] = {
                "outcome": "resisted", "input_hash": task["request"]["dependencies"]["combination_input_hash"],
                "evidence": "受控合成组合风险判断，不代表真实案件结论",
            }
            repo.put("case", case)
            for kind in ("identity", "candidate_set", "sensitive_inference", "cross_round"):
                protocol = protocols_by_pack[kind]
                run = {
                    "id": f"synthetic-run-{index}-{kind}", "protocol_id": protocol["id"],
                    "protocol_hash": protocol["content_hash"], "task_id": task["id"],
                    "task_version": task["version"], "attack_input_hash": task["attack_input_hash"],
                    "outcome": "resisted", "score": 0.0,
                    "evidence": ["受控集成测试合成攻击结果；不代表真实攻击评估"],
                    "query_count": 0, "duration_ms": 0,
                    "started_at": "2026-09-19T00:00:00Z", "finished_at": "2026-09-19T00:00:01Z",
                }
                run["result_hash"] = digest(run)
                repo.put("attack_run", run, task["id"])
    for index, task in enumerate(tasks):
        with store.transaction() as repo:
            task = service.evaluate_task(repo, task["id"], release_context=context)
            tasks[index] = task
        assert task["request"]["policy"]["risk_completion"] == "complete", task["risk"].get("blockers")

    # Bind a named legal opinion to each generated request.
    legal_identity = login_as(env, "legal_reviewer")
    for task in tasks:
        pack = active_pack
        review_result = client.post(f"/api/v1/tasks/{task['id']}/legal-review",
                                    json=_legal_review_body(task, pack))
        assert review_result.status_code == 200, review_result.text

    intake = context["evidence_intake"]
    evidence_store = intake.evidence_store
    frozen_by_task = {}
    versions_by_task = {}
    for task in tasks:
        with store.read() as repo:
            current = repo.get(task["id"], "task")
            case = repo.get(task["case_id"], "case")
        from lexaegis.formal_release import freeze_request
        with store.read() as repo:
            frozen = freeze_request(repo, task=current, case=case,
                                    build_manifest=manifest, runtime_identities=context["runtime_identities"])
        frozen_by_task[task["id"]] = frozen
        versions_by_task[task["id"]] = {
            "materials": digest(frozen.material_versions), "rules": digest(frozen.rule_versions),
            "task": str(frozen.task_version), "mapping": str(frozen.mapping_version),
            "ledger": str(frozen.ledger_version), "combination": frozen.combination_input_hash,
        }

    # Register the complete controlled evidence set for each exact task tuple.
    approver_identity = login_as(env, "approver")
    g8_by_task = {}
    isolation_by_task = {}
    for task in tasks:
        frozen = frozen_by_task[task["id"]]
        versions = versions_by_task[task["id"]]
        release_tuple = frozen.tuple
        adopted = [fact["id"] for fact in task["fact_snapshot"]]
        def receipt(gate, template, actor=legal_identity["actor"], role="legal_reviewer", technical=None):
            return _register_receipt(intake, evidence_store, gate, template, actor=actor, role=role,
                versions=versions, request_hash=frozen.request_hash, technical_template=technical,
                adopted_fact_ids=adopted, release_tuple=release_tuple)
        receipt("G1", "法01")
        receipt("G2", "法02")
        receipt("G3", "法03")
        receipt("G3", "法04")
        receipt("G5", "法05")
        receipt("G6", "技03", actor="技术甲", role="technical_reviewer")
        receipt("G7", "法08", technical="技04")
        g8 = receipt("G8", "法09", technical="技05")
        g8_by_task[task["id"]] = g8
        receipt("G9", "法10", technical="技06")
        receipt("G10", "技08", actor=approver_identity["actor"], role="approver")
        now = datetime.now(timezone.utc)
        isolation = IsolationReceipt(
            id=f"isolation-{task['id']}", request_hash=frozen.request_hash,
            tuple=release_tuple,
            build_manifest_hash=frozen.build_manifest_hash, deployment_mode="isolated",
            deployment_identity_hash="sha256:" + "1" * 64, compose_hash="sha256:" + "2" * 64,
            image_digests=manifest.container_image_digests, api_no_egress=True, worker_no_egress=True,
            gateway_no_case_volume=True, redteam_no_secrets=True, benchmark_no_secrets=True,
            probe_output_hash="sha256:" + "3" * 64, host_firewall_evidence_hash="sha256:" + "4" * 64,
            supply_chain_evidence_hash="sha256:" + "5" * 64,
            generated_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(minutes=20)).isoformat(), attested_by="technical-reviewer",
            status="pending_legal_confirmation")
        isolation_by_task[task["id"]] = isolation

    first, second = tasks
    wrong_tuple = isolation_by_task[first["id"]].model_copy(update={
        "id": "isolation-wrong-tuple", "tuple": isolation_by_task[second["id"]].tuple})
    login_as(env, "technical_reviewer")
    assert client.post("/api/v1/formal-release/isolation",
                       json=wrong_tuple.model_dump(mode="json")).status_code == 409
    wrong_hash = isolation_by_task[first["id"]].model_copy(update={
        "id": "isolation-wrong-hash", "request_hash": second["request_hash"]})
    assert client.post("/api/v1/formal-release/isolation",
                       json=wrong_hash.model_dump(mode="json")).status_code == 409
    for task in tasks:
        isolation = isolation_by_task[task["id"]]
        submitted = client.post("/api/v1/formal-release/isolation",
                                json=isolation.model_dump(mode="json"))
        assert submitted.status_code == 200, submitted.text
    login_as(env, "legal_reviewer")
    wrong_g8 = client.post(
        f"/api/v1/formal-release/isolation/{isolation_by_task[first['id']].id}/confirm",
        json={"receipt_id": g8_by_task[second["id"]].id})
    assert wrong_g8.status_code == 409
    for task in tasks:
        confirmed = client.post(
            f"/api/v1/formal-release/isolation/{isolation_by_task[task['id']].id}/confirm",
            json={"receipt_id": g8_by_task[task["id"]].id})
        assert confirmed.status_code == 200, confirmed.text

    # Each generated request receives its own request-bound strategy, approval,
    # and one-time gateway claim; a prior task's grant cannot authorize the next.
    login_admin(env)
    for task in tasks:
        response = client.post(f"/api/v1/tasks/{task['id']}/formal-release/policy", json={
            "request_hash": task["request_hash"], "scope_kind": "request"})
        assert response.status_code == 200, response.text
        intake_context = client.get(
            f"/api/v1/tasks/{task['id']}/formal-release/intake-context")
        assert intake_context.status_code == 200, intake_context.text
        assert intake_context.json()["tuple"] == {
            "case_id": next(case["reference_code"] for case, _fact in cases
                             if case["id"] == task["case_id"]),
            "purpose": "R_fact_summary", "recipient": provider["id"]}
    login_as(env, "approver")
    for task in tasks:
        result = client.post(f"/api/v1/tasks/{task['id']}/approve", json={"request_hash": task["request_hash"]})
        assert result.status_code == 200, result.text
        tasks[tasks.index(task)] = result.json()
    with store.transaction() as repo:
        first_grant_id = tasks[0]["formal_release"]["grant"]["id"]
        with pytest.raises(FormalReleaseError, match="bound to another request"):
            reserve_grant(repo, first_grant_id, task_id=tasks[1]["id"],
                          request_hash=tasks[1]["request_hash"])
    login_as(env, "case_operator")
    for index, task in enumerate(tasks):
        result = client.post(f"/api/v1/tasks/{task['id']}/send")
        assert result.status_code == 200, result.text
        with TestClient(gateway) as gateway_client:
            assert process_one(store, root, gateway_client=gateway_client)
        with store.read() as repo:
            done = repo.get(task["id"], "task")
            grant = repo.get(done["formal_release"]["grant"]["id"], "one_time_dispatch_grant")
        assert done["status"] == "complete"
        assert grant["request_hash"] == task["request_hash"]
        assert grant["state"] == "consumed"
    assert gateway_provider.calls == 2

    with store.read() as repo:
        grants = repo.list("one_time_dispatch_grant")
        assert len(grants) == 2
        assert len({grant["request_hash"] for grant in grants}) == 2
        assert {repo.get(grant["release_policy_id"], "formal_release_policy")["scope_kind"]
                for grant in grants} == {"request"}
        assert len({repo.get(grant["release_policy_id"], "formal_release_policy")["bound_request_hash"]
                    for grant in grants}) == 2
