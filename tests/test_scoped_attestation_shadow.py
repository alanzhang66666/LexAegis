"""Synthetic Ed25519/revocation checks; none is an authorization fixture."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from lexaegis.scoped_attestation_shadow import (
    AttestationStatement, AuthenticatedAttestation, AuthenticatedRevocations,
    DeploymentScope, PolicyScope, RecipientScope, RevocationStatement, TrustedKey,
    authenticate_statement, authenticate_revocations, inspect_attestation,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = T0 + timedelta(minutes=30)
HASH = "sha256:" + "a" * 64
ISSUE_PRIVATE_BYTES = bytes([1])*32
REVOKE_PRIVATE_BYTES = bytes([2])*32
ISSUE_KEY = Ed25519PrivateKey.from_private_bytes(ISSUE_PRIVATE_BYTES)
REVOKE_KEY = Ed25519PrivateKey.from_private_bytes(REVOKE_PRIVATE_BYTES)
ISSUE_PUBLIC = ISSUE_KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
REVOKE_PUBLIC = REVOKE_KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
ROTATED_PUBLIC = Ed25519PrivateKey.from_private_bytes(bytes([3])*32).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def scope(**updates):
    values = {"kind":"recipient", "provider_id":"provider-a", "provider_profile_hash":HASH,
        "endpoint":"https://provider.invalid/v1", "model":"model-a", "purpose":"summary",
        "jurisdiction":"CN", "processing_region":"CN"}
    values.update(updates)
    return RecipientScope(**values)


def statement(**updates):
    values = {"attestation_id":"att-a", "scope":scope(), "issuer_id":"reviewer-a",
        "issuer_role":"legal_reviewer", "key_id":"issuer-key-a", "issued_at":T0,
        "valid_from":T0, "valid_until":T0+timedelta(hours=2), "evidence_hashes":(HASH,)}
    values.update(updates)
    return AttestationStatement(**values)


def snapshot(**updates):
    values = {"ledger_id":"ledger-a", "sequence":2, "authority_id":"revoker-a",
        "key_id":"revoker-key-a", "issued_at":T0, "valid_until":T0+timedelta(hours=1),
        "revoked_attestation_ids":()}
    values.update(updates)
    return authenticate_revocations(RevocationStatement(**values),REVOKE_KEY)


def keys():
    return {
        "issuer-key-a":TrustedKey("issuer-key-a","reviewer-a","legal_reviewer","attestation",frozenset({"recipient","policy"}),ISSUE_PUBLIC),
        "revoker-key-a":TrustedKey("revoker-key-a","revoker-a","revocation_authority","revocation",frozenset(),REVOKE_PUBLIC),
    }


def run(*, proof=None, expected=None, rev="default", trust=None, at=NOW, floor=2, authority="revoker-a", ledger="ledger-a", known_revoked=frozenset()):
    return inspect_attestation(proof or authenticate_statement(statement(),ISSUE_KEY), expected or scope(),
        snapshot() if rev == "default" else rev, trusted_keys=keys() if trust is None else trust,
        expected_revocation_authority=authority, expected_ledger_id=ledger,
        minimum_revocation_sequence=floor, minimum_revoked_ids=known_revoked, at=at)


def test_success_only_means_cryptographic_diagnostic_not_authorization():
    result = run()
    assert result["state"] == "diagnostic_match" and result["reasons"] == []
    assert result["authoritative"] is False and result["evidence_bytes_verified"] is False
    assert result["human_identity_verified"] is False and "dispatch_allowed" not in result
    assert repr(ISSUE_PRIVATE_BYTES) not in repr(keys()["issuer-key-a"])


@pytest.mark.parametrize("field,value", [
    ("provider_id","provider-b"), ("provider_profile_hash","sha256:"+"b"*64),
    ("endpoint","https://other.invalid/v1"), ("model","model-b"),
    ("purpose","different"), ("jurisdiction","VN"), ("processing_region","SG"),
])
def test_every_recipient_scope_field_is_exactly_bound(field,value):
    result=run(expected=scope(**{field:value}))
    assert result["state"] == "not_accepted" and "scope_mismatch" in result["reasons"]


def test_tampering_statement_or_signature_is_rejected():
    proof=authenticate_statement(statement(),ISSUE_KEY)
    data=proof.model_dump(mode="json")
    data["statement"]["scope"]["model"]="model-b"
    tampered=AuthenticatedAttestation.model_validate(data)
    result=run(proof=tampered,expected=scope(model="model-b"))
    assert "attestation_signature_invalid" in result["reasons"]
    data=proof.model_dump(mode="json");data["signature_ed25519"]="0"*128
    assert "attestation_signature_invalid" in run(proof=AuthenticatedAttestation.model_validate(data))["reasons"]


@pytest.mark.parametrize("at", [T0-timedelta(seconds=1),T0+timedelta(hours=2),T0+timedelta(hours=3)])
def test_attestation_outside_validity_never_accepted(at):
    assert "attestation_outside_validity" in run(at=at)["reasons"]


def test_missing_stale_or_rolled_back_revocation_snapshot_is_not_accepted():
    assert "revocation_snapshot_missing" in run(rev=None)["reasons"]
    assert "revocation_snapshot_stale" in run(rev=snapshot(valid_until=T0+timedelta(minutes=10)))["reasons"]
    assert "revocation_sequence_rollback" in run(rev=snapshot(sequence=1),floor=2)["reasons"]
    assert "revocation_sequence_floor_invalid" in run(floor=0)["reasons"]
    assert "revocation_sequence_floor_invalid" in run(floor=True)["reasons"]


def test_revoked_proof_stays_rejected_at_current_sequence():
    current=snapshot(sequence=3,revoked_attestation_ids=("att-a",))
    assert "attestation_revoked" in run(rev=current,floor=3)["reasons"]
    # A formerly clean snapshot cannot be replayed against the independent floor.
    assert "revocation_sequence_rollback" in run(rev=snapshot(sequence=2),floor=3)["reasons"]
    # A newer signed snapshot cannot silently erase an independently anchored revocation.
    assert "revocation_history_truncated" in run(rev=snapshot(sequence=4),floor=3,known_revoked=frozenset({"att-a"}))["reasons"]
    assert "revocation_history_anchor_invalid" in run(known_revoked=None)["reasons"]


def test_revocation_snapshot_tamper_and_scope_mismatch_rejected():
    raw=snapshot().model_dump(mode="json");raw["statement"]["sequence"]=4
    assert "revocation_signature_invalid" in run(rev=AuthenticatedRevocations.model_validate(raw))["reasons"]
    assert "revocation_scope_mismatch" in run(authority="other")["reasons"]
    assert "revocation_scope_mismatch" in run(ledger="other")["reasons"]
    assert "revocation_trust_anchor_missing" in run(ledger="")["reasons"]


def test_untrusted_wrong_role_disabled_and_rotated_keys_rejected():
    trust=keys(); trust.pop("issuer-key-a")
    assert "issuer_key_untrusted" in run(trust=trust)["reasons"]
    trust=keys();trust["issuer-key-a"]=replace(trust["issuer-key-a"],role="technical_reviewer")
    assert "issuer_key_untrusted" in run(trust=trust)["reasons"]
    trust=keys();trust["issuer-key-a"]=replace(trust["issuer-key-a"],active=False)
    assert "issuer_key_untrusted" in run(trust=trust)["reasons"]
    trust=keys();trust["issuer-key-a"]=replace(trust["issuer-key-a"],public_key=ROTATED_PUBLIC)
    assert "attestation_signature_invalid" in run(trust=trust)["reasons"]
    trust=keys();trust["revoker-key-a"]=replace(trust["revoker-key-a"],active=False)
    assert "revocation_key_untrusted" in run(trust=trust)["reasons"]


def test_scope_permission_and_role_requirements():
    trust=keys();trust["issuer-key-a"]=replace(trust["issuer-key-a"],allowed_scopes=frozenset({"policy"}))
    assert "issuer_scope_not_allowed" in run(trust=trust)["reasons"]
    with pytest.raises(ValidationError):
        statement(issuer_role="technical_reviewer")
    deployment=DeploymentScope(kind="deployment",environment="production",build_manifest_hash=HASH,network_policy_hash=HASH)
    with pytest.raises(ValidationError):
        statement(scope=deployment,issuer_role="legal_reviewer")
    policy=PolicyScope(kind="policy",domain="labor",pack_id="pack-a",pack_content_hash=HASH,jurisdiction="CN")
    proof=authenticate_statement(statement(scope=policy),ISSUE_KEY)
    assert run(proof=proof,expected=policy)["state"] == "diagnostic_match"


@pytest.mark.parametrize("field,value", [("provider_id","*"),("purpose","*"),("endpoint","http://provider.invalid"),
    ("endpoint","https://user:pass@provider.invalid"),("endpoint","https://provider.invalid/#x"),
    ("endpoint","https://provider.invalid/\n"),("endpoint","https://provider.invalid\\x")])
def test_wildcards_and_unsafe_endpoint_are_rejected(field,value):
    with pytest.raises(ValidationError):scope(**{field:value})


def test_missing_evidence_naive_timestamps_and_extra_fields_rejected():
    with pytest.raises(ValidationError):statement(evidence_hashes=())
    with pytest.raises(ValidationError):statement(issued_at=datetime(2026,1,1))
    with pytest.raises(ValidationError):statement(issued_at=1767225600)
    with pytest.raises(ValidationError):statement(issued_at="1767225600")
    with pytest.raises(ValidationError):statement(valid_until=T0)
    with pytest.raises(ValidationError):statement(evidence_hashes=(HASH,HASH))
    with pytest.raises(ValidationError):AttestationStatement.model_validate({**statement().model_dump(),"unexpected":True})
    with pytest.raises(ValidationError):RevocationStatement(ledger_id="a",sequence=1,authority_id="r",key_id="k",issued_at=T0,valid_until=T0+timedelta(hours=1),revoked_attestation_ids=("x","x"))
    with pytest.raises(ValueError):TrustedKey("k","o","r","attestation",frozenset(),b"short")


def test_domain_separation_prevents_attestation_signature_as_revocation_signature():
    proof=authenticate_statement(statement(),ISSUE_KEY)
    raw=snapshot().model_dump(mode="json");raw["signature_ed25519"]=proof.signature_ed25519
    assert "revocation_signature_invalid" in run(rev=AuthenticatedRevocations.model_validate(raw))["reasons"]


def test_no_production_gate_imports_experimental_module():
    root=Path(__file__).resolve().parents[1]/"lexaegis"
    for name in ("formal_release.py","release_service.py","outbound_gate.py","gateway.py","evidence.py"):
        assert "scoped_attestation_shadow" not in (root/name).read_text()


def test_shadow_ledger_persists_revocation_and_requires_external_anchor(tmp_path):
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    path=tmp_path/"ledger.sqlite";store=Store(path)
    ledger=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=2,known_revoked_ids=frozenset())
    with pytest.raises(ShadowLedgerError,match="snapshot_missing"):ledger.current(at=NOW)
    assert ledger.ingest(snapshot(),at=NOW)=={"state":"stored_shadow","sequence":2,"authoritative":False}
    newer=snapshot(sequence=3,revoked_attestation_ids=("att-a",))
    ledger.ingest(newer,at=NOW)
    with pytest.raises(ShadowLedgerError,match="sequence_rollback|sequence_not_newer"):ledger.ingest(snapshot(),at=NOW)
    store.engine.dispose()
    reopened=Store(path)
    try:
        anchored=ShadowRevocationLedger(reopened,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=3,known_revoked_ids=frozenset({"att-a"}))
        current=anchored.current(at=NOW)
        assert current.statement.sequence==3
        assert "attestation_revoked" in run(rev=current,floor=3,known_revoked=frozenset({"att-a"}))["reasons"]
        with reopened.read() as repo: rows=repo.list("v3_shadow_revocation")
        assert len(rows)==1 and repr(ISSUE_PRIVATE_BYTES) not in repr(rows) and repr(REVOKE_PRIVATE_BYTES) not in repr(rows)
    finally:reopened.engine.dispose()


def test_new_external_anchor_can_advance_stale_local_snapshot(tmp_path):
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    store=Store(tmp_path/"ledger.sqlite")
    try:
        original=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=2,known_revoked_ids=frozenset())
        original.ingest(snapshot(),at=NOW)
        newer=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=3,known_revoked_ids=frozenset({"att-a"}))
        with pytest.raises(ShadowLedgerError):newer.current(at=NOW)
        newer.ingest(snapshot(sequence=3,revoked_attestation_ids=("att-a",)),at=NOW)
        assert newer.current(at=NOW).statement.sequence==3
    finally:store.engine.dispose()


def test_shadow_ledger_rejects_tampering_truncation_and_expiry(tmp_path):
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    store=Store(tmp_path/"ledger.sqlite")
    try:
        ledger=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=2,known_revoked_ids=frozenset())
        ledger.ingest(snapshot(revoked_attestation_ids=("att-a",)),at=NOW)
        with pytest.raises(ShadowLedgerError,match="history_truncated"):ledger.ingest(snapshot(sequence=3),at=NOW)
        assert ledger.current(at=NOW).statement.sequence==2
        with pytest.raises(ShadowLedgerError,match="snapshot_stale"):ledger.current(at=T0+timedelta(hours=1))
        with store.transaction() as repo:
            row=repo.get(ledger.record_id);row["snapshot"]["statement"]["sequence"]=99
            repo.put("v3_shadow_revocation",row)
        with pytest.raises(ShadowLedgerError,match="signature_invalid"):ledger.current(at=NOW)
        with pytest.raises(ShadowLedgerError,match="signature_invalid"):ledger.ingest(snapshot(sequence=100,revoked_attestation_ids=("att-a",)),at=NOW)
    finally:store.engine.dispose()


def test_concurrent_same_sequence_has_no_lost_update(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    store=Store(tmp_path/"ledger.sqlite")
    try:
        ledger=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=2,known_revoked_ids=frozenset())
        ledger.ingest(snapshot(),at=NOW)
        def attempt(ident):
            try:ledger.ingest(snapshot(sequence=3,revoked_attestation_ids=(ident,)),at=NOW);return "stored"
            except ShadowLedgerError:return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(attempt,["att-a","att-b"]))
        assert sorted(out)==["rejected","stored"]
        current=ledger.current(at=NOW)
        assert current.statement.sequence==3 and len(current.statement.revoked_attestation_ids)==1
        ledger.ingest(snapshot(sequence=4,revoked_attestation_ids=("att-a","att-b")),at=NOW)
        assert set(ledger.current(at=NOW).statement.revoked_attestation_ids)=={"att-a","att-b"}
    finally:store.engine.dispose()


def test_ledger_does_not_overwrite_different_record_kind(tmp_path):
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    store=Store(tmp_path/"ledger.sqlite")
    try:
        ledger=ShadowRevocationLedger(store,trusted_keys=keys(),authority_id="revoker-a",ledger_id="ledger-a",external_floor=2,known_revoked_ids=frozenset())
        with store.transaction() as repo:repo.put("other_kind",{"id":ledger.record_id,"record_type":ledger._KIND,
            "ledger_id":"ledger-a","snapshot":snapshot().model_dump(mode="json")})
        with pytest.raises(ShadowLedgerError,match="record_collision"):ledger.ingest(snapshot(),at=NOW)
        with store.read() as repo:
            assert repo.get(ledger.record_id,"other_kind")["record_type"] == ledger._KIND
    finally:store.engine.dispose()


def test_detects_local_database_rollback_with_observed_and_external_anchors(tmp_path):
    from lexaegis.scoped_attestation_shadow import ShadowRevocationLedger, ShadowLedgerError
    from lexaegis.storage import Store
    store = Store(tmp_path / "ledger.sqlite")
    try:
        ledger = ShadowRevocationLedger(store, trusted_keys=keys(), authority_id="revoker-a",
                                        ledger_id="ledger-a", external_floor=2,
                                        known_revoked_ids=frozenset())
        ledger.ingest(snapshot(), at=NOW)
        with store.read() as repo:
            old_record = repo.get(ledger.record_id)
        ledger.ingest(snapshot(sequence=3, revoked_attestation_ids=("att-a",)), at=NOW)
        with store.transaction() as repo:
            repo.put("v3_shadow_revocation", old_record)
        with pytest.raises(ShadowLedgerError, match="sequence_rollback|history_truncated"):
            ledger.current(at=NOW)
        restarted = ShadowRevocationLedger(store, trusted_keys=keys(), authority_id="revoker-a",
                                           ledger_id="ledger-a", external_floor=3,
                                           known_revoked_ids=frozenset({"att-a"}))
        with pytest.raises(ShadowLedgerError, match="sequence_rollback|history_truncated"):
            restarted.current(at=NOW)
    finally:
        store.engine.dispose()
