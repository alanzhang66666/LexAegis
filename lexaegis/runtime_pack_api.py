"""Production HTTP workflow for preparing, reviewing and activating rule packs."""
from pathlib import Path
from typing import Literal

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidenceStore
from . import runtime_pack
from .util import audit, canonical


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeDraft(Input):
    source_pack: dict
    import_report: dict
    scope_kind: Literal["first_acceptance", "request"] = "request"


class RuntimeReview(Input):
    review_record: str = Field(min_length=1, max_length=10000)
    law_05_evidence_id: str = Field(min_length=1)
    published_scope: dict[str, str]
    risk_weights: dict[str, float]
    references: list[str] = Field(min_length=1)
    dispatch_allowed: bool


class RuntimeRetire(Input):
    reason: str = Field(min_length=1, max_length=1000)


def register_runtime_pack_routes(app, store, root, require_role, require_exact_role):
    evidence = EvidenceStore(store, Path(root) / "release-evidence")
    base = "/api/v1/formal-release/runtime-packs"

    @app.get(base)
    def list_packs(request: Request):
        require_role(request, "technical_reviewer", "legal_reviewer", "approver")
        with store.read() as repo:
            return {"packs": repo.list("runtime_pack"), "activations": repo.list("runtime_pack_activation")}

    @app.post(base)
    def prepare_pack(body: RuntimeDraft, request: Request):
        actor = require_role(request, "technical_reviewer")
        with store.transaction() as repo:
            result = runtime_pack.create_runtime_pack_from_bytes(
                repo, canonical(body.source_pack).encode("utf-8"),
                canonical(body.import_report).encode("utf-8"), scope_kind=body.scope_kind)
            audit(repo, "", "runtime_pack.prepared", runtime_pack_id=result["id"],
                  actor_user_id=actor["user_id"], actor_role=actor["role"])
            return result

    @app.post(base + "/{pack_id}/review")
    def review_pack(pack_id: str, body: RuntimeReview, request: Request):
        actor = require_exact_role(request, "legal_reviewer")
        # Verify actual controlled bytes, rather than accepting a nonempty ID.
        evidence.read_artifact(body.law_05_evidence_id)
        with store.transaction() as repo:
            result = runtime_pack.review_runtime_pack(repo, pack_id, actor=actor["user_id"],
                legal_status="reviewed", **body.model_dump())
            audit(repo, "", "runtime_pack.reviewed", runtime_pack_id=pack_id,
                  actor_user_id=actor["user_id"], actor_role=actor["role"])
            return result

    @app.post(base + "/{pack_id}/publish")
    def publish_pack(pack_id: str, request: Request):
        actor = require_exact_role(request, "legal_reviewer")
        with store.read() as repo:
            existing = repo.get(pack_id, "runtime_pack")
        evidence.read_artifact(existing.get("law_05_evidence_id", ""))
        with store.transaction() as repo:
            result = runtime_pack.publish_runtime_pack(repo, pack_id, actor=actor["user_id"])
            active = runtime_pack.activate_runtime_pack(repo, pack_id, actor=actor["user_id"])
            return {"runtime_pack": result, "active_pack": active}

    @app.get(base + "/{pack_id}/export")
    def export_pack(pack_id: str, request: Request):
        require_role(request, "technical_reviewer", "legal_reviewer", "approver")
        with store.read() as repo:
            value = repo.get(pack_id, "runtime_pack")
        return Response(canonical(value), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="runtime-pack.json"'})

    @app.post(base + "/{pack_id}/retire")
    def retire_pack(pack_id: str, body: RuntimeRetire, request: Request):
        actor = require_role(request, "legal_reviewer")
        with store.transaction() as repo:
            return runtime_pack.retire_runtime_pack(repo, pack_id, actor=actor["user_id"], reason=body.reason)
