"""Synthetic full-path checks for gate snapshot-bound one-time grants."""
from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from fastapi.testclient import TestClient

from lexaegis import release_service, service
from lexaegis.contracts import FormalReleasePolicy, IsolationReceipt
from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
from lexaegis.formal_release import FIRST_RELEASE_TUPLE, install_policy
from lexaegis.gateway import create_gateway
from lexaegis.runtime_profile import bind_runtime
from lexaegis.storage import Store
from lexaegis.util import canonical, digest
from lexaegis.worker import process_one
from tests.test_release_service_integration import (
    SECRET, _Provider, _hash, _identities, _manifest, _register_receipt, _seed_business_state,
)


@pytest.fixture
def approved(tmp_path, monkeypatch):
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
        register("G3", "法03")
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
        monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
        yield {"store": store, "root": root, "gateway": gateway, "provider": provider,
               "task": task, "case": case, "context": context, "register": register}
    finally:
        store.engine.dispose()
        gateway.state.store.engine.dispose()


def _add_extra_valid_receipt(f):
    f["register"]("G3", "法03")


def test_unchanged_snapshot_remains_eligible_for_reserve_and_send(approved):
    f = approved
    with f["store"].transaction() as repo:
        service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
    with TestClient(f["gateway"]) as client:
        assert process_one(f["store"], f["root"], gateway_client=client)
    assert f["provider"].calls == 1


def test_changed_valid_receipt_set_requires_reapproval_before_reserve(approved):
    f = approved
    _add_extra_valid_receipt(f)
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError, match="证据快照已变化"):
            service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        assert repo.list("job") == []
    assert f["provider"].calls == 0


def test_changed_valid_receipt_set_blocks_queued_worker_without_provider_call(approved):
    f = approved
    with f["store"].transaction() as repo:
        service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        grant_id = repo.get(f["task"]["id"], "task")["formal_release"]["grant"]["id"]
    _add_extra_valid_receipt(f)
    with TestClient(f["gateway"]) as client:
        assert process_one(f["store"], f["root"], gateway_client=client)
    assert f["provider"].calls == 0
    with f["store"].read() as repo:
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.list("job")[-1]["status"] == "failed"
    with f["gateway"].state.store.read() as repo:
        assert repo.list("send") == []


@pytest.mark.parametrize("phase", ["enqueue", "send"])
def test_legacy_mismatching_snapshot_fails_closed(approved, phase):
    f = approved
    if phase == "send":
        with f["store"].transaction() as repo:
            service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        grant_id = task["formal_release"]["grant"]["id"]
        grant = repo.get(grant_id, "one_time_dispatch_grant")
        case = repo.get(task["case_id"], "case")
        frozen, decision = release_service.evaluate(repo, task, case, f["context"])
        snapshot = repo.get("formal-release-snapshot-" + decision.snapshot_hash.removeprefix("sha256:"), "gate_snapshot")
        legacy = {"request_hash": frozen.request_hash, "build_manifest_hash": frozen.build_manifest_hash,
                  "hits": [hit.model_dump(mode="json") for hit in decision.hits],
                  "evidence_receipt_ids": snapshot["evidence_receipt_ids"]}
        legacy_hash = "sha256:" + hashlib.sha256(canonical(legacy).encode()).hexdigest()
        assert legacy_hash != decision.snapshot_hash
        grant["gate_snapshot_hash"] = legacy_hash
        repo.put("one_time_dispatch_grant", grant)
        with pytest.raises(ValueError, match="证据快照已变化"):
            release_service.assert_allowed(repo, task, case, f["context"], phase)
    assert f["provider"].calls == 0


def test_expired_request_receipt_changes_validated_snapshot_even_with_alternative(tmp_path):
    from tests.test_release_service_integration import _evaluation_fixture
    store, intake, evidence, context, task, case, frozen, versions = _evaluation_fixture(tmp_path, "expiry-binding")
    try:
        def register():
            return _register_receipt(intake, evidence, "G6", "技03", actor="技术甲", role="technical_reviewer",
                                     versions=versions, request_hash=frozen.request_hash)
        stale = register()
        current = register()
        with store.transaction() as repo:
            _, before = release_service.evaluate(repo, task, case, context)
            old = repo.get("formal-release-snapshot-" + before.snapshot_hash.removeprefix("sha256:"), "gate_snapshot")
        # EvidenceIntake uses its own read connection; commit the simulated
        # expiry before asking the real evaluator to resolve the receipt.
        with store.transaction() as repo:
            record = repo.get(stale.id, "gate_evidence_receipt")
            record["valid_until"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            repo.put("gate_evidence_receipt", record)
        with store.transaction() as repo:
            _, after = release_service.evaluate(repo, task, case, context)
            new = repo.get("formal-release-snapshot-" + after.snapshot_hash.removeprefix("sha256:"), "gate_snapshot")
            assert [h.model_dump() for h in before.hits] == [h.model_dump() for h in after.hits]
            assert old["evidence_receipt_ids"] == new["evidence_receipt_ids"]
            assert stale.id in old["validated_receipt_ids"]
            assert stale.id not in new["validated_receipt_ids"]
            assert current.id in new["validated_receipt_ids"]
            assert before.snapshot_hash != after.snapshot_hash
    finally:
        store.engine.dispose()
