"""Controlled evidence -> approval -> reservation -> worker -> local gateway.

Every evidence artifact below is generated in the test and stored through the
same content-addressed EvidenceStore used by production. The provider is a
local stub; no external network request is possible.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from lexaegis import release_service, service
from lexaegis.contracts import (FormalReleasePolicy, GateReceiptInput, IsolationReceipt,
                                OneTimeDispatchGrant, ReleaseBuildManifest)
from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
from lexaegis.formal_release import FIRST_RELEASE_TUPLE, FormalReleaseError, install_policy, issue_grant
from lexaegis.gateway import create_gateway
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.runtime_profile import bind_runtime
from lexaegis.storage import Store
from lexaegis.util import digest
from lexaegis.worker import process_one


SECRET = "controlled-formal-release-test-secret-32-chars"
TARGET = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"


def _hash(char):
    return "sha256:" + char * 64


def _manifest():
    return ReleaseBuildManifest(
        id="verified-integration-test-build", source_commit="a" * 40, worktree_clean=True,
        source_tree_hash=_hash("a"), documentation_hash=_hash("b"),
        frontend_dist_hash=_hash("c"), wheel_hash=_hash("d"),
        lockfile_hashes={"requirements.lock": _hash("e")}, runtime_pack_hash=_hash("f"),
        container_image_digests={"api": _hash("a"), "worker": _hash("b"), "gateway": _hash("c")},
        migration_revision="0003_formal_release_uniques", validation_results_hash=_hash("d"),
        status="verified", created_at=datetime.now(timezone.utc).isoformat(), verified_by="test-ci",
    )


def _identities(manifest):
    identity_hash = build_manifest_identity_hash(manifest)
    return [{"process": process, "status": "verified", "runtime_identity_hash": identity_hash}
            for process in ("api", "worker", "gateway")]


class _Outcome:
    status = "complete"
    result = {"claims": [{"text": "合成事实", "source_ids": ["fact-1"]}],
              "unused_fact_ids": [], "gaps": []}

    def ledger_fields(self):
        return {"selected_slot": "primary", "attempts": [], "authorized_recipients": []}


class _Provider:
    primary_key = "local-test-key"
    standby_key = ""

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def dispatch(self, target, body, dual_slot=None, persist_attempt=None):
        assert target == TARGET
        assert dual_slot.get("standby") is None
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic unknown provider result")
        return _Outcome()


def _register_receipt(intake, evidence, gate_id, template, *, actor, role, versions,
                      request_hash, technical_template=None, adopted_fact_ids=None, release_tuple=None):
    at = datetime.now(timezone.utc)
    release_tuple = release_tuple or FIRST_RELEASE_TUPLE
    template_artifact = evidence.register_artifact(
        content=f"synthetic signed {gate_id} template for test".encode(), media_type="application/pdf",
        source_path_hint=f"controlled/{gate_id}.pdf", actor="test-intake", template_kind=template,
    )
    artifacts = [template_artifact]
    data = {
        "gate_id": gate_id, "tuple": release_tuple, "template_kind": template,
        "template_version": "2026-09-19", "template_artifact_id": template_artifact.id,
        "bound_versions": versions if gate_id in {"G1", "G2", "G3", "G5"} else {},
        "request_hash": request_hash if gate_id in {"G6", "G7", "G8", "G9", "G10"} else None,
        "conclusion": "pass", "confirmed_by": actor, "confirmed_role": role,
        "confirmed_at": (at - timedelta(seconds=5)).isoformat(),
        "valid_from": (at - timedelta(minutes=1)).isoformat(),
        "valid_until": (at + timedelta(minutes=20)).isoformat(),
        "evidence_artifact_ids": [template_artifact.id],
    }
    if gate_id == "G1":
        data["adopted_fact_ids"] = adopted_fact_ids if adopted_fact_ids is not None else ["fact-1"]
    if gate_id == "G2":
        organization = evidence.register_artifact(
            content=b"synthetic organization authorization", media_type="application/pdf",
            source_path_hint="controlled/organization.pdf", actor="test-intake", template_kind=None,
        )
        artifacts.append(organization)
        data["evidence_artifact_ids"].append(organization.id)
        data["authorization_statement"] = (
            f"本次 {release_tuple['case_id']}、{release_tuple['purpose']} 子目的、"
            f"{release_tuple['recipient']} 接收方可用。")
        data["organization_authorization_artifact_id"] = organization.id
    if technical_template:
        technical = evidence.register_artifact(
            content=f"synthetic {technical_template} evidence".encode(), media_type="application/pdf",
            source_path_hint=f"controlled/{technical_template}.pdf", actor="test-intake",
            template_kind=technical_template,
        )
        data["evidence_artifact_ids"].append(technical.id)
        data["technical_evidence_artifact_id"] = technical.id
        data["technical_evidence_hash"] = technical.content_hash
        data["technical_evidence_request_hash"] = request_hash
    return intake.record_gate_receipt(GateReceiptInput(**data), actor="test-intake", at=at)


def _seed_business_state(repo, manifest):
    pack = {"id": "rules-v1", "domain_id": "labor", "status": "published", "schema_version": 2,
            "version": "1", "content_hash": _hash("9"), "published_scope": FIRST_RELEASE_TUPLE}
    provider = {"id": "deepseek-profile", "status": "reviewed", "endpoint": TARGET, "model": MODEL}
    repo.put("pack", pack)
    repo.put("provider", provider)
    repo.put("settings", {"id": "settings", "version": 1})
    case = {"id": "LA-001", "reference_code": "LA-001", "domain": "labor", "revision": 1, "ledger_version": 0,
            "runtime_profile": "production", "data_origin": "customer_material", "mode": "formal",
            "mapping_version": 1}
    source_block_id = "document-e2e:v1:b1"
    repo.put("document", {"id": "document-e2e", "case_id": case["id"], "version": 1,
                           "ir": {"blocks": [{"id": source_block_id, "kind": "paragraph",
                                               "text": "合成事实来源段落"}] }}, case["id"])
    repo.put("fact", {"id": "fact-1", "case_id": case["id"], "field": "event", "value": "合成事实",
                       "source_ids": [source_block_id], "confirmed": True, "stale": False}, case["id"])
    request = {
        "request_id": "request-formal-e2e-001", "case_id": case["id"], "task_id": "task-formal-e2e-001",
        "mode": "formal", "transport": "cloud", "target": TARGET,
        "wire_payload": {"contract_version": 2, "task": {"id": "fact_summary", "version": "2.0"},
                         "facts": [{"id": "fact-1", "text": "合成事实"}]},
        "body": {"model": MODEL, "messages": [{"role": "system", "content": "仅摘要给定事实"},
                                                {"role": "user", "content": "{}"}]},
        "dependencies": {
            "primary_provider_id": provider["id"], "primary_provider_hash": digest(provider),
            "provider_id": provider["id"], "provider_hash": digest(provider), "material_versions": {"document-e2e": 1},
            "pack_hash": digest(pack), "mapping_version": 1, "ledger_version": 0,
            "combination_input_hash": _hash("1"), "risk_protocol_hashes": {"identity": _hash("2")},
            "dual_slot": {"primary": {"target": TARGET, "model": MODEL}},
            "runtime_profile": "production", "data_origin": "customer_material",
        },
        "policy": {"approved_for_dispatch": True, "demo_exception": False, "risk_completion": "complete"},
    }
    task = {
        "id": request["task_id"], "case_id": case["id"], "type": "fact_summary", "status": "review",
        "transport": "cloud", "sub_purpose": "R_fact_summary", "version": 1, "mapping_version": 1,
        "case_revision": 1, "settings_version": 1, "pack_id": pack["id"], "request": request,
        "request_hash": digest(request), "risk": {"approval_allowed": True, "ledger_version": 0},
        "review_status": "cleared", "review_request_hash": digest(request), "approval": None,
        "formal_release": None, "stale": False,
        "decisions": [{"fact_id": "fact-1", "field": "event", "output": "合成事实"}],
        "fact_snapshot": [{"id": "fact-1", "field": "event", "value": "合成事实", "source_ids": [source_block_id],
                           "confirmed": True, "stale": False}],
    }
    case.update(mapping={}, mapping_entries=[], followups=[])
    repo.put("case", case)
    repo.put("task", task, case["id"])
    return task, case, pack, provider


@pytest.mark.parametrize("provider_fails", [False, True], ids=["complete", "unknown-no-refund"])
def test_controlled_evidence_release_service_worker_gateway_once(monkeypatch, tmp_path, provider_fails):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", SECRET)
    manifest = _manifest()
    store = Store(tmp_path / "app.sqlite")
    app_root = tmp_path / "app"
    bind_runtime(app_root, "app")
    evidence = EvidenceStore(store, app_root / "release-evidence")
    intake = EvidenceIntakeService(evidence)
    provider = _Provider(fail=provider_fails)
    gateway = create_gateway(tmp_path / "gateway", secret=SECRET, provider=provider, build_manifest=manifest)
    with store.transaction() as repo:
        task, case, pack, provider_profile = _seed_business_state(repo, manifest)
    with store.transaction() as repo:
        frozen = release_service.evaluate(repo, task, case, {
            "build_manifest": manifest, "runtime_identities": _identities(manifest), "evidence_intake": intake,
        })[0]
    versions = {
        "materials": digest(frozen.material_versions), "rules": digest(frozen.rule_versions),
        "task": str(frozen.task_version), "mapping": str(frozen.mapping_version),
        "ledger": str(frozen.ledger_version), "combination": frozen.combination_input_hash,
    }
    _register_receipt(intake, evidence, "G1", "法01", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G2", "法02", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G3", "法03", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G3", "法04", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G5", "法05", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G6", "技03", actor="技术甲", role="technical_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G7", "法08", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash, technical_template="技04")
    g8 = _register_receipt(intake, evidence, "G8", "法09", actor="法学甲", role="legal_reviewer",
                           versions=versions, request_hash=frozen.request_hash, technical_template="技05")
    _register_receipt(intake, evidence, "G9", "法10", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash, technical_template="技06")
    _register_receipt(intake, evidence, "G10", "技08", actor="审批人甲", role="approver",
                      versions=versions, request_hash=frozen.request_hash)
    now = datetime.now(timezone.utc)
    isolation = IsolationReceipt(
            id="isolation-e2e", request_hash=frozen.request_hash,
            tuple=FIRST_RELEASE_TUPLE,
            build_manifest_hash=frozen.build_manifest_hash, deployment_mode="isolated",
            deployment_identity_hash=_hash("3"), compose_hash=_hash("4"),
            image_digests=manifest.container_image_digests, api_no_egress=True, worker_no_egress=True,
            gateway_no_case_volume=True, redteam_no_secrets=True, benchmark_no_secrets=True,
            probe_output_hash=_hash("5"), host_firewall_evidence_hash=_hash("6"),
            supply_chain_evidence_hash=_hash("7"), generated_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(minutes=20)).isoformat(), attested_by="technical-reviewer",
            legal_confirmation_receipt_id=g8.id, status="valid",
    )
    policy = FormalReleasePolicy(
        id="policy-e2e", tuple=FIRST_RELEASE_TUPLE, build_manifest_hash=frozen.build_manifest_hash,
        allowed_target=frozen.target, allowed_model=frozen.model,
        allowed_provider_profile_hash=digest(provider_profile), maximum_dispatches=1,
    )
    with store.transaction() as repo:
        repo.put("isolation_receipt", isolation.model_dump(mode="json"), case["id"])
        install_policy(repo, policy, actor="release-admin", actor_role="admin")

    context = {"build_manifest": manifest, "runtime_identities": _identities(manifest), "evidence_intake": intake}
    # Worker obtains the same verified API/worker/gateway identities from the
    # startup probe. Inject only that probe result; all task and gateway checks run.
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
    with store.transaction() as repo:
        task = service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                                    actor_role="approver", actor_user_id="approver-user", release_context=context)
        job = service.reserve_send(repo, task["id"], release_context=context)
        assert job["kind"] == "send"
        reserved = repo.get(task["id"], "task")
        assert reserved["formal_release"]["grant"]["state"] == "reserved"

    with TestClient(gateway) as gateway_client:
        assert process_one(store, app_root, gateway_client=gateway_client)
        # A second worker pass sees no pending job and cannot resend.
        assert process_one(store, app_root, gateway_client=gateway_client) is False

    assert provider.calls == 1
    with store.read() as repo:
        completed = repo.get(task["id"], "task")
        api_grant = repo.get(reserved["formal_release"]["grant"]["id"], "one_time_dispatch_grant")
        policy = repo.get("policy-e2e", "formal_release_policy")
        expected_status = "unknown" if provider_fails else "complete"
        assert completed["status"] == expected_status, str((completed.get("error"), repo.list("job"),
                                                             _gateway_state(gateway)))
        assert api_grant["state"] == "consumed"
        assert policy["status"] == "consumed"
        assert policy["consumed_dispatches"] == 1
        release_service.revoke(repo, completed, "后续案件材料变化")
        repo.put("task", completed, completed["case_id"])
        assert completed["product_release"]["state"] == expected_status
        assert repo.get("policy-e2e", "formal_release_policy")["consumed_dispatches"] == 1
    sends, gateway_claims = _gateway_state(gateway)
    expected_status = "unknown" if provider_fails else "complete"
    assert sends[0]["status"] == expected_status
    assert gateway_claims[0]["state"] == expected_status
    with gateway.state.store.read() as repo:
        assert repo.get(reserved["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "consumed"
        assert repo.get("policy-e2e", "formal_release_policy")["consumed_dispatches"] == 1


def test_missing_controlled_evidence_blocks_approval_and_creates_no_grant(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    manifest = _manifest()
    store = Store(tmp_path / "blocked.sqlite")
    evidence = EvidenceStore(store, tmp_path / "controlled-evidence")
    intake = EvidenceIntakeService(evidence)
    identities = _identities(manifest)
    context = {"build_manifest": manifest, "runtime_identities": identities, "evidence_intake": intake}
    with store.transaction() as repo:
        task, case, _pack, provider = _seed_business_state(repo, manifest)
        frozen = release_service.evaluate(repo, task, case, context)[0]
        install_policy(repo, FormalReleasePolicy(
            id="policy-blocked", tuple=FIRST_RELEASE_TUPLE,
            build_manifest_hash=frozen.build_manifest_hash, allowed_target=frozen.target,
            allowed_model=frozen.model, allowed_provider_profile_hash=digest(provider),
        ), actor="release-admin", actor_role="admin")
        with pytest.raises(ValueError, match="正式放行未满足"):
            service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                                 actor_role="approver", actor_user_id="approver-user", release_context=context)
        assert repo.get(task["id"], "task")["approval"] is None
        assert repo.list("one_time_dispatch_grant") == []
        assert repo.get("policy-blocked", "formal_release_policy")["status"] == "blocked"


def _evaluation_fixture(tmp_path, name):
    manifest = _manifest()
    store = Store(tmp_path / f"{name}.sqlite")
    app_root = tmp_path / f"{name}-app"
    bind_runtime(app_root, "app")
    evidence = EvidenceStore(store, app_root / "release-evidence")
    intake = EvidenceIntakeService(evidence)
    context = {"build_manifest": manifest, "runtime_identities": _identities(manifest),
               "evidence_intake": intake}
    with store.transaction() as repo:
        task, case, _pack, provider_profile = _seed_business_state(repo, manifest)
        frozen = release_service.evaluate(repo, task, case, context)[0]
        versions = {
            "materials": digest(frozen.material_versions), "rules": digest(frozen.rule_versions),
            "task": str(frozen.task_version), "mapping": str(frozen.mapping_version),
            "ledger": str(frozen.ledger_version), "combination": frozen.combination_input_hash,
        }
        install_policy(repo, FormalReleasePolicy(
            id=f"policy-{name}", tuple=frozen.tuple, build_manifest_hash=frozen.build_manifest_hash,
            allowed_target=frozen.target, allowed_model=frozen.model,
            allowed_provider_profile_hash=digest(provider_profile),
        ), actor="release-admin", actor_role="admin")
    return store, intake, evidence, context, task, case, frozen, versions


@pytest.mark.parametrize("adopted_fact_ids,add_wire_fact", [
    (["fact-does-not-exist"], False),
    (["fact-1"], True),
], ids=["unknown-adopted-fact", "disclosure-fact-not-adopted"])
def test_g1_requires_current_source_anchored_adoption_for_every_disclosed_fact(
        tmp_path, adopted_fact_ids, add_wire_fact):
    store, intake, evidence, context, task, case, frozen, versions = _evaluation_fixture(
        tmp_path, "g1-adoption")
    if add_wire_fact:
        with store.transaction() as repo:
            current_task = repo.get(task["id"], "task")
            source_id = "document-e2e:v1:b1"
            repo.put("fact", {"id": "fact-2", "case_id": case["id"], "field": "date",
                               "value": "2026-01-01", "source_ids": [source_id],
                               "confirmed": True, "stale": False}, case["id"])
            current_task["fact_snapshot"].append({"id": "fact-2", "field": "date", "value": "2026-01-01",
                                                   "source_ids": [source_id], "confirmed": True, "stale": False})
            current_task["decisions"].append({"fact_id": "fact-2", "field": "date", "output": "2026-01-01"})
            current_task["request"]["wire_payload"]["facts"].append(
                {"id": "fact-2", "field": "date", "text": "2026-01-01"})
            current_task["request_hash"] = digest(current_task["request"])
            repo.put("task", current_task, case["id"])
            task = current_task
            frozen = release_service.evaluate(repo, task, case, context)[0]
            versions = {"materials": digest(frozen.material_versions), "rules": digest(frozen.rule_versions),
                        "task": str(frozen.task_version), "mapping": str(frozen.mapping_version),
                        "ledger": str(frozen.ledger_version), "combination": frozen.combination_input_hash}
    _register_receipt(intake, evidence, "G1", "法01", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash,
                      adopted_fact_ids=adopted_fact_ids)
    with store.transaction() as repo:
        _frozen, decision = release_service.evaluate(repo, task, case, context)
        assert any(hit.gate_id == "G1" and hit.reason_code == "formal_evidence_missing"
                   for hit in decision.hits)
    store.engine.dispose()


@pytest.mark.parametrize("template,actor,role", [
    ("技01", "技术甲", "technical_reviewer"),
    ("法03", "法学甲", "legal_reviewer"),
    ("法04", "法学甲", "legal_reviewer"),
], ids=["engineering-only", "legal03-only", "legal04-only"])
def test_g3_requires_both_current_legal_reviews_and_blocks_grant(tmp_path, template, actor, role):
    store, intake, evidence, context, task, case, frozen, versions = _evaluation_fixture(
        tmp_path, f"g3-{template}")
    _register_receipt(intake, evidence, "G1", "法01", actor="法学甲", role="legal_reviewer",
                      versions=versions, request_hash=frozen.request_hash)
    _register_receipt(intake, evidence, "G3", template, actor=actor, role=role,
                      versions=versions, request_hash=frozen.request_hash)
    with store.transaction() as repo:
        _frozen, decision = release_service.evaluate(repo, task, case, context)
        assert any(hit.gate_id == "G3" and hit.reason_code == "formal_evidence_missing"
                   for hit in decision.hits)
        with pytest.raises(FormalReleaseError, match="not eligible"):
            issue_grant(repo, frozen=_frozen, decision=decision, actor="审批人甲", actor_role="approver",
                        approval={"actor_role": "approver", "actor": "审批人甲",
                                  "request_hash": frozen.request_hash})
    store.engine.dispose()


def test_evidence_revocation_uses_single_transaction_and_completes(tmp_path):
    store = Store(tmp_path / "revocation.sqlite")
    evidence = EvidenceStore(store, tmp_path / "revocation-evidence")
    intake = EvidenceIntakeService(evidence)
    receipt = _register_receipt(intake, evidence, "G1", "法01", actor="法学甲", role="legal_reviewer",
                                versions={"material": "v1"}, request_hash=None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(intake.revoke_evidence, receipt.id, "synthetic fixture cleanup",
                             actor="法学甲", actor_role="legal_reviewer")
        revoked = future.result(timeout=3)
    assert revoked.revoked_at
    assert revoked.revocation_reason == "synthetic fixture cleanup"
    assert not intake.receipt_passes(revoked)


def test_pre_send_rejection_revokes_reserved_grant_without_consuming_slot(tmp_path):
    store = Store(tmp_path / "pre-send.sqlite")
    request_hash = "request-pre-send"
    policy = FormalReleasePolicy(
        id="policy-pre-send", tuple=FIRST_RELEASE_TUPLE, build_manifest_hash=_hash("a"),
        allowed_target=TARGET, allowed_model=MODEL, allowed_provider_profile_hash=_hash("b"),
        status="armed_once", consumed_dispatches=0,
        valid_from="2026-09-19T00:00:00Z", valid_until="2026-09-20T00:00:00Z",
    )
    grant = OneTimeDispatchGrant(
        id="grant-pre-send", nonce="pre-send-nonce", request_hash=request_hash,
        gate_snapshot_hash=_hash("c"), evidence_manifest_hash=_hash("d"), build_manifest_hash=_hash("a"),
        release_policy_id=policy.id, tuple=FIRST_RELEASE_TUPLE, actor="approver", actor_role="approver",
        issued_at="2026-09-19T00:00:00Z", expires_at="2026-09-20T00:00:00Z", state="reserved",
    )
    task = {
        "id": "task-pre-send", "case_id": "LA-001", "request_hash": request_hash,
        "request": {"request_id": "request-pre-send"},
        "formal_release": {"grant": grant.model_dump(mode="json")},
        "product_release": {"state": "armed_once"},
    }
    with store.transaction() as repo:
        repo.put("formal_release_policy", policy.model_dump(mode="json"))
        repo.put("one_time_dispatch_grant", grant.model_dump(mode="json"))
        repo.put("task", task, "LA-001")
        release_service.revoke(repo, task, "发送前校验失败")
        release_service.mirror_outcome(repo, task, {"status": "rejected"})
        repo.put("task", task, "LA-001")
        assert repo.get(grant.id, "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get(policy.id, "formal_release_policy")["status"] == "blocked"
        assert repo.get(policy.id, "formal_release_policy")["consumed_dispatches"] == 0
        assert repo.get(task["id"], "task")["product_release"]["state"] == "blocked"
        assert repo.get(task["id"], "task")["formal_release"]["grant"]["state"] == "revoked"


def _gateway_state(gateway):
    with gateway.state.store.read() as repo:
        return repo.list("send"), repo.list("formal_release_claim")
