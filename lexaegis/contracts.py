"""Versioned contracts. Domain packs contain data, never executable expressions."""
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


REVIEW_BLOCK_KINDS = ("ocr", "scan", "transcript")


class SourceAnchor(Contract):
    id: str
    document_id: str
    document_version: int
    kind: Literal["paragraph", "table", "pdf_text", "ocr", "scan", "transcript"]
    text: str
    page: int | None = None
    bbox: list[float] | None = None
    locator: str = ""
    confidence: float | None = None
    recognizer: str | None = None
    reviewed: bool = False


class DocumentIR(Contract):
    schema_version: int = 1
    document_id: str
    version: int
    blocks: list[SourceAnchor]
    needs_review: bool = False
    warnings: list[str] = Field(default_factory=list)


class DocumentIRV2(Contract):
    schema_version: Literal[2] = 2
    document_id: str
    version: int = Field(ge=1)
    blocks: list[SourceAnchor]
    material_hash: str
    review_status: Literal["pending", "reviewed", "needs_correction"] = "pending"
    needs_review: bool = True
    warnings: list[str] = Field(default_factory=list)


class FieldRule(Contract):
    field: str
    necessity: Literal["required", "conditional", "unnecessary", "uncertain"]
    transform: Literal["keep", "pseudonymize", "generalize", "delete"]
    reason: str
    forbidden: bool = False


class LegalSourceRef(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    title: str
    articles: list[str] = Field(default_factory=list)
    version_note: str = ""
    effective_from: str | None = None
    snapshot: str = ""
    historical_mapping: dict[str, str] = Field(default_factory=dict)
    citation_status: Literal["draft_reference", "published"] = "draft_reference"
    tier: Literal[
        "法律", "行政法规", "部门规章", "司法解释", "地方性法规", "地方政府规章",
        "国家标准", "项目自定规则", "参考案例",
    ] = "法律"
    provision_text: str = ""
    norm_summary: str = ""
    applies_to: str = ""
    trigger: str = ""
    consequence: str = ""
    review_required: bool = False
    review_trigger: str = ""
    rule_nature: Literal["statutory", "standard_reference", "provider_terms", "project_control"] = "statutory"
    granularity: Literal["article", "instrument_scope"] = "article"
    merged_from: Literal["v0_1_base", "v0_2_added", "v0_1_v0_2_merged", "pack_seed"] = "pack_seed"


class ManualReviewCondition(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    trigger: str
    why_machine_cannot: str = ""
    what_to_verify: list[str] = Field(default_factory=list)
    legal_source_ids: list[str] = Field(default_factory=list)
    gate_id: Literal["G0", "G2", "G3", "G5", "G7", "G8", "G9"] = "G0"
    blocking: bool = True


class SensitiveObjectRule(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    object_type: str
    object_group: Literal["personal_information", "other_sensitive_object"]
    carriers: list[str] = Field(default_factory=list)
    is_sensitive_pi: bool = False
    default_handling: str = ""
    provision_text: str = ""
    norm_summary: str = ""
    detector_categories: list[str] = Field(default_factory=list)
    review_condition_ids: list[str] = Field(default_factory=list)
    legal_source_ids: list[str] = Field(default_factory=list)
    unresolved_citations: list[str] = Field(default_factory=list)
    rule_nature: Literal["statutory", "standard_reference", "project_control"] = "project_control"


class NotHardBanCategory(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    category: str
    why_not_automatic_ban: str = ""
    what_to_judge: list[str] = Field(default_factory=list)


class ReplyTemplate(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    disposition: Literal["allowed", "needs_minimization", "needs_verification", "prohibited"]
    title: str
    body: str


class ConflictChecklistStep(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    step: int = Field(ge=1, le=6)
    prompt: str


class ProhibitionFinding(Contract):
    category: Literal[
        "state_secret", "court_confidentiality_order", "trade_secret_restriction",
        "communicable_disease", "other_special_law",
    ]
    protected_object_confirmed: bool = False
    rule_prohibits_current_act: bool = False
    applies_to_current_context: bool = False
    minimization_insufficient: bool = False
    legal_source_ids: list[str] = Field(default_factory=list)
    basis_note: str = ""
    confirmed_by: str | None = None
    confirmed_at: str | None = None


class ManualApprovalRecord(Contract):
    id: str
    case_id: str
    task_id: str
    request_hash: str
    material_version: int = Field(ge=0)
    conclusion: Literal[
        "allow_processing", "allow_after_minimization",
        "needs_further_verification", "prohibit_external_processing", "reject_current_request",
    ]
    reason: str = Field(min_length=1)
    reviewed_condition_ids: list[str] = Field(default_factory=list)
    legal_source_ids: list[str] = Field(default_factory=list)
    prohibition_findings: list[ProhibitionFinding] = Field(default_factory=list)
    minimization_actions: list[str] = Field(default_factory=list)
    acknowledged_risk_notices: bool = False
    reviewer: str
    reviewed_at: str
    scope_note: str = ""
    fact_premise: str = ""
    authority_judgment: str = ""
    external_processing_note: str = ""
    minimization_note: str = ""
    final_basis: str = ""
    reviewer_id: str = ""
    reviewer_role: str = "legal_reviewer"
    idempotency_key: str = ""
    resolved_issue_ids: list[str] = Field(default_factory=list)
    resolution_reason: str = ""


class ImmutableRelation(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    kind: Literal["subject_ownership", "date_relation", "numeric_relation", "negation", "dispute_status", "source"]
    description: str = ""


class DisclosureCondition(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    attribute: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    operator: Literal["eq", "in", "known"]
    values: list[str] = Field(default_factory=list)


class ConditionalDisclosureRule(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    task_id: str
    sub_purpose: str
    conditions: list[DisclosureCondition] = Field(default_factory=list)
    affected_fields: list[str] = Field(default_factory=list)
    necessity: Literal["required", "conditional", "unnecessary", "uncertain"] = "uncertain"
    min_precision: str = ""
    allowed_transforms: list[Literal["original_precision", "tokenize", "moderate_generalize", "delete"]] = Field(
        default_factory=lambda: ["original_precision", "tokenize", "moderate_generalize", "delete"]
    )
    forbidden_default_transforms: list[str] = Field(default_factory=list)
    immutable_relations: list[str] = Field(default_factory=list)
    legal_source_ids: list[str] = Field(default_factory=list)
    missing_item_strategy: Literal["review", "delete", "keep", "restrict"] = "restrict"
    unknown_condition_strategy: Literal["review", "restrict"] = "restrict"
    preferred_transform: Literal["original_precision", "tokenize", "moderate_generalize", "delete"] = "original_precision"
    reason: str = ""


class ProcessingBasis(Contract):
    subject_category: Literal["natural_person", "legal_person", "unknown"] = "unknown"
    collection_source: str = ""
    local_purpose: str = ""
    cloud_purpose: str = ""
    proposed_basis: str = ""
    necessity_note: str = ""
    consent_or_other_evidence: str = ""
    notice_status: Literal["unknown", "not_notified", "notified", "not_applicable"] = "unknown"
    review_conclusion: Literal["pending", "review", "insufficient"] = "pending"
    necessity_judgment: Literal["unknown", "necessary", "not_necessary", "review"] = "unknown"
    processability_judgment: Literal["unknown", "processable", "not_processable", "review"] = "unknown"
    residual_risk_judgment: Literal["unknown", "elevated", "unverified", "review"] = "unknown"


class ConfidentialityRecord(Contract):
    case_level: Literal["unknown", "ordinary", "elevated", "restricted"] = "unknown"
    information_category: Literal[
        "unknown", "personal_information", "party_privacy", "trade_secret", "state_secret", "other_confidential"
    ] = "unknown"
    team_policy_block: bool = False
    statutory_duty_note: str = ""
    lawyer_law_article: str | None = None
    lawyer_law_snapshot: str = ""
    lawyer_law_mapping_note: str = ""
    lawyer_law_text_date: str | None = None


class DomainPack(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    name: str
    version: str
    status: Literal["draft", "demo", "published"]
    task_ids: list[str]
    fact_fields: list[str]
    rules: list[FieldRule]
    forbidden_terms: list[str] = Field(default_factory=list)
    references: list[str]
    review_record: str | None = None
    required_attacks: list[Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]]
    legal_sources: list[LegalSourceRef] = Field(default_factory=list)
    manual_review_conditions: list[ManualReviewCondition] = Field(default_factory=list)
    risk_protocols: list["RiskProtocolRef"] = Field(default_factory=list)


class FactFieldDefinition(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    label: str
    value_type: Literal["text", "entity", "date", "money", "number", "enum", "boolean"] = "text"
    description: str = ""


class RiskProtocolRef(Contract):
    id: str
    version: str


class TaskFieldRequirement(Contract):
    task_id: str
    field: str
    necessity: Literal["required", "conditional", "unnecessary", "uncertain"] = "uncertain"
    rationale: str = ""


class DomainPackV2(Contract):
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    name: str
    version: str
    status: Literal["draft", "pending_review", "reviewed", "published", "retired"] = "draft"
    compatible_core: str = ">=0.2,<2"
    task_ids: list[str]
    fact_fields: list[FactFieldDefinition]
    task_field_matrix: list[TaskFieldRequirement] = Field(default_factory=list)
    rules: list[FieldRule]
    direct_identifier_patterns: list[dict[str, Any]] = Field(default_factory=list)
    risk_weights: dict[str, float] = Field(default_factory=dict)
    forbidden_terms: list[str] = Field(default_factory=list)
    manual_review_conditions: list[ManualReviewCondition] = Field(default_factory=list)
    sensitive_object_rules: list[SensitiveObjectRule] = Field(default_factory=list)
    not_hard_ban_categories: list[NotHardBanCategory] = Field(default_factory=list)
    reply_templates: list[ReplyTemplate] = Field(default_factory=list)
    conflict_checklist: list[ConflictChecklistStep] = Field(default_factory=list)
    references: list[str]
    effective_from: str | None = None
    effective_until: str | None = None
    review_record: str | None = None
    legal_status: Literal["pending_legal_review", "reviewed"] = "pending_legal_review"
    dispatch_allowed: bool = False
    reviewer: str | None = None
    reviewed_at: str | None = None
    content_hash: str | None = None
    frozen_at: str | None = None
    published_scope: dict[str, Any] = Field(default_factory=dict)
    published_by: str | None = None
    risk_protocols: list[RiskProtocolRef] = Field(default_factory=list)
    synthetic_cases: list[dict[str, Any]] = Field(default_factory=list)
    legal_sources: list[LegalSourceRef] = Field(default_factory=list)
    immutable_relations: list[ImmutableRelation] = Field(default_factory=list)
    disclosure_rules: list[ConditionalDisclosureRule] = Field(default_factory=list)
    # Declarative return-pipeline mapper config (see lexaegis/domain_mapper.py).
    # Data only — packages never carry executable code.
    mapper: dict[str, Any] = Field(default_factory=dict)


class TaskDefinition(Contract):
    id: str
    name: str
    version: str = "1.0.0"
    available: bool = False
    output_type: str


class TaskDefinitionV2(Contract):
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    name: str
    version: str
    status: Literal["available", "unimplemented", "retired"] = "unimplemented"
    execution_type: Literal["local_deterministic", "approved_cloud"]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    prompt_template: str | None = None
    validator: str
    transports: list[Literal["local", "mock", "cloud"]]
    max_payload_chars: int = Field(default=50000, ge=1, le=200000)
    ui_renderer: Literal["claims", "timeline", "evidence", "issues"]


class RiskAssessment(Contract):
    completion: Literal["complete", "incomplete", "error"]
    findings: list[str]
    blockers: list[str]
    gates: list[dict[str, Any]] = Field(default_factory=list)
    attacks: list[dict]
    ledger_version: int
    approval_allowed: bool = False
    disposition: Literal["allowed", "needs_minimization", "needs_verification", "prohibited"] = "allowed"
    system_readiness: Literal["ready", "not_ready"] = "ready"
    demo_exception: bool = False


class DetectionFinding(Contract):
    id: str
    category: str
    value: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    risk: Literal["low", "medium", "high", "critical"]
    source_anchor_id: str | None = None
    source_anchor_ids: list[str] = Field(default_factory=list)
    source_spans: list[dict[str, Any]] = Field(default_factory=list)
    coordinate_space: Literal["disclosure", "source"] = "disclosure"
    locator_status: Literal["located", "warning"] = "located"
    explanation: str = ""


class SensitivitySignal(Contract):
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    source_anchor_ids: list[str] = Field(default_factory=list)
    explanation: str


class RiskSignal(Contract):
    kind: Literal["entity", "density", "context", "combination", "cross_round"]
    score: float = Field(ge=0, le=1)
    weight: float = Field(ge=0)
    source_anchor_ids: list[str] = Field(default_factory=list)
    explanation: str


class MappingEntry(Contract):
    entity_id: str
    wire_token: str = Field(pattern=r"^\[\[LEX:[POLC]\d{4,}\]\]$")
    display_alias: str
    original_value: str
    source_ids: list[str] = Field(default_factory=list)
    mapping_version: int = Field(ge=1)
    aliases: list[str] = Field(default_factory=list)


class ClaimArtifactV2(Contract):
    id: str
    text: str
    local_text: str
    source_ids: list[str]
    anchors: list[dict[str, Any]]
    support: list[str]
    issues: list[str]
    status: Literal["source_matched", "needs_review", "confirmed"]
    reviewer: str | None = None
    reviewed_at: str | None = None


class CloudGap(Contract):
    code: Literal["missing_field", "insufficient_support", "ambiguous_reference", "other"]
    detail: str = Field(max_length=500)
    fact_ids: list[str] = Field(default_factory=list, max_length=20)


class CollaborationFollowup(Contract):
    id: str
    source_task_id: str
    kind: Literal["unused_fact", "gap", "feedback_issue"]
    status: Literal["open", "dismissed", "addressed"]
    detail: str = ""
    fact_id: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    field: str | None = None
    code: str | None = None
    next_task_id: str | None = None


class RiskProtocol(Contract):
    id: str
    kind: Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]
    version: str
    status: Literal["draft", "frozen", "retired"] = "draft"
    attacker_view: list[str]
    auxiliary_data: list[str]
    query_budget: int = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)
    success_criteria: dict[str, Any]
    threshold: float = Field(ge=0, le=1)
    random_seed: int
    content_hash: str | None = None


class AttackRun(Contract):
    id: str
    protocol_id: str
    protocol_hash: str
    task_id: str
    task_version: int = Field(ge=1)
    attack_input_hash: str
    outcome: Literal["resisted", "succeeded", "uncertain", "error", "not_run"]
    score: float | None = None
    evidence: list[str] = Field(default_factory=list)
    query_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    result_hash: str | None = None
    started_at: str
    finished_at: str | None = None


class ProviderProfile(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,60}$")
    name: str
    legal_entity: str | None = None
    product: str | None = None
    role: Literal["processor", "independent_controller", "other", "unknown"] = "unknown"
    endpoint: str | None = None
    model: str | None = None
    processing_regions: list[str] = Field(default_factory=list)
    retention: str | None = None
    training_use: Literal["forbidden", "allowed", "unknown"] = "unknown"
    human_access: Literal["forbidden", "controlled", "allowed", "unknown"] = "unknown"
    subprocessors: list[str] = Field(default_factory=list)
    subprocessor_status: Literal["none", "declared", "unknown"] = "unknown"
    deletion_mechanism: str | None = None
    contract_reference: str | None = None
    contract_version: str | None = None
    impact_assessment_reference: str | None = None
    impact_assessment_version: str | None = None
    valid_until: str | None = None
    allowed_tasks: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_fields: list[str] = Field(default_factory=list)
    allowed_transports: list[Literal["cloud"]] = Field(default_factory=list)
    status: Literal["draft", "reviewed", "expired"] = "draft"
    profile_version: int = Field(default=1, ge=1)
    reviewed_by: str | None = None
    reviewed_at: str | None = None


class DispatchAttempt(Contract):
    id: str
    slot: Literal["primary", "standby"]
    target: str
    model: str = ""
    request_digest: str
    started_at: str
    finished_at: str | None = None
    generation_state: Literal["not_started", "started", "complete"] = "not_started"
    transmission_state: Literal["not_left_local", "sent_unconfirmed", "response_received"] = "not_left_local"
    disclosure_state: Literal["undisclosed", "possible", "disclosed"] = "undisclosed"
    error_type: str | None = None
    output_state: Literal["none", "partial", "complete"] = "none"


class ApprovalV2(Contract):
    id: str
    actor: str
    actor_role: Literal["approver"]
    request_hash: str
    dependencies: dict[str, Any]
    at: str
    expires_at: str


class ComplianceCheck(Contract):
    id: str
    name: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    basis: list[str] = Field(default_factory=list)
    detail: str


class PrivacyTransformRun(Contract):
    id: str
    algorithm: Literal["gaussian_dp", "saliency_mask", "jl", "pca", "random_projection"]
    input_hash: str
    input_model_hash: str | None = None
    parameters: dict[str, Any]
    output_hash: str
    matrix_hash: str | None = None
    provenance: Literal["numeric_input", "heuristic", "experimental_model"]
    budget: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, str]
    created_at: str


class ApprovedRequest(Contract):
    request_id: str
    case_id: str
    task_id: str
    mode: Literal["formal", "demo"]
    transport: Literal["local", "mock", "cloud"]
    target: str
    wire_payload: dict | None = None
    body: dict
    dependencies: dict
    policy: dict


class TaskArtifact(Contract):
    claims: list[dict]
    provenance: Literal["simulation", "cloud", "local_deterministic"]
    confirmed: bool = False


# Formal outbound release contracts. These types intentionally default to
# fail-closed states; a caller must supply reviewed evidence before any pass.
GateID = Literal["G0", "G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G-product"]
GateStatus = Literal["unknown", "pending", "pass", "fail", "expired", "stale", "revoked", "not_applicable"]
ReleaseTuple = dict[str, str]


class FormalReleaseState(str, Enum):
    BLOCKED = "blocked"
    EVIDENCE_PENDING = "evidence_pending"
    FROZEN = "frozen"
    APPROVAL_ELIGIBLE = "approval_eligible"
    APPROVED_ONCE = "approved_once"
    RESERVED = "reserved"
    CLAIMED = "claimed"
    CONSUMED_COMPLETE = "consumed_complete"
    CONSUMED_UNKNOWN = "consumed_unknown"
    FAILED_BEFORE_DISCLOSURE = "failed_before_disclosure"
    REVOKED = "revoked"
    EXPIRED = "expired"


class LegalSourceAssetPointer(Contract):
    asset_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    source_path: str = ""


class LegalSourceRecord(Contract):
    id: str = Field(min_length=1)
    canonical_title: str = Field(min_length=1)
    articles: list[str] = Field(default_factory=list)
    provision_hash: str = Field(min_length=1)
    provision_text_ref: str = Field(min_length=1)
    effective_from: str | None = None
    effective_to: str | None = None
    citation_status: Literal[
        "unknown", "draft_reference", "verified_text", "historical", "superseded"
    ] = "unknown"
    rule_nature: Literal[
        "unknown", "statutory", "standard_reference", "provider_terms", "project_control"
    ] = "unknown"
    granularity: Literal["unknown", "article", "instrument_scope"] = "unknown"
    source_assets: list[LegalSourceAssetPointer] = Field(min_length=1)
    duplicate_group_id: str | None = None


class CitationMapping(Contract):
    id: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    from_article: str = Field(min_length=1)
    to_article: str = Field(min_length=1)
    effective_from: str = Field(min_length=1)
    mapping_basis: Literal[
        "unknown", "official_text", "amendment_sequence", "human_verified"
    ] = "unknown"
    basis_artifact_hash: str = Field(min_length=1)
    status: Literal["pending", "verified", "rejected"] = "pending"
    note: str = ""

    @field_validator("status")
    @classmethod
    def amendment_sequence_cannot_verify_full_text(cls, value, info):
        if info.data.get("mapping_basis") == "amendment_sequence" and value == "verified":
            raise ValueError("仅凭条文顺序推算不得标记为已核验全文")
        return value


class EvidenceArtifact(Contract):
    id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    source_path_hint: str = ""
    template_kind: str | None = None
    created_at: str = Field(min_length=1)
    registered_by: str = Field(min_length=1)
    storage_ref: str = Field(min_length=1)


class GateReceiptInput(Contract):
    """Structured fields transcribed from an existing legal-computing template."""

    gate_id: GateID
    tuple: ReleaseTuple
    template_kind: str = Field(min_length=1)
    template_version: str | None = None
    template_artifact_id: str | None = None
    bound_versions: dict[str, str] = Field(default_factory=dict)
    request_hash: str | None = None
    conclusion: Literal["unknown", "pending", "pass", "fail"] = "unknown"
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    confirmed_by: str | None = None
    confirmed_role: str | None = None
    confirmed_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes_id: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None
    adopted_fact_ids: list[str] = Field(default_factory=list)
    authorization_statement: str | None = None
    organization_authorization_artifact_id: str | None = None
    technical_evidence_artifact_id: str | None = None
    technical_evidence_hash: str | None = None
    technical_evidence_request_hash: str | None = None


class GateEvidenceReceipt(Contract):
    id: str = Field(min_length=1)
    gate_id: GateID
    tuple: ReleaseTuple
    template_kind: str | None = None
    template_version: str | None = None
    template_artifact_id: str | None = None
    bound_versions: dict[str, str] = Field(default_factory=dict)
    request_hash: str | None = None
    conclusion: Literal["unknown", "pending", "pass", "fail"] = "unknown"
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    evidence_manifest_hash: str = ""
    confirmed_by: str | None = None
    confirmed_role: str | None = None
    confirmed_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes_id: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None
    adopted_fact_ids: list[str] = Field(default_factory=list)
    authorization_statement: str | None = None
    organization_authorization_artifact_id: str | None = None
    technical_evidence_artifact_id: str | None = None
    technical_evidence_hash: str | None = None
    technical_evidence_request_hash: str | None = None


RoleActionRole = Literal["legal_reviewer", "case_operator", "technical_reviewer", "approver", "admin"]
RoleActionKind = Literal[
    "legal_confirmation", "engineering_record", "g10_approval", "evidence_revocation"
]


class EvidenceRoleAction(Contract):
    """One role-specific action performed by one stable local identity.

    Legal confirmation, engineering records, and approver actions are stored as
    separate records with their own role, actor, and time. One natural person
    acting under two roles produces two role actions bound to the same
    ``actor``, never two independent reviewers.
    """

    id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    role: RoleActionRole
    action: RoleActionKind
    gate_id: GateID
    receipt_id: str = Field(min_length=1)
    template_kind: str | None = None
    request_hash: str | None = None
    acted_at: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    recorded_by: str = Field(min_length=1)


class ReleaseBuildManifest(Contract):
    id: str = Field(min_length=1)
    source_commit: str = ""
    worktree_clean: bool = False
    source_tree_hash: str = ""
    documentation_hash: str = ""
    frontend_dist_hash: str = ""
    wheel_hash: str = ""
    lockfile_hashes: dict[str, str] = Field(default_factory=dict)
    runtime_pack_hash: str = ""
    container_image_digests: dict[str, str] = Field(default_factory=dict)
    migration_revision: str = ""
    validation_results_hash: str = ""
    status: Literal["pending", "verified", "revoked"] = "pending"
    created_at: str = Field(min_length=1)
    verified_by: str | None = None


class FormalReleasePolicy(Contract):
    id: str = Field(min_length=1)
    scope_kind: Literal["first_acceptance", "request"] = "first_acceptance"
    bound_request_hash: str | None = None
    tuple: ReleaseTuple
    build_manifest_hash: str = ""
    allowed_target: str = ""
    allowed_model: str = ""
    allowed_provider_profile_hash: str = ""
    maximum_dispatches: int = Field(default=1, ge=1)
    consumed_dispatches: int = Field(default=0, ge=0)
    valid_from: str | None = None
    valid_until: str | None = None
    status: Literal["blocked", "armed_once", "consumed", "revoked", "expired"] = "blocked"
    installed_by: str | None = None
    installed_at: str | None = None

    @model_validator(mode="after")
    def validate_release_scope(self):
        expected = {
            "case_id": "LA-001",
            "purpose": "R_fact_summary",
            "recipient": "D_DeepSeek_official_API",
        }
        if self.scope_kind == "first_acceptance":
            if self.tuple != expected or self.bound_request_hash is not None:
                raise ValueError("first-acceptance policy requires the exact LA-001 × R × D scope")
        else:
            value = self.bound_request_hash or ""
            candidate = value.removeprefix("sha256:")
            if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
                raise ValueError("request policy requires a canonical bound_request_hash")
            if self.maximum_dispatches != 1:
                raise ValueError("request policy permits exactly one dispatch")
            if set(self.tuple) != {"case_id", "purpose", "recipient"} or not all(
                    isinstance(item, str) and item.strip() for item in self.tuple.values()):
                raise ValueError("request policy requires an exact case, purpose, and recipient tuple")
        return self


class FrozenFormalRequest(Contract):
    request_id: str = Field(min_length=1)
    tuple: ReleaseTuple
    wire_payload: dict[str, Any]
    prompt: str
    target: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_profile_hash: str = Field(min_length=1)
    runtime_pack_hash: str = Field(min_length=1)
    material_versions: dict[str, int]
    rule_versions: dict[str, str]
    task_version: int = Field(ge=1)
    mapping_version: int = Field(ge=1)
    ledger_version: int = Field(ge=0)
    combination_input_hash: str = Field(min_length=1)
    attack_protocol_hashes: dict[str, str]
    build_manifest_hash: str = Field(min_length=1)
    request_hash: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class GateHit(Contract):
    gate_id: GateID
    status: GateStatus = "unknown"
    kind: Literal["unknown", "prohibition", "verification", "minimization", "engineering"] = "unknown"
    reason_code: str = ""
    message: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class GateDecision(Contract):
    phase: Literal["unknown", "evaluate", "approve", "enqueue", "send", "gateway"] = "unknown"
    request_hash: str = ""
    hits: list[GateHit] = Field(default_factory=list)
    snapshot_hash: str = ""
    disposition: Literal[
        "unknown", "allowed", "needs_minimization", "needs_verification", "prohibited"
    ] = "unknown"
    system_readiness: Literal["blocked", "ready", "not_ready"] = "blocked"
    approval_eligible: bool = False
    dispatch_allowed: bool = False
    evaluated_at: str | None = None


class IsolationReceipt(Contract):
    id: str = Field(min_length=1)
    request_hash: str = ""
    tuple: ReleaseTuple
    build_manifest_hash: str = ""
    deployment_mode: Literal["unknown", "isolated"] = "unknown"
    deployment_identity_hash: str = ""
    compose_hash: str = ""
    image_digests: dict[str, str] = Field(default_factory=dict)
    api_no_egress: bool = False
    worker_no_egress: bool = False
    gateway_no_case_volume: bool = False
    redteam_no_secrets: bool = False
    benchmark_no_secrets: bool = False
    probe_output_hash: str = ""
    host_firewall_evidence_hash: str = ""
    supply_chain_evidence_hash: str = ""
    generated_at: str | None = None
    expires_at: str | None = None
    attested_by: str | None = None
    legal_confirmation_receipt_id: str | None = None
    status: Literal[
        "pending_legal_confirmation", "valid", "failed", "revoked", "expired"
    ] = "pending_legal_confirmation"


class OneTimeDispatchGrant(Contract):
    id: str = Field(min_length=1)
    nonce: str = Field(min_length=1)
    request_hash: str = Field(min_length=1)
    gate_snapshot_hash: str = Field(min_length=1)
    evidence_manifest_hash: str = Field(min_length=1)
    build_manifest_hash: str = Field(min_length=1)
    release_policy_id: str = Field(min_length=1)
    tuple: ReleaseTuple
    actor: str = ""
    actor_role: Literal["unknown", "approver"] = "unknown"
    issued_at: str | None = None
    expires_at: str | None = None
    state: Literal[
        "pending", "issued", "reserved", "claimed", "consumed", "revoked", "expired"
    ] = "pending"
    claimed_at: str | None = None
    gateway_attempt_id: str | None = None


# --- V2.2 runtime binding objects (P1) ---
# These records are written alongside the legacy aggregates; the legacy path
# stays authoritative until the orchestration cut-over in a later phase.

PLATFORM_API_VERSION = "v2"


class CaseDomainBinding(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    cause_id: str = Field(min_length=1)
    cause_pack_id: str | None = None
    cause_pack_version: str | None = None
    legal_rule_pack_id: str | None = None
    legal_rule_pack_version: str | None = None
    jurisdiction: str | None = None
    domain_package_manifest_id: str | None = None
    binding_status: Literal["active", "superseded"] = "active"
    bound_at: str
    bound_by: str = Field(min_length=1)


class DomainRuntimeSnapshot(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    cause_pack_hash: str = Field(min_length=1)
    legal_rule_pack_hash: str = Field(min_length=1)
    capability_binding_hash: str | None = None
    review_schema_hash: str = Field(min_length=1)
    artifact_schema_hash: str = Field(min_length=1)
    minimization_profile_hash: str = Field(min_length=1)
    gate_profile_hash: str = Field(min_length=1)
    platform_api_version: str = Field(min_length=1)
    # provenance of the interim section-hash derivation over a monolithic pack
    pack_id: str | None = None
    pack_version: str | None = None
    pack_content_hash: str | None = None
    # provenance when resolved through a DomainPackageManifest (P2)
    domain_package_manifest_id: str | None = None
    capability_binding_id: str | None = None
    runtime_environment: str = ""
    created_at: str


PACKAGE_TYPES = (
    "cause_pack", "legal_rule_pack", "capability_binding", "review_schema",
    "artifact_schema", "minimization_profile", "gate_profile",
    "domain_acceptance_suite",
)

PACKAGE_LIFECYCLE = (
    "draft", "validated", "signed", "published", "deprecated", "revoked",
)

_PACKAGE_TYPE = Literal[
    "cause_pack", "legal_rule_pack", "capability_binding", "review_schema",
    "artifact_schema", "minimization_profile", "gate_profile",
    "domain_acceptance_suite",
]

_PACKAGE_STATUS = Literal[
    "draft", "validated", "signed", "published", "deprecated", "revoked",
]


class DomainPackage(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    package_type: _PACKAGE_TYPE
    package_id: str = Field(min_length=1)
    cause_id: str | None = None
    version: str = Field(min_length=1)
    status: _PACKAGE_STATUS = "draft"
    platform_api: str | None = None
    compatibility: dict[str, str] = Field(default_factory=dict)
    jurisdiction: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    publisher: str | None = None
    supersedes: str | None = None
    signature: str | None = None
    signed_by: str | None = None
    signed_at: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(min_length=1)
    created_at: str
    deprecated_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None


class DomainPackageManifest(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    cause_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: _PACKAGE_STATUS = "draft"
    package_refs: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    platform_api_version: str | None = None
    publisher: str | None = None
    signature: str | None = None
    signed_by: str | None = None
    signed_at: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(min_length=1)
    created_at: str
    deprecated_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None


class CaseContextVersion(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    context_version_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    domain_runtime_snapshot_id: str = Field(min_length=1)
    verified_fact_set_hash: str = Field(min_length=1)
    source_material_set_hash: str = Field(min_length=1)
    identity_mapping_version: int = Field(ge=1)
    cumulative_disclosure_state: int = Field(ge=0)
    case_revision: int = Field(ge=1)
    status: Literal["current", "superseded"] = "current"
    superseded_by: str | None = None
    created_at: str


TASK_STEP_TYPES = (
    "LOCAL", "CONTROL", "CLOUD", "VALIDATION", "HUMAN", "STATE_TRANSITION",
)


class TaskStep(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    step_type: Literal[
        "LOCAL", "CONTROL", "CLOUD", "VALIDATION", "HUMAN", "STATE_TRANSITION"
    ]
    from_status: str | None = None
    to_status: str = Field(min_length=1)
    actor: str | None = None
    at: str


SUPPORT_STATUSES = (
    "supported", "validation", "integration_only", "unsupported", "suspended",
)


class SupportedCause(Contract):
    """V2.2 §8 Support Registry record: which causes the product supports.

    Separate from the Package Registry — a loadable/validated package does
    not make its cause supported. Support only gates entry into the product
    loop (case/task creation); formal dispatch stays gated elsewhere.
    """
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    cause_id: str = Field(min_length=1)
    status: Literal[
        "supported", "validation", "integration_only", "unsupported", "suspended",
    ] = "validation"
    environments: list[str] = Field(default_factory=list)
    pack_ids: list[str] = Field(default_factory=list)
    manifest_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    notes: str | None = None
    version: int = Field(ge=1, default=1)
    created_at: str
    updated_at: str | None = None
    updated_by: str | None = None


FAILURE_CODES = (
    "package_resolution_failed", "platform_api_mismatch",
    "invalid_cloud_result", "failed_before_send", "unknown",
)


class CloudTaskEnvelope(Contract):
    """V2.2 CloudContext Envelope: the minimized, approved context a task is
    allowed to send cloud-side. case_ref is an opaque reference — the raw
    case id never crosses the envelope boundary."""
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    case_ref: str = Field(min_length=1)
    cause_id: str = Field(min_length=1)
    capability_id: str | None = None
    capability_binding_id: str | None = None
    context_version_id: str = Field(min_length=1)
    domain_runtime_snapshot_id: str = Field(min_length=1)
    request_hash: str = Field(min_length=1)
    contract_version: int = Field(ge=1)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class CloudResultEnvelope(Contract):
    """V2.2 Cloud Result Envelope: the edge-side receipt binding a returned
    result to the approved request. Cloud results are candidate outputs —
    pipeline_status stays 'pending_human' until a human adopts the artifact
    (see HumanDecision); a failed return validation records 'rejected'.
    Written for any transport so the receipt trail is complete; provenance
    records what the result actually is — a simulation can never read
    'cloud'."""
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    cloud_task_envelope_id: str | None = None
    request_hash: str | None = None
    result_hash: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    pipeline_status: Literal["pending_human", "rejected"]
    failure_code: str | None = None
    created_at: str


class HumanDecision(Contract):
    """V2.2 HumanDecision: the named human adoption of a candidate artifact.
    Until this record exists the artifact is a candidate output, not a
    decision. The decision binds actor, role and the exact artifact hash
    reviewed."""
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    artifact_hash: str = Field(min_length=1)
    request_hash: str | None = None
    decision: Literal["adopted"] = "adopted"
    actor: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    created_at: str


class Capability(Contract):
    """V2.2 Capability Registry record: what the platform can execute.

    Registered from task_engine definitions (built-in or entrypoint-loaded).
    A capability must exist and be available before any binding may point
    at it — an unregistered capability call is rejected."""
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    api_version: str = Field(min_length=1)
    name: str = ""
    execution_type: str = ""
    transports: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    privacy_contract: dict[str, Any] = Field(default_factory=dict)
    status: Literal["available", "disabled"] = "available"
    registered_by: str = "system"
    created_at: str
