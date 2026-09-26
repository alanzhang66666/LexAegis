"""Content-addressed storage and structured intake for protected evidence.

Artifact bytes live only in the configured controlled directory. The business
store contains metadata and opaque content references; audit records contain
only identifiers, hashes, and media type. Gate receipts preserve bindings to
existing templates without copying protected evidence into audit data.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    EvidenceArtifact,
    EvidenceRoleAction,
    GateEvidenceReceipt,
    GateReceiptInput,
)
from .storage import Store
from .util import assert_local_filesystem, audit, digest, now, restrict_mode, uid


_ARTIFACT_KIND = "evidence_artifact"
_RECEIPT_KIND = "gate_evidence_receipt"
_ROLE_ACTION_KIND = "evidence_role_action"
_STORAGE_REF_RE = re.compile(r"sha256:([0-9a-f]{64})\Z")
_TEMPLATE_CODE_RE = re.compile(r"(法|技)\s*0?(\d{1,2})")
_VERSION_BOUND_GATES = frozenset({"G1", "G2", "G3", "G5"})
_REQUEST_BOUND_GATES = frozenset({"G6", "G7", "G8", "G9", "G10"})
_TEMPLATE_GATES = {
    "G1": frozenset({"法01"}),
    "G2": frozenset({"法02"}),
    "G3": frozenset({"法03", "法04", "技01"}),
    "G5": frozenset({"法05", "技02"}),
    "G6": frozenset({"法07", "技03"}),
    "G7": frozenset({"法08"}),
    "G8": frozenset({"法09"}),
    "G9": frozenset({"法10"}),
    "G10": frozenset({"技08"}),
}
_TECHNICAL_CONFIRMATION_TEMPLATES = {
    "G7": "技04",
    "G8": "技05",
    "G9": "技06",
}
_TUPLE_KEYS = frozenset({"case_id", "purpose", "recipient"})
_LEGAL_REVIEW_ROLE = "legal_reviewer"
_ENGINEERING_RECORD_ROLE = "case_operator"
_TECHNICAL_REVIEW_ROLE = "technical_reviewer"
_APPROVAL_ROLE = "approver"
_REVOCATION_ROLES = frozenset({"admin", _LEGAL_REVIEW_ROLE, _ENGINEERING_RECORD_ROLE, _TECHNICAL_REVIEW_ROLE, _APPROVAL_ROLE})
_ROLE_ACTIONS = {
    _LEGAL_REVIEW_ROLE: "legal_confirmation",
    _ENGINEERING_RECORD_ROLE: "engineering_record",
    _TECHNICAL_REVIEW_ROLE: "engineering_record",
    _APPROVAL_ROLE: "g10_approval",
}
_NAMED_ROLES = frozenset(_ROLE_ACTIONS)
_REVOCATION_ACTION = "evidence_revocation"

# Dependency propagation is deliberately receipt-specific until the generic
# reverse-dependency graph lands. Gateway records are read only to detect a
# claim and are never rewritten; no aggregate is deleted.
_FROZEN_REQUEST_KINDS = ("frozen_formal_request", "frozen_request")
_SNAPSHOT_KINDS = ("gate_snapshot", "evidence_snapshot")
_INTENT_KIND = "dispatch_intent"
_GRANT_KIND = "one_time_dispatch_grant"
_GATEWAY_RECORD_KIND = "gateway_record"
_UNCLAIMED_GRANT_STATES = frozenset({"pending", "issued", "reserved"})
_PENDING_INTENT_STATES = frozenset({"pending", "queued", "reserved"})
_CLAIMED_STATES = frozenset({
    "claimed",
    "sending",
    "complete",
    "unknown",
    "consumed",
    "consumed_complete",
    "consumed_unknown",
    "failed_before_disclosure",
})


class EvidenceStoreError(RuntimeError):
    """Base error for evidence storage failures."""


class EvidenceIntegrityError(EvidenceStoreError):
    """Raised when controlled bytes no longer match their content address."""


class EvidenceReceiptError(EvidenceStoreError):
    """Raised when a template cannot support the requested receipt state."""


class EvidenceStore:
    """Store protected bytes by SHA-256 and metadata in the business database."""

    def __init__(self, store: Store, controlled_root: Path):
        root = Path(controlled_root).resolve()
        assert_local_filesystem(root)
        root.mkdir(parents=True, exist_ok=True)
        restrict_mode(root, 0o700)
        self.store = store
        self.controlled_root = root

    def register_artifact(
        self,
        *,
        content: bytes,
        media_type: str,
        source_path_hint: str,
        actor: str,
        template_kind: str | None = None,
    ) -> EvidenceArtifact:
        """Persist bytes once and append metadata plus a plaintext-free audit event."""
        if not isinstance(content, bytes) or not content:
            raise ValueError("evidence content must be nonempty bytes")
        media_type = media_type.strip()
        actor = actor.strip()
        source_path_hint = source_path_hint.strip()
        template_kind = template_kind.strip() if template_kind else None
        if not media_type or len(media_type) > 255:
            raise ValueError("media_type must be between 1 and 255 characters")
        if not actor:
            raise ValueError("actor must be nonempty")
        if len(source_path_hint) > 1000:
            raise ValueError("source_path_hint must not exceed 1000 characters")
        if template_kind is not None and len(template_kind) > 100:
            raise ValueError("template_kind must not exceed 100 characters")

        content_hash = hashlib.sha256(content).hexdigest()
        storage_ref = f"sha256:{content_hash}"
        target = self._path_for_ref(storage_ref)
        created_blob = False

        try:
            with self.store.transaction() as repo:
                if target.exists():
                    self._verify_path(target, content_hash)
                else:
                    created_blob = self._write_blob(target, content)

                artifact = EvidenceArtifact(
                    id=uid("evidence"),
                    content_hash=content_hash,
                    media_type=media_type,
                    source_path_hint=source_path_hint,
                    template_kind=template_kind,
                    created_at=now(),
                    registered_by=actor,
                    storage_ref=storage_ref,
                )
                repo.put(_ARTIFACT_KIND, artifact.model_dump(mode="json"))
                audit(
                    repo,
                    "",
                    "evidence.registered",
                    evidence_id=artifact.id,
                    content_hash=content_hash,
                    media_type=media_type,
                    storage_ref=storage_ref,
                    actor=actor,
                )
                return artifact
        except BaseException:
            if created_blob:
                target.unlink(missing_ok=True)
            raise

    def get_artifact(self, artifact_id: str) -> EvidenceArtifact:
        """Return business metadata without loading protected content."""
        with self.store.read() as repo:
            record = repo.get(artifact_id, _ARTIFACT_KIND)
        return EvidenceArtifact.model_validate(record)

    def artifact_ids_by_hash(self, content_hash: str) -> list[str]:
        """Return artifact ids whose registered content_hash matches, oldest first."""
        content_hash = content_hash.strip().lower()
        with self.store.read() as repo:
            return [
                item["id"] for item in repo.list(_ARTIFACT_KIND)
                if item.get("content_hash") == content_hash
            ]

    def verified_artifact_by_hash(self, content_hash: str) -> EvidenceArtifact | None:
        """Resolve a content hash to an artifact whose bytes re-verify, else None."""
        for artifact_id in self.artifact_ids_by_hash(content_hash):
            try:
                self.read_artifact(artifact_id)
            except (EvidenceIntegrityError, KeyError):
                continue
            return self.get_artifact(artifact_id)
        return None

    def read_artifact(self, artifact_id: str) -> bytes:
        """Load protected content through its opaque reference and verify SHA-256."""
        artifact = self.get_artifact(artifact_id)
        target = self._path_for_ref(artifact.storage_ref)
        if not target.is_file():
            raise EvidenceIntegrityError("evidence content is missing")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.content_hash:
            raise EvidenceIntegrityError("evidence content hash mismatch")
        return content

    def _path_for_ref(self, storage_ref: str) -> Path:
        match = _STORAGE_REF_RE.fullmatch(storage_ref)
        if match is None:
            raise EvidenceIntegrityError("invalid evidence storage reference")
        content_hash = match.group(1)
        return self.controlled_root / "sha256" / content_hash[:2] / content_hash[2:4] / content_hash

    @staticmethod
    def _verify_path(path: Path, expected_hash: str) -> None:
        if not path.is_file():
            raise EvidenceIntegrityError("content address is not a regular file")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise EvidenceIntegrityError("content-addressed evidence failed integrity check")

    @staticmethod
    def _write_blob(target: Path, content: bytes) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        restrict_mode(target.parent, 0o700)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            restrict_mode(temporary, 0o600)
            if target.exists():
                temporary.unlink()
                EvidenceStore._verify_path(target, target.name)
                return False
            os.replace(temporary, target)
            restrict_mode(target, 0o600)
            return True
        finally:
            temporary.unlink(missing_ok=True)


class EvidenceIntakeService:
    """Map completed existing templates to fail-closed gate evidence receipts."""

    def __init__(self, evidence_store: EvidenceStore):
        self.evidence_store = evidence_store
        self.store = evidence_store.store

    def record_gate_receipt(
        self,
        receipt_input: GateReceiptInput | dict,
        *,
        actor: str,
        at: datetime | None = None,
    ) -> GateEvidenceReceipt:
        """Validate template bindings and persist one structured receipt.

        This method records supplied conclusions; it never infers a signer,
        legal conclusion, authorization, or technical result from a filename.
        """
        data = GateReceiptInput.model_validate(receipt_input)
        actor = actor.strip()
        if not actor:
            raise EvidenceReceiptError("recording actor must be nonempty")
        recorded_at = _as_utc(at or datetime.now(timezone.utc), "at")
        release_tuple = _validate_tuple(data.tuple)
        template_kind = _template_code(data.template_kind)
        allowed_templates = _TEMPLATE_GATES.get(data.gate_id)
        if allowed_templates is None or template_kind not in allowed_templates:
            raise EvidenceReceiptError(
                f"{template_kind or data.template_kind!r} is not an existing template for {data.gate_id}"
            )

        template_version = _clean(data.template_version)
        bound_versions = _clean_mapping(data.bound_versions)
        request_hash = _clean(data.request_hash)
        artifact_ids = _clean_unique(data.evidence_artifact_ids, "evidence_artifact_ids")

        if data.gate_id in _VERSION_BOUND_GATES:
            if not template_version or not bound_versions:
                raise EvidenceReceiptError(
                    f"{data.gate_id} receipt must bind a template version and exact dependency versions"
                )
        if data.gate_id in _REQUEST_BOUND_GATES and not request_hash:
            raise EvidenceReceiptError(f"{data.gate_id} receipt must bind request_hash")

        confirmed_by = _clean(data.confirmed_by)
        confirmed_role = _clean(data.confirmed_role)
        confirmed_at = _clean(data.confirmed_at)
        valid_from = _clean(data.valid_from)
        valid_until = _clean(data.valid_until)
        revoked_at = _clean(data.revoked_at)
        adopted_fact_ids = _clean_unique(data.adopted_fact_ids, "adopted_fact_ids")
        template_artifact_id = _clean(data.template_artifact_id)
        organization_artifact_id = _clean(data.organization_authorization_artifact_id)
        technical_artifact_id = _clean(data.technical_evidence_artifact_id)
        technical_evidence_hash = _normalize_hash(data.technical_evidence_hash)
        technical_request_hash = _clean(data.technical_evidence_request_hash)

        parsed_confirmed_at = _optional_timestamp(confirmed_at, "confirmed_at")
        parsed_valid_from = _optional_timestamp(valid_from, "valid_from")
        parsed_valid_until = _optional_timestamp(valid_until, "valid_until")
        _optional_timestamp(revoked_at, "revoked_at")
        self._validate_role_action(
            gate_id=data.gate_id,
            template_kind=template_kind,
            confirmed_by=confirmed_by,
            confirmed_role=confirmed_role,
            parsed_confirmed_at=parsed_confirmed_at,
            recorded_at=recorded_at,
        )

        with self.store.transaction() as repo:
            artifacts = self._load_artifacts(repo, artifact_ids, verify=data.conclusion == "pass")
            artifact_by_id = {artifact.id: artifact for artifact in artifacts}

            if data.conclusion == "pass":
                self._validate_pass(
                    data=data,
                    recorded_at=recorded_at,
                    artifacts=artifact_by_id,
                    artifact_ids=artifact_ids,
                    template_kind=template_kind,
                    template_artifact_id=template_artifact_id,
                    confirmed_by=confirmed_by,
                    confirmed_role=confirmed_role,
                    parsed_confirmed_at=parsed_confirmed_at,
                    parsed_valid_from=parsed_valid_from,
                    parsed_valid_until=parsed_valid_until,
                    revoked_at=revoked_at,
                    adopted_fact_ids=adopted_fact_ids,
                    organization_artifact_id=organization_artifact_id,
                    request_hash=request_hash,
                    technical_artifact_id=technical_artifact_id,
                    technical_evidence_hash=technical_evidence_hash,
                    technical_request_hash=technical_request_hash,
                )

            manifest_entries = [
                {
                    "id": artifact.id,
                    "content_hash": artifact.content_hash,
                    "template_kind": _template_code(artifact.template_kind),
                }
                for artifact in sorted(artifacts, key=lambda item: item.id)
            ]
            manifest_hash = digest(
                {
                    "gate_id": data.gate_id,
                    "tuple": release_tuple,
                    "template_kind": template_kind,
                    "template_version": template_version,
                    "bound_versions": bound_versions,
                    "request_hash": request_hash,
                    "artifacts": manifest_entries,
                    "technical_evidence_hash": technical_evidence_hash,
                    "technical_evidence_request_hash": technical_request_hash,
                }
            )
            receipt = GateEvidenceReceipt(
                id=uid("gate_receipt"),
                gate_id=data.gate_id,
                tuple=release_tuple,
                template_kind=template_kind,
                template_version=template_version,
                template_artifact_id=template_artifact_id,
                bound_versions=bound_versions,
                request_hash=request_hash,
                conclusion=data.conclusion,
                evidence_artifact_ids=artifact_ids,
                evidence_manifest_hash=manifest_hash,
                confirmed_by=confirmed_by,
                confirmed_role=confirmed_role,
                confirmed_at=confirmed_at,
                valid_from=valid_from,
                valid_until=valid_until,
                supersedes_id=_clean(data.supersedes_id),
                revoked_at=revoked_at,
                revocation_reason=_clean(data.revocation_reason),
                adopted_fact_ids=adopted_fact_ids,
                authorization_statement=_clean(data.authorization_statement),
                organization_authorization_artifact_id=organization_artifact_id,
                technical_evidence_artifact_id=technical_artifact_id,
                technical_evidence_hash=technical_evidence_hash,
                technical_evidence_request_hash=technical_request_hash,
            )
            repo.put(_RECEIPT_KIND, receipt.model_dump(mode="json"), scope=data.gate_id)
            audit(
                repo,
                "",
                "gate_evidence.receipt_recorded",
                receipt_id=receipt.id,
                gate_id=receipt.gate_id,
                request_hash=receipt.request_hash,
                evidence_manifest_hash=receipt.evidence_manifest_hash,
                conclusion=receipt.conclusion,
                confirmed_by=receipt.confirmed_by,
                confirmed_role=receipt.confirmed_role,
                confirmed_at=receipt.confirmed_at,
                actor=actor,
            )
            if confirmed_by and confirmed_role and confirmed_at:
                self._record_role_action(
                    repo,
                    actor=confirmed_by,
                    role=confirmed_role,
                    action=_ROLE_ACTIONS[confirmed_role],
                    receipt=receipt,
                    acted_at=confirmed_at,
                    recorded_at=recorded_at,
                    recorded_by=actor,
                )
            return receipt

    @staticmethod
    def _record_role_action(
        repo,
        *,
        actor: str,
        role: str,
        action: str,
        receipt: GateEvidenceReceipt,
        acted_at: str,
        recorded_at: datetime,
        recorded_by: str,
    ) -> EvidenceRoleAction:
        """Append one role-specific action trail beside the receipt itself."""
        role_action = EvidenceRoleAction(
            id=uid("role_action"),
            actor=actor,
            role=role,
            action=action,
            gate_id=receipt.gate_id,
            receipt_id=receipt.id,
            template_kind=receipt.template_kind,
            request_hash=receipt.request_hash,
            acted_at=acted_at,
            recorded_at=recorded_at.isoformat(),
            recorded_by=recorded_by,
        )
        repo.put(_ROLE_ACTION_KIND, role_action.model_dump(mode="json"), scope=role)
        audit(
            repo,
            "",
            "gate_evidence.role_action_recorded",
            role_action_id=role_action.id,
            receipt_id=receipt.id,
            gate_id=receipt.gate_id,
            request_hash=receipt.request_hash,
            role=role,
            action=action,
            acted_at=acted_at,
            actor=actor,
        )
        return role_action

    @staticmethod
    def _validate_role_action(
        *,
        gate_id: str,
        template_kind: str | None,
        confirmed_by: str | None,
        confirmed_role: str | None,
        parsed_confirmed_at: datetime | None,
        recorded_at: datetime,
    ) -> None:
        """Check the named role against the template without inferring a signer.

        An incomplete signature is left to pass validation, which refuses it;
        this check never fills in a missing actor, role, or time.
        """
        if confirmed_by is None or confirmed_role is None or parsed_confirmed_at is None:
            return
        if confirmed_role not in _NAMED_ROLES:
            raise EvidenceReceiptError(f"{confirmed_role!r} is not a named confirmation role")
        allowed_roles = _allowed_receipt_roles(gate_id, template_kind)
        if confirmed_role not in allowed_roles:
            raise EvidenceReceiptError(
                f"{gate_id} {template_kind} must be confirmed by {' or '.join(sorted(allowed_roles))}, "
                f"not {confirmed_role}"
            )
        if parsed_confirmed_at > recorded_at:
            raise EvidenceReceiptError("confirmation time cannot be in the future")

    def role_actions(
        self,
        *,
        receipt_id: str | None = None,
        gate_id: str | None = None,
        request_hash: str | None = None,
        actor: str | None = None,
        role: str | None = None,
    ) -> list[EvidenceRoleAction]:
        """Return stored role actions; deactivating a user does not remove them."""
        with self.store.read() as repo:
            records = repo.list(_ROLE_ACTION_KIND)
        actions = [EvidenceRoleAction.model_validate(record) for record in records]
        wanted = {
            "receipt_id": _clean(receipt_id),
            "gate_id": _clean(gate_id),
            "request_hash": _clean(request_hash),
            "actor": _clean(actor),
            "role": _clean(role),
        }
        selected = [
            action
            for action in actions
            if all(
                value is None or getattr(action, field) == value
                for field, value in wanted.items()
            )
        ]
        # Stable sort keeps append order for actions sharing one timestamp.
        return sorted(selected, key=lambda action: (action.acted_at, action.recorded_at))

    @staticmethod
    def role_action_summary(actions: list[EvidenceRoleAction]) -> dict[str, list[str]]:
        """Group role actions by one stable natural-person identity."""
        summary: dict[str, set[str]] = {}
        for action in actions:
            summary.setdefault(action.actor, set()).add(action.role)
        return {actor: sorted(roles) for actor, roles in sorted(summary.items())}

    @staticmethod
    def distinct_actor_count(actions: list[EvidenceRoleAction]) -> int:
        """Count natural persons, not role actions."""
        return len({action.actor for action in actions})

    def get_receipt(self, receipt_id: str) -> GateEvidenceReceipt:
        with self.store.read() as repo:
            record = repo.get(receipt_id, _RECEIPT_KIND)
        return GateEvidenceReceipt.model_validate(record)

    def revoke_evidence(
        self,
        evidence_id: str,
        reason: str,
        *,
        actor: str,
        actor_role: str,
        at: datetime | None = None,
    ) -> GateEvidenceReceipt:
        """Revoke a receipt without deleting its role-specific action history."""
        evidence_id = evidence_id.strip()
        reason = reason.strip()
        actor = actor.strip()
        actor_role = actor_role.strip()
        if not evidence_id:
            raise EvidenceReceiptError("evidence_id must be nonempty")
        if not reason:
            raise EvidenceReceiptError("revocation reason must be nonempty")
        if len(reason) > 1000:
            raise EvidenceReceiptError("revocation reason must not exceed 1000 characters")
        if not actor:
            raise EvidenceReceiptError("revocation actor must be nonempty")
        if actor_role not in _REVOCATION_ROLES:
            raise EvidenceReceiptError("revocation actor role is not recognized")
        revoked_at = _as_utc(at or datetime.now(timezone.utc), "at")

        with self.store.transaction() as repo:
            try:
                current = GateEvidenceReceipt.model_validate(
                    repo.get(evidence_id, _RECEIPT_KIND)
                )
            except KeyError as exc:
                raise EvidenceReceiptError(f"unknown evidence receipt: {evidence_id}") from exc
            if current.revoked_at:
                raise EvidenceReceiptError("evidence receipt is already revoked")

            allowed_roles = _allowed_receipt_roles(current.gate_id, current.template_kind)
            if actor_role != "admin" and actor_role not in allowed_roles:
                raise EvidenceReceiptError(
                    f"{current.gate_id} {current.template_kind} evidence must be revoked by "
                    f"{' or '.join(sorted(allowed_roles))} or admin"
                )
            if current.confirmed_at:
                confirmed_at = _parse_timestamp(current.confirmed_at, "confirmed_at")
                if revoked_at < confirmed_at:
                    raise EvidenceReceiptError("revocation time cannot precede confirmation time")

            revoked = current.model_copy(
                update={
                    "revoked_at": revoked_at.isoformat(),
                    "revocation_reason": reason,
                }
            )
            repo.put(_RECEIPT_KIND, revoked.model_dump(mode="json"), scope=current.gate_id)
            report = _invalidate_receipt_dependents(
                repo, revoked, reason=reason, at=revoked_at.isoformat()
            )
            audit(
                repo,
                "",
                "gate_evidence.receipt_revoked",
                receipt_id=current.id,
                gate_id=current.gate_id,
                request_hash=current.request_hash,
                evidence_manifest_hash=current.evidence_manifest_hash,
                confirmed_by=current.confirmed_by,
                confirmed_role=current.confirmed_role,
                revocation_reason=reason,
                actor_role=actor_role,
                dependent_invalidation=report,
                actor=actor,
            )
            self._record_role_action(
                repo,
                actor=actor,
                role=actor_role,
                action=_REVOCATION_ACTION,
                receipt=revoked,
                acted_at=revoked.revoked_at,
                recorded_at=revoked_at,
                recorded_by=actor,
            )
            return revoked

    def resolve_evidence(
        self,
        release_tuple: dict[str, str],
        *,
        request_hash: str | None = None,
        bound_versions: dict[str, str] | None = None,
        at: datetime | None = None,
    ) -> list[GateEvidenceReceipt]:
        """Return only currently passing receipts with exact current bindings."""
        expected_tuple = _validate_tuple(release_tuple)
        expected_request_hash = _clean(request_hash)
        expected_versions = None if bound_versions is None else _clean_mapping(bound_versions)
        evaluated_at = _as_utc(at or datetime.now(timezone.utc), "at")
        with self.store.read() as repo:
            records = repo.list(_RECEIPT_KIND)

        resolved: list[GateEvidenceReceipt] = []
        for record in records:
            receipt = GateEvidenceReceipt.model_validate(record)
            if receipt.tuple != expected_tuple or not self.receipt_passes(receipt, at=evaluated_at):
                continue
            if receipt.gate_id in _REQUEST_BOUND_GATES:
                if not expected_request_hash or receipt.request_hash != expected_request_hash:
                    continue
            if receipt.gate_id in _VERSION_BOUND_GATES:
                if expected_versions is None or receipt.bound_versions != expected_versions:
                    continue
            try:
                for artifact_id in receipt.evidence_artifact_ids:
                    self.evidence_store.read_artifact(artifact_id)
            except (KeyError, EvidenceIntegrityError):
                continue
            resolved.append(receipt)
        return resolved

    @staticmethod
    def receipt_passes(receipt: GateEvidenceReceipt, *, at: datetime | None = None) -> bool:
        """Evaluate pass state without treating unknown, expiry, or revocation as pass."""
        if receipt.conclusion != "pass" or receipt.revoked_at:
            return False
        if not receipt.evidence_artifact_ids or not receipt.evidence_manifest_hash:
            return False
        if not receipt.confirmed_by or not receipt.confirmed_role or not receipt.confirmed_at:
            return False
        if not receipt.valid_from or not receipt.valid_until:
            return False
        try:
            evaluated_at = _as_utc(at or datetime.now(timezone.utc), "at")
            confirmed_at = _parse_timestamp(receipt.confirmed_at, "confirmed_at")
            valid_from = _parse_timestamp(receipt.valid_from, "valid_from")
            valid_until = _parse_timestamp(receipt.valid_until, "valid_until")
        except EvidenceReceiptError:
            return False
        return confirmed_at <= evaluated_at and valid_from <= evaluated_at < valid_until

    def _load_artifacts(self, repo, artifact_ids: list[str], *, verify: bool) -> list[EvidenceArtifact]:
        artifacts: list[EvidenceArtifact] = []
        for artifact_id in artifact_ids:
            try:
                artifact = EvidenceArtifact.model_validate(repo.get(artifact_id, _ARTIFACT_KIND))
            except KeyError as exc:
                raise EvidenceReceiptError(f"unknown evidence artifact: {artifact_id}") from exc
            if verify:
                target = self.evidence_store._path_for_ref(artifact.storage_ref)
                self.evidence_store._verify_path(target, artifact.content_hash)
            artifacts.append(artifact)
        return artifacts

    @staticmethod
    def _validate_pass(
        *,
        data: GateReceiptInput,
        recorded_at: datetime,
        artifacts: dict[str, EvidenceArtifact],
        artifact_ids: list[str],
        template_kind: str,
        template_artifact_id: str | None,
        confirmed_by: str | None,
        confirmed_role: str | None,
        parsed_confirmed_at: datetime | None,
        parsed_valid_from: datetime | None,
        parsed_valid_until: datetime | None,
        revoked_at: str | None,
        adopted_fact_ids: list[str],
        organization_artifact_id: str | None,
        request_hash: str | None,
        technical_artifact_id: str | None,
        technical_evidence_hash: str | None,
        technical_request_hash: str | None,
    ) -> None:
        if not artifact_ids or not template_artifact_id:
            raise EvidenceReceiptError("pass receipt requires nonempty evidence and a template artifact")
        if template_artifact_id not in artifacts:
            raise EvidenceReceiptError("template artifact must be included in evidence_artifact_ids")
        artifact_template = _template_code(artifacts[template_artifact_id].template_kind)
        if artifact_template != template_kind:
            raise EvidenceReceiptError("template artifact kind does not match receipt template")
        if not confirmed_by or not confirmed_role or parsed_confirmed_at is None:
            raise EvidenceReceiptError("pass receipt requires named signer, role, and confirmation time")
        if parsed_confirmed_at > recorded_at:
            raise EvidenceReceiptError("confirmation time cannot be in the future")
        if parsed_valid_from is None or parsed_valid_until is None:
            raise EvidenceReceiptError("pass receipt requires a validity period")
        if parsed_valid_from > recorded_at or parsed_valid_until <= recorded_at:
            raise EvidenceReceiptError("expired or not-yet-valid evidence cannot pass")
        if parsed_valid_until <= parsed_valid_from:
            raise EvidenceReceiptError("valid_until must be after valid_from")
        if revoked_at:
            raise EvidenceReceiptError("revoked evidence cannot pass")

        if data.gate_id == "G1" and not adopted_fact_ids:
            raise EvidenceReceiptError("G1 pass requires the adopted fact set from 法01")
        if data.gate_id == "G2":
            expected_statement = _g2_authorization_statement(data.tuple)
            if data.authorization_statement != expected_statement:
                raise EvidenceReceiptError("G2 pass requires the exact 本次可用 authorization statement")
            if not organization_artifact_id or organization_artifact_id not in artifacts:
                raise EvidenceReceiptError("G2 pass requires matching organization authorization evidence")

        expected_technical_template = _TECHNICAL_CONFIRMATION_TEMPLATES.get(data.gate_id)
        if expected_technical_template:
            if not technical_artifact_id or technical_artifact_id not in artifacts:
                raise EvidenceReceiptError(f"{data.gate_id} pass requires corresponding technical evidence")
            technical_artifact = artifacts[technical_artifact_id]
            if _template_code(technical_artifact.template_kind) != expected_technical_template:
                raise EvidenceReceiptError(
                    f"{data.gate_id} legal confirmation must reference {expected_technical_template} evidence"
                )
            if technical_evidence_hash != technical_artifact.content_hash:
                raise EvidenceReceiptError("technical evidence hash does not match the referenced artifact")
            if technical_request_hash != request_hash:
                raise EvidenceReceiptError("legal and technical evidence must bind the same request_hash")


def _required_receipt_role(gate_id: str, template_kind: str | None) -> str:
    """Return the single role that may sign one gate's existing template.

    法 templates carry legal confirmation, 技 templates carry engineering
    records, and G10 carries the named approver action. The three trails stay
    separate even when one natural person holds more than one role.
    """
    if gate_id == "G10":
        return _APPROVAL_ROLE
    code = _template_code(template_kind) or ""
    if code.startswith("技"):
        return _ENGINEERING_RECORD_ROLE
    return _LEGAL_REVIEW_ROLE


def _allowed_receipt_roles(gate_id: str, template_kind: str | None) -> frozenset[str]:
    """Keep case-operator records compatible while allowing named technical reviewers."""
    required = _required_receipt_role(gate_id, template_kind)
    if required == _ENGINEERING_RECORD_ROLE:
        return frozenset({_ENGINEERING_RECORD_ROLE, _TECHNICAL_REVIEW_ROLE})
    return frozenset({required})


def _record_state(record) -> str:
    value = record.get("state", record.get("status", ""))
    return value if isinstance(value, str) else ""


def _claimed_request_hashes(repo) -> set[str]:
    """Collect request hashes the gateway may already have claimed."""
    claimed: set[str] = set()
    for record in repo.list(_GATEWAY_RECORD_KIND):
        if record.get("request_hash"):
            claimed.add(str(record["request_hash"]))
    for kind in (_GRANT_KIND, _INTENT_KIND, *_FROZEN_REQUEST_KINDS):
        for record in repo.list(kind):
            if record.get("request_hash") and _record_state(record) in _CLAIMED_STATES:
                claimed.add(str(record["request_hash"]))
    return claimed


def _dependent_request_hashes(repo, receipt: GateEvidenceReceipt) -> set[str]:
    hashes: set[str] = set()
    if receipt.request_hash:
        hashes.add(receipt.request_hash)
    for kind in (*_FROZEN_REQUEST_KINDS, *_SNAPSHOT_KINDS):
        for record in repo.list(kind):
            referenced = record.get("evidence_receipt_ids") or []
            if not isinstance(referenced, (list, tuple)):
                continue
            if receipt.id in {str(item) for item in referenced} and record.get("request_hash"):
                hashes.add(str(record["request_hash"]))
    return hashes


def _invalidate_receipt_dependents(
    repo, receipt: GateEvidenceReceipt, *, reason: str, at: str
) -> dict:
    """Invalidate only unclaimed records that depend on one revoked receipt.

    Claimed, sending, complete, and ``unknown`` history is preserved verbatim;
    gateway records are never rewritten and nothing is deleted.
    """
    dependents = _dependent_request_hashes(repo, receipt)
    claimed_hashes = _claimed_request_hashes(repo)
    affected = dependents - claimed_hashes
    report = {
        "request_ids": [],
        "snapshot_ids": [],
        "intent_ids": [],
        "grant_ids": [],
        "preserved_claimed_request_hashes": sorted(dependents & claimed_hashes),
    }
    if not affected:
        return report

    for kind in _FROZEN_REQUEST_KINDS:
        for request in repo.list(kind):
            if str(request.get("request_hash", "")) not in affected:
                continue
            if request.get("invalidation_status") == "invalidated":
                continue
            updated = dict(request)
            updated.update(
                invalidation_status="invalidated",
                invalidated_at=at,
                invalidation_reason=reason,
                invalidated_evidence_receipt_id=receipt.id,
            )
            repo.put(kind, updated)
            report["request_ids"].append(str(updated.get("request_id") or updated["id"]))

    for kind in _SNAPSHOT_KINDS:
        for snapshot in repo.list(kind):
            if str(snapshot.get("request_hash", "")) not in affected:
                continue
            if snapshot.get("status") == "invalidated":
                continue
            updated = dict(snapshot)
            updated.update(
                status="invalidated",
                approval_eligible=False,
                dispatch_allowed=False,
                invalidated_at=at,
                invalidation_reason=reason,
            )
            repo.put(kind, updated)
            report["snapshot_ids"].append(str(updated["id"]))

    for intent in repo.list(_INTENT_KIND):
        if str(intent.get("request_hash", "")) not in affected:
            continue
        if _record_state(intent) not in _PENDING_INTENT_STATES:
            continue
        updated = dict(intent)
        updated["state" if "state" in updated else "status"] = "cancelled"
        updated.update(cancelled_at=at, cancellation_reason=reason)
        repo.put(_INTENT_KIND, updated)
        report["intent_ids"].append(str(updated["id"]))

    for grant in repo.list(_GRANT_KIND):
        if str(grant.get("request_hash", "")) not in affected:
            continue
        if _record_state(grant) not in _UNCLAIMED_GRANT_STATES:
            continue
        updated = dict(grant)
        updated["state" if "state" in updated else "status"] = "revoked"
        updated.update(revoked_at=at, revocation_reason=reason)
        repo.put(_GRANT_KIND, updated)
        report["grant_ids"].append(str(updated["id"]))

    for key in ("request_ids", "snapshot_ids", "intent_ids", "grant_ids"):
        report[key].sort()
    return report


def _validate_tuple(value: dict[str, str]) -> dict[str, str]:
    if set(value) != _TUPLE_KEYS:
        raise EvidenceReceiptError("release tuple must contain exactly case_id, purpose, and recipient")
    result = {key: str(value[key]).strip() for key in sorted(_TUPLE_KEYS)}
    if any(not item or item == "*" for item in result.values()):
        raise EvidenceReceiptError("release tuple values must be nonempty and non-wildcard")
    return result


def _template_code(value: str | None) -> str | None:
    if not value:
        return None
    match = _TEMPLATE_CODE_RE.search(value.strip())
    if match is None:
        return value.strip()
    return f"{match.group(1)}{int(match.group(2)):02d}"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    return result or None


def _clean_mapping(value: dict[str, str]) -> dict[str, str]:
    result = {str(key).strip(): str(item).strip() for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise EvidenceReceiptError("version bindings cannot contain blank keys or values")
    return dict(sorted(result.items()))


def _clean_unique(values: list[str], field: str) -> list[str]:
    result = [str(value).strip() for value in values]
    if any(not value for value in result):
        raise EvidenceReceiptError(f"{field} cannot contain blank values")
    if len(result) != len(set(result)):
        raise EvidenceReceiptError(f"{field} cannot contain duplicate values")
    return result


def _normalize_hash(value: str | None) -> str | None:
    result = _clean(value)
    if result and result.startswith("sha256:"):
        result = result.removeprefix("sha256:")
    return result


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceReceiptError(f"{field} must be an ISO-8601 timestamp") from exc
    return _as_utc(parsed, field)


def _optional_timestamp(value: str | None, field: str) -> datetime | None:
    return None if value is None else _parse_timestamp(value, field)


def _as_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise EvidenceReceiptError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def _g2_authorization_statement(release_tuple: dict[str, str]) -> str:
    return (
        f"本次 {release_tuple['case_id']}、{release_tuple['purpose']} 子目的、"
        f"{release_tuple['recipient']} 接收方可用。"
    )
