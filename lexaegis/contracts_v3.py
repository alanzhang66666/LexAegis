"""V3 planning contracts. These objects are not signatures or send authority.

This additive module deliberately does not alter the V2 wire format, existing
release gates, provider dispatch, or the task state machine. Hash references
are opaque linkage identifiers, not a claim of anonymisation. A caller must
independently authenticate every proof before making any authorization decision.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .contracts import DomainRuntimeSnapshot, FormalReleasePolicy
from .util import digest


Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128,
                                             pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Chain = Literal["A", "B"]
Route = Literal["LOCAL_DETERMINISTIC", "LOCAL_LLM", "MINIMIZED_TEXT_B", "DP_VECTOR_EXPERIMENT", "BLOCK"]
Grade = Literal["L0", "L1", "L2", "L3", "L4", "UNKNOWN"]


class V3Contract(BaseModel):
    """Closed, immutable, strict input; validation does not establish trust."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")
    contract_version: Literal[3] = 3

    @model_validator(mode="before")
    @classmethod
    def enforce_boolean_and_version_types(cls, value):
        # Python equates 0/1 with False/True, including in Literal fields.
        # Keep external version and safety fields unambiguous.
        if isinstance(value, dict):
            if "contract_version" in value and type(value["contract_version"]) is not int:
                raise ValueError("contract_version must be an integer")
            for field in ("verified", "approval_granted", "authorization", "experiment_only"):
                if field in value and type(value[field]) is not bool:
                    raise ValueError(f"{field} must be a boolean")
            # JSON arrays are the wire representation of immutable tuples.
            value = dict(value)
            for field in ("signal_ids", "hard_prohibitions", "explanation_codes", "missing_codes",
                          "attestation_refs", "transfer_ids", "transfer_hashes", "source_refs"):
                if isinstance(value.get(field), list):
                    value[field] = tuple(value[field])
        return value

    def fingerprint(self) -> str:
        return digest({"domain": f"lexaegis.v3.{type(self).__name__}",
                       "value": self.model_dump(mode="json")})


class ContextSnapshotV3(V3Contract):
    task_id: OpaqueId
    case_ref: Sha256
    domain_pack_hash: Sha256
    domain_pack_kind: Literal["aggregate", "cause_pack"] = "aggregate"
    legal_rule_hash: Sha256
    privacy_policy_hash: Sha256
    classifier_hash: Sha256
    minimization_profile_hash: Sha256
    capability_binding_hash: Sha256
    provider_policy_hash: Sha256
    recipient_ref: Sha256
    material_versions_hash: Sha256
    mapping_version_hash: Sha256
    disclosure_ledger_hash: Sha256
    attack_input_hash: Sha256
    legacy_snapshot_hash: Sha256 | None = None


class PrivacyAssessmentV3(V3Contract):
    assessment_id: OpaqueId
    task_id: OpaqueId
    source_context_hash: Sha256
    sensitivity_class: Literal["S0", "S1", "S2", "UNKNOWN"]
    disclosure_grade: Grade
    classifier_version_hash: Sha256
    ruleset_hash: Sha256
    uncertainty: Literal["none", "review_required", "unknown"]
    signal_ids: tuple[OpaqueId, ...] = ()
    hard_prohibitions: tuple[OpaqueId, ...] = ()
    explanation_codes: tuple[OpaqueId, ...] = ()


class OutboundCapabilityV3(V3Contract):
    """A capability report is descriptive and is never a dispatch permit."""
    state: Literal["unconfigured", "needs_readiness", "available", "suspended"] = "unconfigured"
    missing_codes: tuple[OpaqueId, ...] = ()
    attestation_refs: tuple[Sha256, ...] = ()
    verified: Literal[False] = False

    @model_validator(mode="after")
    def available_needs_references(self):
        if self.state == "available" and (self.missing_codes or len(set(self.attestation_refs)) < 3):
            raise ValueError("available candidate needs distinct deployment, recipient, and policy references")
        return self


class ReleaseScopeV3(V3Contract):
    task_id: OpaqueId
    case_ref: Sha256
    purpose_ref: Sha256
    recipient_ref: Sha256
    chain: Chain
    request_hash: Sha256
    endpoint_hash: Sha256
    model_hash: Sha256
    provider_profile_hash: Sha256
    authorization: Literal[False] = False


class TransferIntentV3(V3Contract):
    transfer_id: OpaqueId
    task_id: OpaqueId
    chain: Chain
    recipient_ref: Sha256
    recipient_policy_hash: Sha256
    purpose_ref: Sha256
    legal_rule_hash: Sha256
    request_hash: Sha256
    approved_wire_bytes_hash: Sha256
    status: Literal["pending"] = "pending"


class ChainDecisionV3(V3Contract):
    """An unverified decision record; its presence does not prove signature validity."""
    decision_id: OpaqueId
    transfer_id: OpaqueId
    chain: Chain
    payload_hash: Sha256
    context_hash: Sha256
    status: Literal["not_applicable", "pending", "approved", "rejected", "expired", "revoked"]
    attestation_ref: Sha256 | None = None
    verified: Literal[False] = False

    @model_validator(mode="after")
    def approved_needs_reference(self):
        if self.status == "approved" and self.attestation_ref is None:
            raise ValueError("approved decision candidate needs an attestation reference")
        return self


class ExecutionPlanV3(V3Contract):
    plan_id: OpaqueId
    task_id: OpaqueId
    route: Route
    assessment_hash: Sha256
    minimization_profile_hash: Sha256
    capability_binding_hash: Sha256
    transfer_ids: tuple[OpaqueId, ...] = ()
    experiment_only: bool = False
    approval_granted: Literal[False] = False

    @model_validator(mode="after")
    def check_candidate_route(self):
        if self.route == "DP_VECTOR_EXPERIMENT" and not self.experiment_only:
            raise ValueError("DP vector routes must remain experiment-only")
        if self.route != "DP_VECTOR_EXPERIMENT" and self.experiment_only:
            raise ValueError("experiment_only is reserved for experimental vector routes")
        if len(set(self.transfer_ids)) != len(self.transfer_ids):
            raise ValueError("transfer identifiers must be unique")
        if self.route != "MINIMIZED_TEXT_B" and self.transfer_ids:
            raise ValueError("this planning contract does not authorize transfers for this route")
        return self


class PrivacyReleaseReceiptV3(V3Contract):
    release_id: OpaqueId
    payload_hash: Sha256
    mechanism_id: OpaqueId | None = None
    budget_reservation_id: OpaqueId | None = None
    experiment_only: Literal[True] = True
    verified: Literal[False] = False


class WireReceiptV3(V3Contract):
    transfer_id: OpaqueId
    chain: Chain
    request_hash: Sha256
    wire_bytes_hash: Sha256
    state: Literal["not_sent", "sending", "complete", "unknown", "failed_before_send"]
    gateway_receipt_ref: Sha256 | None = None
    verified: Literal[False] = False

    @model_validator(mode="after")
    def completed_needs_reference(self):
        if self.state == "complete" and self.gateway_receipt_ref is None:
            raise ValueError("complete receipt candidate needs a gateway reference")
        return self


class FactAssertionV3(V3Contract):
    assertion_id: OpaqueId
    fact_ref: Sha256
    source_refs: tuple[Sha256, ...] = Field(min_length=1)
    content_hash: Sha256
    verified: Literal[False] = False


class FrozenExecutionPlanV3(V3Contract):
    snapshot_hash: Sha256
    assessment_hash: Sha256
    plan: ExecutionPlanV3
    transfer_hashes: tuple[Sha256, ...] = ()


def snapshot_fingerprint(snapshot: ContextSnapshotV3) -> str:
    return ContextSnapshotV3.model_validate(snapshot).fingerprint()


def create_v3_context_snapshot(*, task_id: str, case_ref: str, domain_pack_hash: str,
        legal_rule_hash: str, privacy_policy_hash: str, classifier_hash: str,
        minimization_profile_hash: str, capability_binding_hash: str,
        provider_policy_hash: str, recipient_ref: str,
        material_versions_hash: str, mapping_version_hash: str,
        disclosure_ledger_hash: str, attack_input_hash: str,
        domain_pack_kind: Literal["aggregate", "cause_pack"] = "aggregate") -> ContextSnapshotV3:
    """Accept only caller-computed references; do not ingest case text or mappings."""
    return ContextSnapshotV3(task_id=task_id, case_ref=case_ref,
        domain_pack_hash=domain_pack_hash, domain_pack_kind=domain_pack_kind, legal_rule_hash=legal_rule_hash,
        privacy_policy_hash=privacy_policy_hash, classifier_hash=classifier_hash,
        minimization_profile_hash=minimization_profile_hash, capability_binding_hash=capability_binding_hash,
        provider_policy_hash=provider_policy_hash, recipient_ref=recipient_ref,
        material_versions_hash=material_versions_hash, mapping_version_hash=mapping_version_hash,
        disclosure_ledger_hash=disclosure_ledger_hash, attack_input_hash=attack_input_hash)


def v2_snapshot_to_v3(snapshot: DomainRuntimeSnapshot, *, task_id: str, case_ref: str,
        classifier_hash: str, privacy_policy_hash: str, capability_binding_hash: str, provider_policy_hash: str,
        recipient_ref: str, material_versions_hash: str, mapping_version_hash: str,
        disclosure_ledger_hash: str, attack_input_hash: str) -> ContextSnapshotV3:
    """Build an additive V3 reference without modifying the V2 snapshot or wire.

    V2's cause-pack hash is used when an aggregate pack hash was not recorded.
    The entire original V2 snapshot is also fingerprinted so changes to any
    legacy dependency invalidate this derived reference.
    """
    legacy = DomainRuntimeSnapshot.model_validate(snapshot.model_dump())
    if legacy.capability_binding_hash and legacy.capability_binding_hash != capability_binding_hash:
        raise ValueError("V2 capability binding differs from requested V3 reference")
    return ContextSnapshotV3(task_id=task_id, case_ref=case_ref,
        domain_pack_hash=legacy.pack_content_hash or legacy.cause_pack_hash,
        domain_pack_kind="aggregate" if legacy.pack_content_hash else "cause_pack",
        legal_rule_hash=legacy.legal_rule_pack_hash, privacy_policy_hash=privacy_policy_hash,
        classifier_hash=classifier_hash, provider_policy_hash=provider_policy_hash,
        minimization_profile_hash=legacy.minimization_profile_hash,
        capability_binding_hash=capability_binding_hash,
        recipient_ref=recipient_ref, material_versions_hash=material_versions_hash,
        mapping_version_hash=mapping_version_hash, disclosure_ledger_hash=disclosure_ledger_hash,
        attack_input_hash=attack_input_hash,
        legacy_snapshot_hash=digest({"domain": "lexaegis.v2.DomainRuntimeSnapshot",
                                     "value": legacy.model_dump(mode="json")}))


def freeze_execution_plan(snapshot: ContextSnapshotV3, risk: PrivacyAssessmentV3,
                          plan: ExecutionPlanV3,
                          transfer_intents: tuple[TransferIntentV3, ...]) -> FrozenExecutionPlanV3:
    """Freeze a candidate only; this does not approve, persist, or send anything."""
    snapshot = ContextSnapshotV3.model_validate(snapshot)
    risk = PrivacyAssessmentV3.model_validate(risk)
    plan = ExecutionPlanV3.model_validate(plan)
    intents = tuple(TransferIntentV3.model_validate(item) for item in transfer_intents)
    context_hash = snapshot.fingerprint()
    if (risk.task_id != snapshot.task_id or plan.task_id != snapshot.task_id
            or risk.source_context_hash != context_hash or risk.classifier_version_hash != snapshot.classifier_hash
            or risk.ruleset_hash != snapshot.privacy_policy_hash or plan.assessment_hash != risk.fingerprint()
            or plan.minimization_profile_hash != snapshot.minimization_profile_hash
            or plan.capability_binding_hash != snapshot.capability_binding_hash):
        raise ValueError("snapshot, risk, or plan binding mismatch")
    if tuple(item.transfer_id for item in intents) != plan.transfer_ids:
        raise ValueError("transfer intent list does not match plan")
    if plan.route == "MINIMIZED_TEXT_B":
        if (risk.disclosure_grade in ("L4", "UNKNOWN") or risk.sensitivity_class == "UNKNOWN"
                or risk.uncertainty == "unknown" or risk.hard_prohibitions):
            raise ValueError("risk forbids a cloud candidate")
        if len(intents) != 1 or intents[0].chain != "B":
            raise ValueError("B route needs exactly one B intent")
    for item in intents:
        if (item.task_id != snapshot.task_id or item.recipient_ref != snapshot.recipient_ref
                or item.recipient_policy_hash != snapshot.provider_policy_hash
                or item.legal_rule_hash != snapshot.legal_rule_hash):
            raise ValueError("transfer intent does not match snapshot")
    return FrozenExecutionPlanV3(snapshot_hash=context_hash, assessment_hash=risk.fingerprint(),
                                 plan=plan, transfer_hashes=tuple(item.fingerprint() for item in intents))


def legacy_policy_to_scope(policy: FormalReleasePolicy, *, task_id: str, request_hash: str) -> ReleaseScopeV3:
    """Create a non-authoritative reference to a V2 policy, never a grant.

    Even the first-acceptance policy must be explicitly bound to this request.
    Existing policy validation and gateway enforcement remain unchanged.
    """
    policy = FormalReleasePolicy.model_validate(policy.model_dump())
    requested = request_hash.removeprefix("sha256:")
    if policy.scope_kind == "request" and (policy.bound_request_hash or "").removeprefix("sha256:") != requested:
        raise ValueError("legacy policy is bound to a different request")
    if not policy.allowed_target or not policy.allowed_model:
        raise ValueError("legacy target and model are required")
    return ReleaseScopeV3(task_id=task_id, chain="B", request_hash=requested,
        case_ref=digest({"case": policy.tuple["case_id"]}),
        purpose_ref=digest({"purpose": policy.tuple["purpose"]}),
        recipient_ref=digest({"recipient": policy.tuple["recipient"]}),
        endpoint_hash=digest({"endpoint": policy.allowed_target}),
        model_hash=digest({"model": policy.allowed_model}),
        provider_profile_hash=policy.allowed_provider_profile_hash.removeprefix("sha256:"))
