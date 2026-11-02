"""Authoritative V3 four-gate evaluation: equivalence, fail-closed and binding checks."""
import importlib.util
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import pytest

from lexaegis import gate_orchestrator as gates
from lexaegis import release_service, service
from lexaegis.contracts import GateDecision, GateHit, IsolationReceipt


RECEIPT_GATES = ["G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10"]
TASK = {"id": "task-a", "request_hash": "req-a", "case_id": "case-a",
        "risk": {"approval_allowed": True, "ledger_version": 3}}
CASE = {"id": "case-a", "ledger_version": 3}


def decision(*gate_ids, eligible=None, reason="formal_evidence_missing", status="pending", snapshot="snap-a"):
    hits = [GateHit(gate_id=g, status=status, kind="verification", reason_code=reason, message=f"{g} missing")
            for g in gate_ids]
    return GateDecision(phase="evaluate", request_hash="req-a", snapshot_hash=snapshot, hits=hits,
                        approval_eligible=(not hits) if eligible is None else eligible).model_dump(mode="json")


def groups(bundle):
    return {group["id"]: group["state"] for group in bundle["groups"]}


def test_complete_evaluation_passes_all_four_gates_without_send_authority():
    bundle = gates.evaluate_gate_bundle(decision(), TASK, CASE)
    assert bundle["authoritative"] is True and bundle["approval_eligible"] is True
    assert groups(bundle) == {"G-L": "pass", "G-D": "pass", "G-H": "pass", "G-S": "pass"}
    assert set(bundle["legacy_gates"]) == {"G0", *RECEIPT_GATES, "isolation"}
    assert bundle["dispatch_allowed"] is False


@pytest.mark.parametrize("gate,group_ids", [
    ("G1", {"G-L"}), ("G2", {"G-L", "G-D"}), ("G3", {"G-L"}), ("G5", {"G-L"}), ("G6", {"G-H"}),
    ("G7", {"G-D"}), ("G8", {"G-D"}), ("G9", {"G-S"}), ("G10", {"G-H"}),
])
def test_each_missing_receipt_blocks_only_its_groups(gate, group_ids):
    bundle = gates.evaluate_gate_bundle(decision(gate), TASK, CASE)
    assert bundle["legacy_gates"][gate] == "pending"
    assert {g for g, state in groups(bundle).items() if state != "pass"} == group_ids
    assert bundle["approval_eligible"] is False


def test_missing_isolation_receipt_blocks_send_gate():
    bundle = gates.evaluate_gate_bundle(decision("G-product", reason="isolation_receipt_missing"), TASK, CASE)
    assert bundle["legacy_gates"]["isolation"] == "pending" and groups(bundle)["G-S"] == "pending"
    assert bundle["global_hits"] == [] and bundle["approval_eligible"] is False


def test_aborted_evaluation_is_unknown_not_pass():
    bundle = gates.evaluate_gate_bundle(
        decision("G-product", reason="formal_release_blocked", status="fail"), TASK, CASE)
    assert all(bundle["legacy_gates"][g] == "unknown" for g in [*RECEIPT_GATES, "isolation"])
    assert groups(bundle) == {"G-L": "unknown", "G-D": "unknown", "G-H": "unknown", "G-S": "unknown"}
    assert bundle["global_hits"] and bundle["approval_eligible"] is False


def test_failed_receipt_gate_is_fail():
    bundle = gates.evaluate_gate_bundle(decision("G3", status="fail"), TASK, CASE)
    assert bundle["legacy_gates"]["G3"] == "fail" and groups(bundle)["G-L"] == "fail"


@pytest.mark.parametrize("task,case,expected", [
    ({**TASK, "risk": None}, CASE, "unknown"),
    ({**TASK, "risk": {"approval_allowed": False, "ledger_version": 3}}, CASE, "fail"),
    ({**TASK, "risk": {"approval_allowed": "yes", "ledger_version": 3}}, CASE, "fail"),
    (TASK, {**CASE, "ledger_version": 4}, "fail"),
], ids=["no-risk", "risk-blocked", "truthy-not-true", "ledger-moved"])
def test_g0_requires_current_persisted_risk(task, case, expected):
    bundle = gates.evaluate_gate_bundle(decision(), task, case)
    assert bundle["legacy_gates"]["G0"] == expected
    assert groups(bundle)["G-D"] == expected and bundle["approval_eligible"] is False


def test_send_phase_uses_ledger_recorded_at_enqueue():
    queued = {**TASK, "dispatch_ledger_version": 4}
    moved = {**CASE, "ledger_version": 4}
    assert gates.evaluate_gate_bundle(decision(), queued, moved, "send")["approval_eligible"] is True
    assert gates.evaluate_gate_bundle(decision(), queued, {**CASE, "ledger_version": 5}, "send")[
        "legacy_gates"]["G0"] == "fail"
    # Before enqueue the assessed ledger remains authoritative.
    assert gates.evaluate_gate_bundle(decision(), queued, moved, "approve")["legacy_gates"]["G0"] == "fail"


def test_unknown_hit_and_legacy_ineligibility_block():
    data = decision()
    data["hits"] = [{"gate_id": "future-gate", "message": "new"}]
    assert gates.evaluate_gate_bundle(data, TASK, CASE)["approval_eligible"] is False
    assert gates.evaluate_gate_bundle(decision(eligible=False), TASK, CASE)["approval_eligible"] is False


@pytest.mark.parametrize("mutate", [
    lambda d: None, lambda d: {**d, "phase": "approve"}, lambda d: {**d, "snapshot_hash": ""},
    lambda d: {**d, "request_hash": ""}, lambda d: {**d, "hits": None}, lambda d: {**d, "hits": ["bad"]},
])
def test_incomplete_evaluation_is_rejected(mutate):
    with pytest.raises(ValueError):
        gates.evaluate_gate_bundle(mutate(decision()), TASK, CASE)


def test_new_rule_never_allows_what_legacy_blocks():
    """Exhaustive: eligible iff the legacy decision is eligible with no hits and G0 passes."""
    gate_ids = ["G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G-product"]
    for count in range(len(gate_ids) + 1):
        for subset in combinations(gate_ids, count):
            for eligible in (False, True):
                for risk_ok in (False, True):
                    task = {**TASK, "risk": {"approval_allowed": risk_ok, "ledger_version": 3}}
                    bundle = gates.evaluate_gate_bundle(decision(*subset, eligible=eligible), task, CASE)
                    assert bundle["approval_eligible"] == (eligible and not subset and risk_ok)
                    assert bundle["dispatch_allowed"] is False


def test_bundle_hash_binds_evaluation_but_not_phase():
    base = gates.evaluate_gate_bundle(decision(), TASK, CASE)
    assert base["bundle_hash"] == gates.evaluate_gate_bundle(decision(), TASK, CASE, "enqueue")["bundle_hash"]
    assert base["bundle_hash"] != gates.evaluate_gate_bundle(decision(snapshot="snap-b"), TASK, CASE)["bundle_hash"]
    assert base["bundle_hash"] != gates.evaluate_gate_bundle(decision(), {**TASK, "id": "task-b"}, CASE)["bundle_hash"]


class _Repo:
    def __init__(self):
        self.rows = {}

    def put(self, kind, data, scope=""):
        self.rows[data["id"]] = (kind, dict(data))
        return data

    def get(self, ident, kind=None):
        if ident not in self.rows or (kind and self.rows[ident][0] != kind):
            raise KeyError(ident)
        return dict(self.rows[ident][1])


def _bound():
    repo = _Repo()
    bundle = gates.evaluate_gate_bundle(decision(), TASK, CASE)
    record = gates.persist_gate_bundle(repo, bundle)
    task = {**TASK, "formal_release": {"gate_evaluation": {"id": record["id"], "bundle_hash": record["bundle_hash"]}}}
    return repo, bundle, task


def test_persist_refuses_blocked_or_projection_bundles():
    with pytest.raises(ValueError):
        gates.persist_gate_bundle(_Repo(), gates.evaluate_gate_bundle(decision("G3"), TASK, CASE))
    with pytest.raises(ValueError):
        gates.persist_gate_bundle(_Repo(), {**gates.build_gate_bundle(decision()), "approval_eligible": True})


def test_bound_bundle_accepts_identical_recomputation():
    repo, bundle, task = _bound()
    assert gates.require_bound_bundle(repo, task, bundle)["status"] == "current"


@pytest.mark.parametrize("tamper", ["missing", "forged-hash", "other-task", "retired", "changed"])
def test_bound_bundle_fails_closed(tamper):
    repo, bundle, task = _bound()
    if tamper == "missing":
        task = {**TASK}
    elif tamper == "forged-hash":
        task["formal_release"]["gate_evaluation"]["bundle_hash"] = "sha256:" + "0" * 64
    elif tamper == "other-task":
        task = {**task, "id": "task-b"}
    elif tamper == "retired":
        assert gates.retire_bound_bundle(repo, task, "test") is True
        assert gates.retire_bound_bundle(repo, task, "again") is False
    elif tamper == "changed":
        bundle = gates.evaluate_gate_bundle(decision(snapshot="snap-b"), TASK, CASE)
    with pytest.raises(ValueError, match="四门评估"):
        gates.require_bound_bundle(repo, task, bundle)


def test_approve_refuses_when_four_gates_disagree_with_legacy(monkeypatch):
    """Defence in depth: even an eligible legacy decision needs a passing G0."""
    monkeypatch.setattr(release_service, "required", lambda _: True)
    blocked_risk = {**TASK, "risk": {"approval_allowed": False, "ledger_version": 3}, "approval": {}}
    monkeypatch.setattr(release_service, "evaluate",
                        lambda *a: (object(), GateDecision.model_validate(decision())))
    called = []
    monkeypatch.setattr(release_service.release, "issue_grant", lambda *a, **k: called.append(1))
    with pytest.raises(ValueError, match="四门评估未全部满足：G-D"):
        release_service.approve(_Repo(), blocked_risk, CASE, {})
    assert called == []


# --- Real formal evaluation (receipts, isolation, policy, grant, worker path) ---

def _helpers():
    spec = importlib.util.spec_from_file_location(
        "formal_integration_helpers_v3_gates", Path(__file__).with_name("test_release_service_integration.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready(tmp_path, monkeypatch, name):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    h = _helpers()
    store, intake, evidence, context, task, case, frozen, versions = h._evaluation_fixture(tmp_path, name)
    receipts = {}
    for gate_id, template, actor, role, technical in [
        ("G1", "法01", "法学甲", "legal_reviewer", None), ("G2", "法02", "法学甲", "legal_reviewer", None),
        ("G3", "法03", "法学甲", "legal_reviewer", None), ("G3", "法04", "法学甲", "legal_reviewer", None),
        ("G5", "法05", "法学甲", "legal_reviewer", None), ("G6", "技03", "技术甲", "technical_reviewer", None),
        ("G7", "法08", "法学甲", "legal_reviewer", "技04"), ("G8", "法09", "法学甲", "legal_reviewer", "技05"),
        ("G9", "法10", "法学甲", "legal_reviewer", "技06"), ("G10", "技08", "审批人甲", "approver", None),
    ]:
        kwargs = {"technical_template": technical} if technical else {}
        receipts[gate_id] = h._register_receipt(intake, evidence, gate_id, template, actor=actor, role=role,
                                                versions=versions, request_hash=frozen.request_hash, **kwargs)
    now = datetime.now(timezone.utc)
    manifest = context["build_manifest"]
    isolation = IsolationReceipt(
        id=f"isolation-{name}", request_hash=frozen.request_hash, tuple=frozen.tuple,
        build_manifest_hash=frozen.build_manifest_hash, deployment_mode="isolated",
        deployment_identity_hash=h._hash("3"), compose_hash=h._hash("4"),
        image_digests=manifest.container_image_digests, api_no_egress=True, worker_no_egress=True,
        gateway_no_case_volume=True, redteam_no_secrets=True, benchmark_no_secrets=True,
        probe_output_hash=h._hash("5"), host_firewall_evidence_hash=h._hash("6"),
        supply_chain_evidence_hash=h._hash("7"), generated_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(minutes=20)).isoformat(), attested_by="technical-reviewer",
        legal_confirmation_receipt_id=receipts["G8"].id, status="valid")
    with store.transaction() as repo:
        repo.put("isolation_receipt", isolation.model_dump(mode="json"), case["id"])
    return store, context, task


def _approve(repo, task, context):
    return service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲", actor_role="approver",
                                actor_user_id="approver-user", release_context=context)


def test_real_evaluation_records_and_binds_authoritative_bundle(tmp_path, monkeypatch):
    store, context, task = _ready(tmp_path, monkeypatch, "v3-gates-ok")
    try:
        with store.transaction() as repo:
            status = release_service.status(repo, repo.get(task["id"], "task"),
                                            repo.get(task["case_id"], "case"), context)
            assert status["state"] == "eligible"
            assert status["gate_evaluation"]["approval_eligible"] is True
            assert groups(status["gate_evaluation"]) == {"G-L": "pass", "G-D": "pass", "G-H": "pass", "G-S": "pass"}
            assert repo.list(gates.BUNDLE_KIND) == []  # status is read-only
            approved = _approve(repo, task, context)
            binding = approved["formal_release"]["gate_evaluation"]
            record = repo.get(binding["id"], gates.BUNDLE_KIND)
            assert record["status"] == "current" and record["bundle_hash"] == binding["bundle_hash"]
            assert record["bundle_hash"] == status["gate_evaluation"]["bundle_hash"]
            assert record["task_id"] == task["id"] and record["dispatch_allowed"] is False
            job = service.reserve_send(repo, task["id"], release_context=context)
            assert job["kind"] == "send"
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("tamper", ["retired", "forged-binding", "deleted"])
def test_enqueue_refuses_without_current_server_bundle(tmp_path, monkeypatch, tamper):
    store, context, task = _ready(tmp_path, monkeypatch, "v3-gates-" + tamper)
    try:
        with store.transaction() as repo:
            approved = _approve(repo, task, context)
            binding = approved["formal_release"]["gate_evaluation"]
            if tamper == "retired":
                record = repo.get(binding["id"], gates.BUNDLE_KIND)
                repo.put(gates.BUNDLE_KIND, {**record, "status": "retired"}, task["case_id"])
            elif tamper == "forged-binding":
                approved["formal_release"]["gate_evaluation"]["bundle_hash"] = "sha256:" + "f" * 64
                repo.put("task", approved, task["case_id"])
            else:
                repo.delete(binding["id"])
            with pytest.raises(ValueError, match="四门评估"):
                service.reserve_send(repo, task["id"], release_context=context)
            assert repo.get(approved["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "issued"
    finally:
        store.engine.dispose()


def test_revocation_retires_bound_bundle(tmp_path, monkeypatch):
    store, context, task = _ready(tmp_path, monkeypatch, "v3-gates-revoke")
    try:
        with store.transaction() as repo:
            approved = _approve(repo, task, context)
            binding = approved["formal_release"]["gate_evaluation"]
            release_service.revoke(repo, approved, "材料版本变更")
            assert repo.get(binding["id"], gates.BUNDLE_KIND)["status"] == "retired"
    finally:
        store.engine.dispose()
