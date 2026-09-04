"""Versioned contracts. Domain packs contain data, never executable expressions."""
from enum import StrEnum
from typing import Literal, Protocol
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
    reviewed: bool = False


class DocumentIR(Contract):
    schema_version: int = 1
    document_id: str
    version: int
    blocks: list[SourceAnchor]
    needs_review: bool = False
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


class TaskDefinition(Contract):
    id: str
    name: str
    version: str = "1.0.0"
    available: bool = False
    output_type: str


class RiskAssessment(Contract):
    completion: Literal["complete", "incomplete", "error"]
    findings: list[str]
    blockers: list[str]
    attacks: list[dict]
    ledger_version: int
    approval_allowed: bool = False


class ApprovedRequest(Contract):
    request_id: str
    case_id: str
    task_id: str
    mode: Literal["formal", "demo"]
    transport: Literal["mock", "cloud"]
    target: str
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
