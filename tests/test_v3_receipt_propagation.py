"""Synthetic integration checks for request-independent receipt revocation."""
from copy import deepcopy

import pytest

from lexaegis import release_service
from tests.test_release_service_integration import _evaluation_fixture, _register_receipt


@pytest.mark.parametrize("claimed", [False, True], ids=["unclaimed", "claimed-history"])
def test_exact_scope_receipt_revocation_propagates_without_rewriting_claimed(tmp_path, claimed):
    store, intake, evidence, context, task, case, frozen, versions = _evaluation_fixture(tmp_path, "v3-propagation")
    try:
        def g3(template, *, bound=versions):
            return _register_receipt(intake, evidence, "G3", template, actor="法学甲",
                                     role="legal_reviewer", versions=bound,
                                     request_hash=frozen.request_hash)
        receipt = g3("法03")
        companion = g3("法04")
        unrelated = g3("法03", bound={**versions, "task": "different"})
        assert receipt.request_hash is None
        with store.transaction() as repo:
            _, decision = release_service.evaluate(repo, task, case, context)
            snap_id = "formal-release-snapshot-" + decision.snapshot_hash.removeprefix("sha256:")
            snap = repo.get(snap_id, "gate_snapshot")
            assert receipt.id in snap["evidence_receipt_ids"]
            assert companion.id in snap["evidence_receipt_ids"]
            assert unrelated.id not in snap["evidence_receipt_ids"]
            repo.put("one_time_dispatch_grant", {"id": "test-grant", "request_hash": frozen.request_hash, "state": "issued"})
            repo.put("dispatch_intent", {"id": "test-intent", "request_hash": frozen.request_hash, "status": "pending"})
            if claimed:
                gateway = {"id": "test-gateway-record", "request_hash": frozen.request_hash, "status": "unknown"}
                repo.put("gateway_record", gateway)
            before = deepcopy(snap)
        intake.revoke_evidence(receipt.id, "synthetic revoke", actor="法学甲", actor_role="legal_reviewer")
        with store.read() as repo:
            if claimed:
                assert repo.get(snap_id, "gate_snapshot") == before
                assert repo.get("test-gateway-record", "gateway_record") == gateway
                assert repo.get("test-grant", "one_time_dispatch_grant")["state"] == "issued"
            else:
                updated = repo.get(snap_id, "gate_snapshot")
                assert updated["status"] == "invalidated"
                assert updated["approval_eligible"] is False
                assert updated["dispatch_allowed"] is False
                assert repo.get("test-grant", "one_time_dispatch_grant")["state"] == "revoked"
                assert repo.get("test-intent", "dispatch_intent")["status"] == "cancelled"
    finally:
        store.engine.dispose()


def test_snapshot_hash_binds_receipt_dependencies_even_when_gate_results_unchanged(tmp_path):
    store, intake, evidence, context, task, case, frozen, versions = _evaluation_fixture(tmp_path, "snapshot-binding")
    try:
        def register(template):
            return _register_receipt(intake, evidence, "G3", template, actor="法学甲",
                                     role="legal_reviewer", versions=versions,
                                     request_hash=frozen.request_hash)
        first = register("法03")
        register("法04")
        with store.transaction() as repo:
            _, prior = release_service.evaluate(repo, task, case, context)
            prior_id = "formal-release-snapshot-" + prior.snapshot_hash.removeprefix("sha256:")
            original = repo.get(prior_id, "gate_snapshot")
        added = register("法03")
        with store.transaction() as repo:
            _, updated = release_service.evaluate(repo, task, case, context)
            updated_id = "formal-release-snapshot-" + updated.snapshot_hash.removeprefix("sha256:")
            assert [h.model_dump() for h in prior.hits] == [h.model_dump() for h in updated.hits]
            assert prior.snapshot_hash != updated.snapshot_hash
            assert repo.get(prior_id, "gate_snapshot") == original
            assert first.id in original["evidence_receipt_ids"]
            assert added.id not in original["evidence_receipt_ids"]
            assert added.id in repo.get(updated_id, "gate_snapshot")["evidence_receipt_ids"]
    finally:
        store.engine.dispose()


def test_revoking_unhashed_g3_before_send_blocks_real_worker_and_provider(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from lexaegis import service
    from lexaegis.contracts import FormalReleasePolicy, IsolationReceipt
    from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
    from lexaegis.formal_release import FIRST_RELEASE_TUPLE, install_policy
    from lexaegis.gateway import create_gateway
    from lexaegis.runtime_profile import bind_runtime
    from lexaegis.storage import Store
    from lexaegis.util import digest
    from lexaegis.worker import process_one
    from tests.test_release_service_integration import (
        SECRET, _Provider, _hash, _identities, _manifest, _seed_business_state,
    )

    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", SECRET)
    manifest = _manifest()
    store = Store(tmp_path / "app.sqlite")
    root = tmp_path / "app"
    bind_runtime(root, "app")
    evidence = EvidenceStore(store, root / "release-evidence")
    intake = EvidenceIntakeService(evidence)
    provider = _Provider()
    gateway = create_gateway(tmp_path / "gateway", secret=SECRET, provider=provider, build_manifest=manifest)
    context = {"build_manifest": manifest, "runtime_identities": _identities(manifest), "evidence_intake": intake}
    try:
        with store.transaction() as repo:
            task, case, _, profile = _seed_business_state(repo, manifest)
            frozen = release_service.evaluate(repo, task, case, context)[0]
        versions = {"materials": digest(frozen.material_versions), "rules": digest(frozen.rule_versions),
                    "task": str(frozen.task_version), "mapping": str(frozen.mapping_version),
                    "ledger": str(frozen.ledger_version), "combination": frozen.combination_input_hash}
        def register(gate, template, role="legal_reviewer", technical=None):
            return _register_receipt(intake, evidence, gate, template,
                actor="审批人甲" if role == "approver" else ("技术甲" if role == "technical_reviewer" else "法学甲"),
                role=role, versions=versions, request_hash=frozen.request_hash, technical_template=technical)
        register("G1", "法01")
        register("G2", "法02")
        revoked = register("G3", "法03")
        register("G3", "法04")
        register("G5", "法05")
        register("G6", "技03", "technical_reviewer")
        register("G7", "法08", technical="技04")
        g8 = register("G8", "法09", technical="技05")
        register("G9", "法10", technical="技06")
        register("G10", "技08", "approver")
        stamp = datetime.now(timezone.utc)
        isolation = IsolationReceipt(
            id="v3-isolation", request_hash=frozen.request_hash, tuple=FIRST_RELEASE_TUPLE,
            build_manifest_hash=frozen.build_manifest_hash, deployment_mode="isolated",
            deployment_identity_hash=_hash("3"), compose_hash=_hash("4"), image_digests=manifest.container_image_digests,
            api_no_egress=True, worker_no_egress=True, gateway_no_case_volume=True,
            redteam_no_secrets=True, benchmark_no_secrets=True, probe_output_hash=_hash("5"),
            host_firewall_evidence_hash=_hash("6"), supply_chain_evidence_hash=_hash("7"),
            generated_at=(stamp-timedelta(minutes=1)).isoformat(), expires_at=(stamp+timedelta(minutes=20)).isoformat(),
            attested_by="synthetic-technical", legal_confirmation_receipt_id=g8.id, status="valid")
        with store.transaction() as repo:
            repo.put("isolation_receipt", isolation.model_dump(mode="json"), case["id"])
            install_policy(repo, FormalReleasePolicy(id="v3-policy", tuple=FIRST_RELEASE_TUPLE,
                build_manifest_hash=frozen.build_manifest_hash, allowed_target=frozen.target,
                allowed_model=frozen.model, allowed_provider_profile_hash=digest(profile)),
                actor="release-admin", actor_role="admin")
            task = service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                                        actor_role="approver", actor_user_id="approver-user", release_context=context)
            service.reserve_send(repo, task["id"], release_context=context)
            grant_id = repo.get(task["id"], "task")["formal_release"]["grant"]["id"]
            assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "reserved"
        intake.revoke_evidence(revoked.id, "synthetic revoke", actor="法学甲", actor_role="legal_reviewer")
        with store.read() as repo:
            assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "revoked"
        monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
        with TestClient(gateway) as client:
            assert process_one(store, root, gateway_client=client)
        assert provider.calls == 0
        with gateway.state.store.read() as repo:
            assert repo.list("send") == []
    finally:
        store.engine.dispose()
        gateway.state.store.engine.dispose()
