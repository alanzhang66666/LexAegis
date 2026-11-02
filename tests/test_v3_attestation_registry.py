"""V3 attestation reuse: anchor trust, revocation monotonicity and gate binding."""
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lexaegis import attestation_registry as registry
from lexaegis import gate_orchestrator as gates
from lexaegis import release_service, service
from lexaegis.scoped_attestation_shadow import (
    AttestationStatement,
    RevocationStatement,
    authenticate_revocations,
    authenticate_statement,
)
from lexaegis.util import digest


def _now():
    return datetime.now(timezone.utc)


def _hash(char):
    return "sha256:" + char * 64


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gates_helpers():
    return _load("v3_gates_helpers_for_attestation", "test_v3_authoritative_gates.py")


LEGAL_KEY = Ed25519PrivateKey.generate()
TECH_KEY = Ed25519PrivateKey.generate()
REV_KEY = Ed25519PrivateKey.generate()


def _public(private):
    from cryptography.hazmat.primitives import serialization
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def _write_anchor(tmp_path, *, providers, policies, mode=0o644, revocation_seq=1, revoked=()):
    document = {
        "schema_version": 1,
        "network_policy_hash": _hash("b"),
        "trusted_keys": [
            {"key_id": "legal-key", "owner_id": "firm-a", "role": "legal_reviewer",
             "purpose": "attestation", "allowed_scopes": ["recipient", "policy"],
             "public_key_hex": _public(LEGAL_KEY), "active": True},
            {"key_id": "tech-key", "owner_id": "tech-a", "role": "technical_reviewer",
             "purpose": "attestation", "allowed_scopes": ["deployment"],
             "public_key_hex": _public(TECH_KEY), "active": True},
            {"key_id": "rev-key", "owner_id": "registry-a", "role": "revocation_authority",
             "purpose": "revocation", "allowed_scopes": [],
             "public_key_hex": _public(REV_KEY), "active": True},
        ],
        "revocation": {"authority_id": "registry-a", "ledger_id": "ledger-1",
                       "minimum_sequence": revocation_seq, "known_revoked_ids": list(revoked)},
        "providers": providers,
        "policy_jurisdictions": policies,
    }
    path = tmp_path / "trust-anchor.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, mode)
    return path


def _provider_map(frozen):
    return {frozen.tuple["recipient"]: {"jurisdiction": "SG", "processing_region": "ap-southeast-1"}}


def _scope_statements(frozen, case, *, suffix="", provider_id=None, region="ap-southeast-1"):
    """Build one statement per required scope; caller signs and ingests them."""
    provider = provider_id or frozen.tuple["recipient"]
    now = _now()
    base = {"issued_at": now - timedelta(minutes=2), "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(minutes=30), "evidence_hashes": (_hash("e"),)}
    return {
        "recipient": AttestationStatement(
            attestation_id=f"att-recipient{suffix}", scope={
                "kind": "recipient", "provider_id": provider,
                "provider_profile_hash": _hash_text(frozen.provider_profile_hash),
                "endpoint": frozen.target, "model": frozen.model,
                "purpose": frozen.tuple["purpose"], "jurisdiction": "SG",
                "processing_region": region},
            issuer_id="firm-a", issuer_role="legal_reviewer", key_id="legal-key", **base),
        "policy": AttestationStatement(
            attestation_id=f"att-policy{suffix}", scope={
                "kind": "policy", "domain": str(case["domain"]), "pack_id": "rules-v1",
                "pack_content_hash": _hash_text(frozen.runtime_pack_hash), "jurisdiction": "CN"},
            issuer_id="firm-a", issuer_role="legal_reviewer", key_id="legal-key", **base),
        "deployment": AttestationStatement(
            attestation_id=f"att-deployment{suffix}", scope={
                "kind": "deployment", "environment": "production",
                "build_manifest_hash": _hash_text(frozen.build_manifest_hash),
                "network_policy_hash": _hash("b")},
            issuer_id="tech-a", issuer_role="technical_reviewer", key_id="tech-key", **base),
    }


def _hash_text(value):
    text = value.removeprefix("sha256:")
    return "sha256:" + text


def _revocations(*, sequence=1, revoked=(), valid=True):
    now = _now()
    statement = RevocationStatement(
        ledger_id="ledger-1", sequence=sequence, authority_id="registry-a", key_id="rev-key",
        issued_at=now - timedelta(minutes=1) if valid else now - timedelta(hours=5),
        valid_until=now + timedelta(minutes=30) if valid else now - timedelta(hours=4),
        revoked_attestation_ids=tuple(revoked))
    return authenticate_revocations(statement, REV_KEY)


def _install_scope(repo, statements, at=None):
    at = at or _now()
    anchor = registry.load_anchor()
    for statement in statements.values():
        registry.ingest_attestation(repo, authenticate_statement(statement, _key_for(statement)), anchor, at)


def _key_for(statement):
    return TECH_KEY if statement.scope.kind == "deployment" else LEGAL_KEY


# --- anchor trust -----------------------------------------------------------

def test_guard_is_off_by_default_and_bundle_stays_byte_identical(monkeypatch):
    monkeypatch.delenv(registry.GUARD_ENV, raising=False)
    monkeypatch.delenv(registry.ANCHOR_ENV, raising=False)
    task = {"id": "t", "request_hash": "r", "risk": {"approval_allowed": True, "ledger_version": 1}}
    case = {"id": "c", "ledger_version": 1}
    from lexaegis.contracts import GateDecision
    decision = GateDecision(phase="evaluate", request_hash="r", snapshot_hash="s", hits=[],
                            approval_eligible=True).model_dump(mode="json")
    assert registry.gate_members(None, {}, task, case, _now()) is None
    assert registry.status(None, {}, task, case, _now())["state"] == "not_enabled"
    without = gates.evaluate_gate_bundle(decision, task, case)
    assert "attestation" not in without and without["approval_eligible"] is True


def test_anchor_requires_absolute_untampered_file(tmp_path, monkeypatch):
    monkeypatch.delenv(registry.ANCHOR_ENV, raising=False)
    assert registry.load_anchor()["state"] == "unconfigured"
    assert registry.load_anchor("relative.json")["reasons"] == ["trust_anchor_must_be_absolute"]
    assert registry.load_anchor(str(tmp_path / "absent.json"))["state"] == "unconfigured"
    writable = _write_anchor(tmp_path, providers={}, policies={}, mode=0o666)
    assert registry.load_anchor(str(writable))["reasons"] == ["trust_anchor_writable_by_others"]


def test_anchor_loads_keys_and_facts(tmp_path):
    path = _write_anchor(tmp_path, providers={"p1": {"jurisdiction": "SG", "processing_region": "ap-1"}},
                         policies={"labor": "CN"})
    anchor = registry.load_anchor(str(path))
    assert anchor["state"] == "loaded"
    assert set(anchor["trusted_keys"]) == {"legal-key", "tech-key", "rev-key"}
    assert anchor["network_policy_hash"] == _hash("b")
    assert anchor["providers"]["p1"]["jurisdiction"] == "SG"


# --- scope derivation -------------------------------------------------------

def test_expected_scopes_normalise_bare_hashes_and_require_anchor_facts():
    frozen = {"tuple": {"recipient": "p1", "purpose": "R_fact_summary"}, "target": "https://a.example/v1/x",
              "model": "m1", "provider_profile_hash": "c" * 64, "runtime_pack_hash": "d" * 64,
              "build_manifest_hash": "sha256:" + "e" * 64}
    anchor = {"loaded": True, "network_policy_hash": _hash("b"),
              "providers": {"p1": {"jurisdiction": "SG", "processing_region": "ap-1"}},
              "policy_jurisdictions": {"labor": "CN"}}
    scopes = registry.expected_scopes(frozen, {"pack_id": "rules-v1"}, {"domain": "labor",
                                                                       "runtime_profile": "production"}, anchor)
    assert scopes["reasons"] == []
    assert scopes["recipient"].provider_profile_hash == _hash("c")
    assert scopes["policy"].pack_content_hash == _hash("d")
    assert scopes["deployment"].network_policy_hash == _hash("b")
    # Missing anchor facts are reported, never guessed into a pass.
    stripped = registry.expected_scopes(frozen, {"pack_id": "rules-v1"},
                                        {"domain": "labor", "runtime_profile": "production"},
                                        {**anchor, "providers": {}, "policy_jurisdictions": {}})
    assert stripped["recipient"] is None and stripped["policy"] is None
    assert "recipient_region_unconfigured" in stripped["reasons"]
    assert "policy_jurisdiction_unconfigured" in stripped["reasons"]


def test_attestation_member_only_withholds_never_grants():
    from lexaegis.contracts import GateDecision
    task = {"id": "t", "request_hash": "r", "risk": {"approval_allowed": True, "ledger_version": 1}}
    case = {"id": "c", "ledger_version": 1}
    decision = GateDecision(phase="evaluate", request_hash="r", snapshot_hash="s", hits=[],
                            approval_eligible=True).model_dump(mode="json")
    blocked = {"state": "blocked", "legal_state": "fail", "deployment_state": "unknown",
               "matched": {}, "summary_hash": _hash("f"), "grants_reuse": False}
    bundle = gates.evaluate_gate_bundle(decision, task, case, attestation=blocked)
    assert bundle["approval_eligible"] is False and bundle["dispatch_allowed"] is False
    states = {group["id"]: group["state"] for group in bundle["groups"]}
    assert states["G-L"] == "fail" and states["G-S"] == "unknown"
    passing = {**blocked, "state": "satisfied", "legal_state": "pass", "deployment_state": "pass"}
    ok = gates.evaluate_gate_bundle(decision, task, case, attestation=passing)
    assert ok["approval_eligible"] is True and ok["dispatch_allowed"] is False
    assert ok["attestation"]["grants_reuse"] is False
    # The proof enters the hash, so a replaced proof cannot reuse an old bundle.
    other = gates.evaluate_gate_bundle(decision, task, case,
                                       attestation={**passing, "summary_hash": _hash("1")})
    assert other["bundle_hash"] != ok["bundle_hash"]


# --- registry monotonicity --------------------------------------------------

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

    def list(self, kind, scope=None):
        return [dict(body) for stored, body in self.rows.values() if stored == kind]


def test_ingest_rejects_conflicting_id_and_foreign_signature(tmp_path, monkeypatch):
    path = _write_anchor(tmp_path, providers={}, policies={})
    monkeypatch.setenv(registry.ANCHOR_ENV, str(path))
    anchor = registry.load_anchor()
    repo = _Repo()
    now = _now()
    statement = AttestationStatement(
        attestation_id="att-1", scope={"kind": "policy", "domain": "labor", "pack_id": "rules-v1",
                                       "pack_content_hash": _hash("d"), "jurisdiction": "CN"},
        issuer_id="firm-a", issuer_role="legal_reviewer", key_id="legal-key",
        issued_at=now - timedelta(minutes=2), valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=30),
        evidence_hashes=(_hash("e"),))
    registry.ingest_attestation(repo, authenticate_statement(statement, LEGAL_KEY), anchor, now)
    forged = statement.model_copy(update={"attestation_id": "att-1",
                                          "evidence_hashes": (_hash("f"),)})
    with pytest.raises(registry.AttestationRegistryError):
        registry.ingest_attestation(repo, authenticate_statement(forged, LEGAL_KEY), anchor, now)
    wrong_key = statement.model_copy(update={"attestation_id": "att-2"})
    with pytest.raises(registry.AttestationRegistryError):
        registry.ingest_attestation(repo, authenticate_statement(wrong_key, REV_KEY), anchor, now)


def test_revocation_snapshot_must_be_newer_complete_and_fresh(tmp_path, monkeypatch):
    path = _write_anchor(tmp_path, providers={}, policies={})
    monkeypatch.setenv(registry.ANCHOR_ENV, str(path))
    anchor = registry.load_anchor()
    repo = _Repo()
    now = _now()
    registry.ingest_revocations(repo, _revocations(sequence=2, revoked=("att-1",)), anchor, now)
    with pytest.raises(registry.AttestationRegistryError):
        registry.ingest_revocations(repo, _revocations(sequence=2, revoked=("att-1", "att-2")), anchor, now)
    with pytest.raises(registry.AttestationRegistryError):
        registry.ingest_revocations(repo, _revocations(sequence=3, revoked=()), anchor, now)
    with pytest.raises(registry.AttestationRegistryError):
        registry.ingest_revocations(repo, _revocations(sequence=3, revoked=("att-1",), valid=False), anchor, now)
    assert registry.ingest_revocations(repo, _revocations(sequence=3, revoked=("att-1", "att-2")),
                                       anchor, now)["sequence"] == 3


# --- real formal request integration ---------------------------------------

def _prepared(tmp_path, monkeypatch, name):
    """Full formal request with receipts, isolation, policy and a trust anchor."""
    store, context, task = _gates_helpers()._ready(tmp_path, monkeypatch, name)
    with store.transaction() as repo:
        current_task = repo.get(task["id"], "task")
        case = repo.get(task["case_id"], "case")
        frozen = release_service.evaluate(repo, current_task, case, context)[0]
    path = _write_anchor(tmp_path, providers=_provider_map(frozen),
                         policies={str(case["domain"]): "CN"})
    monkeypatch.setenv(registry.ANCHOR_ENV, str(path))
    monkeypatch.setenv(registry.GUARD_ENV, "1")
    return store, context, task, case, frozen


def test_enabled_guard_blocks_approval_until_every_scope_is_attested(tmp_path, monkeypatch):
    store, context, task, case, frozen = _prepared(tmp_path, monkeypatch, "att-blocked")
    with store.transaction() as repo:
        status = release_service.status(repo, repo.get(task["id"], "task"), case, context)
        assert status["attestations"]["state"] == "blocked"
        assert status["attestations"]["grants_reuse"] is False
        assert status["gate_evaluation"]["approval_eligible"] is False
        with pytest.raises(ValueError):
            service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                                 actor_role="approver", actor_user_id="approver-user",
                                 release_context=context)


def test_valid_attestations_and_revocation_snapshot_enable_approval(tmp_path, monkeypatch):
    store, context, task, case, frozen = _prepared(tmp_path, monkeypatch, "att-ok")
    anchor = registry.load_anchor()
    with store.transaction() as repo:
        now = _now()
        registry.ingest_revocations(repo, _revocations(sequence=1), anchor, now)
        _install_scope(repo, _scope_statements(frozen, case), now)
        status = release_service.status(repo, repo.get(task["id"], "task"), case, context)
        assert status["attestations"]["state"] == "satisfied"
        assert status["gate_evaluation"]["attestation"]["legal_state"] == "pass"
        assert status["gate_evaluation"]["dispatch_allowed"] is False
        approved = service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                                        actor_role="approver", actor_user_id="approver-user",
                                        release_context=context)
        binding = approved["formal_release"]["gate_evaluation"]
        assert binding["bundle_hash"].startswith("sha256:")


def test_revoking_a_proof_after_approval_blocks_enqueue(tmp_path, monkeypatch):
    store, context, task, case, frozen = _prepared(tmp_path, monkeypatch, "att-revoked")
    anchor = registry.load_anchor()
    with store.transaction() as repo:
        now = _now()
        registry.ingest_revocations(repo, _revocations(sequence=1), anchor, now)
        statements = _scope_statements(frozen, case)
        _install_scope(repo, statements, now)
        service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                            actor_role="approver", actor_user_id="approver-user", release_context=context)
        # A newer snapshot revokes the policy proof the approval was bound to.
        registry.ingest_revocations(repo, _revocations(sequence=2, revoked=("att-policy",)), anchor, now)
        with pytest.raises(ValueError):
            service.reserve_send(repo, task["id"], release_context=context)


def test_enqueue_still_works_while_the_same_proofs_stay_valid(tmp_path, monkeypatch):
    """Control arm: without the revocation the identical path must still enqueue."""
    store, context, task, case, frozen = _prepared(tmp_path, monkeypatch, "att-control")
    anchor = registry.load_anchor()
    with store.transaction() as repo:
        now = _now()
        registry.ingest_revocations(repo, _revocations(sequence=1), anchor, now)
        _install_scope(repo, _scope_statements(frozen, case), now)
        service.approve_task(repo, task["id"], task["request_hash"], actor="审批人甲",
                            actor_role="approver", actor_user_id="approver-user", release_context=context)
        job = service.reserve_send(repo, task["id"], release_context=context)
        assert job and repo.get(task["id"], "task")["status"] in {"queued", "sending"}


def test_changed_provider_region_invalidates_the_proof(tmp_path, monkeypatch):
    store, context, task, case, frozen = _prepared(tmp_path, monkeypatch, "att-scope")
    anchor = registry.load_anchor()
    with store.transaction() as repo:
        now = _now()
        registry.ingest_revocations(repo, _revocations(sequence=1), anchor, now)
        _install_scope(repo, _scope_statements(frozen, case), now)
        moved = registry.expected_scopes(
            frozen.model_dump(mode="json"), repo.get(task["id"], "task"), case,
            {**anchor, "providers": {frozen.tuple["recipient"]: {"jurisdiction": "SG",
                                                                "processing_region": "eu-west-1"}}})
        verdict = registry.resolve(repo, frozen.model_dump(mode="json"), repo.get(task["id"], "task"),
                                   case, {**anchor, "providers": {frozen.tuple["recipient"]: {
                                       "jurisdiction": "SG", "processing_region": "eu-west-1"}}},
                                   _now())
        assert moved["recipient"].processing_region == "eu-west-1"
        assert verdict["legal_state"] == "fail" and verdict["state"] == "blocked"
        assert "no_attestation_for_scope" in verdict["reasons"]
