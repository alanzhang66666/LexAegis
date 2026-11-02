"""V3 Ed25519 scope-attestation and revocation primitives.

These models and verifiers are now reused by ``attestation_registry`` on the
production path, which supplies the external trust anchor, the persisted
revocation snapshot and the four-gate binding. This module itself still holds
no key, no anchor and no authority: signature verification is NOT proof of an
authenticated human, legal review, evidence verification, isolation, reusable
authorization, or permission to send. Keys and the monotonic revocation floor
must come from a trusted external authority (``LEX_V3_TRUST_ANCHOR``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from threading import RLock
from typing import Annotated, Literal, Mapping, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from .util import canonical

ID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
SHA256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SIGNATURE = Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]


class _Immutable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeploymentScope(_Immutable):
    kind: Literal["deployment"]
    environment: Literal["production", "integration"]
    build_manifest_hash: SHA256
    network_policy_hash: SHA256


class RecipientScope(_Immutable):
    kind: Literal["recipient"]
    provider_id: ID
    provider_profile_hash: SHA256
    endpoint: str = Field(min_length=9, max_length=2048)
    model: ID
    purpose: ID
    jurisdiction: ID
    processing_region: ID

    @field_validator("endpoint")
    @classmethod
    def https_endpoint(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or "*" in value or "\\" in value
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("endpoint must be an exact https URL without userinfo or fragment")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid endpoint port") from exc
        return value


class PolicyScope(_Immutable):
    kind: Literal["policy"]
    domain: ID
    pack_id: ID
    pack_content_hash: SHA256
    jurisdiction: ID


Scope = Annotated[Union[DeploymentScope, RecipientScope, PolicyScope], Field(discriminator="kind")]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def _timestamp_input(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid ISO timestamp") from exc
    raise ValueError("timestamp must be an ISO string or datetime")


class AttestationStatement(_Immutable):
    schema_version: Literal[1] = 1
    attestation_id: ID
    scope: Scope
    issuer_id: ID
    issuer_role: Literal["technical_reviewer", "legal_reviewer"]
    key_id: ID
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    evidence_hashes: tuple[SHA256, ...] = Field(min_length=1, max_length=64)

    @field_validator("issued_at", "valid_from", "valid_until", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        return _timestamp_input(value)

    @field_validator("issued_at", "valid_from", "valid_until")
    @classmethod
    def timestamp_utc(cls, value):
        return _utc(value)

    @model_validator(mode="after")
    def coherent(self):
        if not self.issued_at <= self.valid_from < self.valid_until:
            raise ValueError("invalid attestation validity interval")
        if len(set(self.evidence_hashes)) != len(self.evidence_hashes):
            raise ValueError("duplicate evidence hashes")
        required_role = "technical_reviewer" if self.scope.kind == "deployment" else "legal_reviewer"
        if self.issuer_role != required_role:
            raise ValueError("issuer role does not match scope")
        return self


class AuthenticatedAttestation(_Immutable):
    statement: AttestationStatement
    signature_ed25519: SIGNATURE


class RevocationStatement(_Immutable):
    schema_version: Literal[1] = 1
    ledger_id: ID
    sequence: int = Field(strict=True, ge=1)
    authority_id: ID
    key_id: ID
    issued_at: datetime
    valid_until: datetime
    revoked_attestation_ids: tuple[ID, ...] = Field(max_length=10000)

    @field_validator("issued_at", "valid_until", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        return _timestamp_input(value)

    @field_validator("issued_at", "valid_until")
    @classmethod
    def timestamp_utc(cls, value):
        return _utc(value)

    @model_validator(mode="after")
    def coherent(self):
        if self.issued_at >= self.valid_until:
            raise ValueError("invalid revocation validity interval")
        if len(set(self.revoked_attestation_ids)) != len(self.revoked_attestation_ids):
            raise ValueError("duplicate revocation ids")
        return self


class AuthenticatedRevocations(_Immutable):
    statement: RevocationStatement
    signature_ed25519: SIGNATURE


@dataclass(frozen=True)
class TrustedKey:
    """Externally configured public verification key; private key never stored."""
    key_id: str
    owner_id: str
    role: str
    purpose: Literal["attestation", "revocation"]
    allowed_scopes: frozenset[str]
    public_key: bytes
    active: bool = True

    def __post_init__(self):
        if not isinstance(self.public_key, bytes) or len(self.public_key) != 32:
            raise ValueError("an Ed25519 public key must be 32 raw bytes")
        if not self.key_id or not self.owner_id or not self.role:
            raise ValueError("trusted key identity, owner and role required")


def _signed_payload(domain: str, statement: _Immutable) -> bytes:
    return domain.encode("ascii") + b"\x00" + canonical(statement.model_dump(mode="json")).encode("utf-8")


def authenticate_statement(statement: AttestationStatement, private_key: Ed25519PrivateKey) -> AuthenticatedAttestation:
    """For controlled experiments only; does not authenticate the calling user."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("an Ed25519 private signing key is required")
    return AuthenticatedAttestation(statement=statement, signature_ed25519=private_key.sign(
        _signed_payload("lexaegis.v3.attestation.v1", statement)).hex())


def authenticate_revocations(statement: RevocationStatement, private_key: Ed25519PrivateKey) -> AuthenticatedRevocations:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("an Ed25519 private signing key is required")
    return AuthenticatedRevocations(statement=statement, signature_ed25519=private_key.sign(
        _signed_payload("lexaegis.v3.revocation.v1", statement)).hex())


def _signature_valid(domain: str, statement: _Immutable, signature: str, public_key: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(bytes.fromhex(signature), _signed_payload(domain, statement))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _key_matches(key: TrustedKey | None, key_id: str, owner: str, role: str, purpose: str) -> bool:
    return bool(isinstance(key, TrustedKey) and key.active is True and key.key_id == key_id and key.owner_id == owner
                and key.role == role and key.purpose == purpose)


def _revocation_reasons(revocations, trusted_keys, expected_authority, expected_ledger,
                        minimum_sequence, minimum_ids, at, *, require_fresh=True):
    reasons = []
    if isinstance(minimum_sequence, bool) or not isinstance(minimum_sequence, int) or minimum_sequence < 1:
        reasons.append("revocation_sequence_floor_invalid")
    trusted_ids = isinstance(minimum_ids, frozenset) and all(isinstance(item, str) and item for item in minimum_ids)
    if not trusted_ids:
        reasons.append("revocation_history_anchor_invalid")
    if not expected_ledger or not expected_authority:
        reasons.append("revocation_trust_anchor_missing")
    if revocations is None:
        return reasons + ["revocation_snapshot_missing"]
    rev = revocations.statement
    rev_key = trusted_keys.get(rev.key_id)
    if rev.authority_id != expected_authority or rev.ledger_id != expected_ledger:
        reasons.append("revocation_scope_mismatch")
    if not _key_matches(rev_key, rev.key_id, rev.authority_id, "revocation_authority", "revocation"):
        reasons.append("revocation_key_untrusted")
    elif not _signature_valid("lexaegis.v3.revocation.v1", rev, revocations.signature_ed25519, rev_key.public_key):
        reasons.append("revocation_signature_invalid")
    if require_fresh and not rev.issued_at <= at < rev.valid_until:
        reasons.append("revocation_snapshot_stale")
    if isinstance(minimum_sequence, int) and not isinstance(minimum_sequence, bool) and rev.sequence < minimum_sequence:
        reasons.append("revocation_sequence_rollback")
    if trusted_ids and not minimum_ids.issubset(rev.revoked_attestation_ids):
        reasons.append("revocation_history_truncated")
    return reasons


def inspect_attestation(
    attestation: AuthenticatedAttestation,
    expected_scope: Scope,
    revocations: AuthenticatedRevocations | None,
    *,
    trusted_keys: Mapping[str, TrustedKey],
    expected_revocation_authority: str,
    expected_ledger_id: str,
    minimum_revocation_sequence: int,
    minimum_revoked_ids: frozenset[str],
    at: datetime,
) -> dict:
    """Check signatures and a fresh, externally anchored revocation snapshot.

    Inputs must already be schema-validated models. A caller must independently
    establish the trusted keys, expected scope, monotonic sequence floor and
    complete set of already revoked IDs;
    accepting these from the proof itself enables forgery or rollback. Artifact
    bytes and signer identity are NOT verified. Nothing authorizes dispatch.
    """
    at = _utc(at)
    reasons: list[str] = []
    stmt = attestation.statement
    issuer_key = trusted_keys.get(stmt.key_id)
    if not _key_matches(issuer_key, stmt.key_id, stmt.issuer_id, stmt.issuer_role, "attestation"):
        reasons.append("issuer_key_untrusted")
    elif stmt.scope.kind not in issuer_key.allowed_scopes:
        reasons.append("issuer_scope_not_allowed")
    elif not _signature_valid("lexaegis.v3.attestation.v1", stmt, attestation.signature_ed25519, issuer_key.public_key):
        reasons.append("attestation_signature_invalid")
    if stmt.scope != expected_scope:
        reasons.append("scope_mismatch")
    if not stmt.issued_at <= at or not stmt.valid_from <= at < stmt.valid_until:
        reasons.append("attestation_outside_validity")
    reasons.extend(_revocation_reasons(revocations, trusted_keys, expected_revocation_authority,
                                       expected_ledger_id, minimum_revocation_sequence, minimum_revoked_ids, at))
    if revocations is not None and stmt.attestation_id in revocations.statement.revoked_attestation_ids:
        reasons.append("attestation_revoked")
    return {
        "state": "diagnostic_match" if not reasons else "not_accepted",
        "reasons": reasons,
        "authoritative": False,
        "evidence_bytes_verified": False,
        "human_identity_verified": False,
        "notice": "仅校验本地实验签名、范围、有效期和撤销快照，不授予批准、复用或发送权限。",
    }


class ShadowLedgerError(ValueError):
    """The experimental local revocation state cannot be trusted."""


class ShadowRevocationLedger:
    """Locally persist signed snapshots under a serialized Store transaction.

    The caller MUST supply an independently maintained monotonic floor and known
    revoked-ID set. This experimental ledger does not provide a trustworthy
    external anchor, authenticated actors, production invalidation, or permission.
    """
    _KIND = "v3_shadow_revocation"

    def __init__(self, store, *, trusted_keys, authority_id, ledger_id, external_floor, known_revoked_ids):
        if (not authority_id or not ledger_id or isinstance(external_floor, bool)
                or not isinstance(external_floor, int) or external_floor < 1
                or not isinstance(known_revoked_ids, frozenset)
                or any(not isinstance(item, str) or not item for item in known_revoked_ids)):
            raise ShadowLedgerError("independent revocation trust anchors required")
        self.store = store
        self.trusted_keys = dict(trusted_keys)
        self.authority_id, self.ledger_id = authority_id, ledger_id
        self.external_floor, self.known_revoked_ids = external_floor, known_revoked_ids
        self._observed_floor, self._observed_ids = external_floor, known_revoked_ids
        self._lock = RLock()
        self.record_id = "v3-shadow-revocation-" + hashlib.sha256(ledger_id.encode()).hexdigest()

    def _validate(self, snapshot, at, *, floor=None, known=None, fresh=True):
        failures = _revocation_reasons(snapshot, self.trusted_keys, self.authority_id, self.ledger_id,
                                       self._observed_floor if floor is None else floor,
                                       self._observed_ids if known is None else known,
                                       _utc(at), require_fresh=fresh)
        if failures:
            raise ShadowLedgerError(";".join(failures))

    def _read(self, repo):
        try:
            repo.get(self.record_id)
        except KeyError:
            return None
        try:
            record = repo.get(self.record_id, self._KIND)
        except KeyError as exc:
            raise ShadowLedgerError("revocation_record_collision") from exc
        if not isinstance(record, dict) or record.get("record_type") != self._KIND or record.get("ledger_id") != self.ledger_id:
            raise ShadowLedgerError("revocation_record_collision")
        try:
            return AuthenticatedRevocations.model_validate(record["snapshot"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ShadowLedgerError("revocation_record_invalid") from exc

    def ingest(self, snapshot: AuthenticatedRevocations, *, at: datetime):
        """Verify and replace only with a newer, non-truncating signed snapshot."""
        if not isinstance(snapshot, AuthenticatedRevocations):
            raise ShadowLedgerError("revocation_snapshot_invalid")
        with self._lock:
            self._validate(snapshot, at)
            with self.store.transaction() as repo:
                previous = self._read(repo)
                if previous is not None:
                    # An expired prior snapshot may be superseded, but its signature
                    # must still hold; the candidate separately satisfies the anchors.
                    self._validate(previous, at, floor=1, known=frozenset(), fresh=False)
                    if snapshot.statement.sequence <= previous.statement.sequence:
                        raise ShadowLedgerError("revocation_sequence_not_newer")
                    if not set(previous.statement.revoked_attestation_ids).issubset(snapshot.statement.revoked_attestation_ids):
                        raise ShadowLedgerError("revocation_history_truncated")
                repo.put(self._KIND, {"id": self.record_id, "record_type": self._KIND,
                                     "ledger_id": self.ledger_id, "snapshot": snapshot.model_dump(mode="json")})
            self._observed_floor = max(self._observed_floor, snapshot.statement.sequence)
            self._observed_ids = self._observed_ids | frozenset(snapshot.statement.revoked_attestation_ids)
        return {"state": "stored_shadow", "sequence": snapshot.statement.sequence, "authoritative": False}

    def current(self, *, at: datetime) -> AuthenticatedRevocations:
        """Read only a fresh, signature-valid snapshot satisfying external anchors."""
        with self._lock:
            with self.store.read() as repo:
                snapshot = self._read(repo)
            if snapshot is None:
                raise ShadowLedgerError("revocation_snapshot_missing")
            self._validate(snapshot, at)
            self._observed_floor = max(self._observed_floor, snapshot.statement.sequence)
            self._observed_ids = self._observed_ids | frozenset(snapshot.statement.revoked_attestation_ids)
            return snapshot
