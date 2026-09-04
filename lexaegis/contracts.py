"""Versioned contracts. Domain packs contain data, never executable expressions."""
from enum import StrEnum
from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capability(StrEnum):
    AVAILABLE = "available"
    UNCONFIGURED = "unconfigured"
    UNIMPLEMENTED = "unimplemented"
    FAILED = "failed"


class SourceAnchor(Contract):
    id: str
    document_id: str
    document_version: int
    kind: Literal["paragraph", "table", "pdf_text", "ocr", "scan"]
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


class DomainPack(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    name: str
    version: str
    status: Literal["draft", "demo", "published"]
    task_ids: list[str]
    fact_fields: list[str]
    rules: list[FieldRule]
    references: list[str]
    review_record: str | None = None
    required_attacks: list[Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]]


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
    manual_review_conditions: list[str] = Field(default_factory=list)
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
    attacks: list[dict]
    ledger_version: int
    approval_allowed: bool = False


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
    wire_token: str = Field(pattern=r"^\[\[LEX:P\d{4,}\]\]$")
    display_alias: str
    original_value: str
    source_ids: list[str] = Field(default_factory=list)
    mapping_version: int = Field(ge=1)


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
    outcome: Literal["resisted", "succeeded", "uncertain", "error", "not_run", "not_applicable"]
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
    role: Literal["processor", "independent_controller", "other", "unknown"] = "unknown"
    processing_regions: list[str] = Field(default_factory=list)
    retention: str | None = None
    training_use: Literal["forbidden", "allowed", "unknown"] = "unknown"
    human_access: Literal["forbidden", "controlled", "allowed", "unknown"] = "unknown"
    subprocessors: list[str] = Field(default_factory=list)
    subprocessor_status: Literal["none", "declared", "unknown"] = "unknown"
    deletion_mechanism: str | None = None
    contract_reference: str | None = None
    impact_assessment_reference: str | None = None
    valid_until: str | None = None
    allowed_tasks: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_fields: list[str] = Field(default_factory=list)
    allowed_transports: list[Literal["cloud"]] = Field(default_factory=list)
    status: Literal["draft", "reviewed", "expired"] = "draft"
    profile_version: int = Field(default=1, ge=1)
    reviewed_by: str | None = None
    reviewed_at: str | None = None


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
    transport: Literal["mock", "cloud"]
    target: str
    wire_payload: dict | None = None
    body: dict
    dependencies: dict
    policy: dict


class TaskArtifact(Contract):
    claims: list[dict]
    provenance: Literal["simulation", "cloud"]
    confirmed: bool = False


class EdgeInference(Protocol):
    def extract(self, blocks: list[dict]) -> list[dict]: ...


class RiskEvaluator(Protocol):
    def evaluate(self, attacker_view: dict) -> dict: ...


class CloudProvider(Protocol):
    def send(self, target: str, body: dict) -> dict: ...
