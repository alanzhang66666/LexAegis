"""Only this service owns a cloud key. Its volume contains no original materials."""
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from .cloud import DualSlotProvider, cloud_endpoint_allowed, wire_contract_error
from .contracts import (ApprovedRequest, FormalReleasePolicy, FrozenFormalRequest,
                        OneTimeDispatchGrant, ReleaseBuildManifest)
from .formal_release import FIRST_RELEASE_TUPLE, FormalReleaseError, complete_gateway_claim, gateway_claim
from .runtime_identity import runtime_identity, _load_manifest
from .runtime_profile import bind_runtime, dispatch_scope
from .storage import Store
from .util import digest, now, restrict_mode, sign


class Envelope(BaseModel):
    request: ApprovedRequest
    approval: dict
    formal_release: dict | None = None
    cloud_envelope: dict | None = None
    signature: str


def create_gateway(data_dir=None, secret=None, provider=None, build_manifest=None):
    root = Path(data_dir or os.getenv("LEX_GATEWAY_DIR", ".data/gateway"))
    runtime = bind_runtime(root, "gateway")
    startup_profile = runtime["runtime_profile"]
    restrict_mode(root, 0o700)
    store = Store(root / "gateway.sqlite")
    secret = secret or os.getenv("LEX_GATEWAY_SECRET", "")
    provider = provider or DualSlotProvider.from_env()
    # V2.2 云侧角色: "unified" runs both surfaces in one process (default,
    # single-node dev). "edge" may serve the claim surface but must not hold
    # cloud credentials — only the cloud-domain gateway owns provider keys.
    # "cloud" refuses to start without a credential so a misdeployed
    # credential-less cloud gateway fails closed instead of 409ing at send
    # time. The claim/queue split across roles is a deployment step; in one
    # process both surfaces still share this app.
    gateway_role = (os.getenv("LEX_GATEWAY_ROLE") or "unified").strip().lower()
    if gateway_role not in {"unified", "edge", "cloud"}:
        raise ValueError("LEX_GATEWAY_ROLE must be unified, edge or cloud")
    _has_key = bool(getattr(provider, "api_key", None) or getattr(provider, "primary_key", None))
    if gateway_role == "edge" and _has_key:
        raise ValueError("LEX_GATEWAY_ROLE=edge forbids holding cloud credentials")
    if gateway_role == "cloud" and not _has_key:
        raise ValueError("LEX_GATEWAY_ROLE=cloud requires a configured cloud credential")
    app = FastAPI(title="LexAegis Egress Gateway", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.runtime_profile = startup_profile
    app.state.runtime_identity = runtime_identity("gateway", build_manifest)
    configured_manifest, _manifest_failure = _load_manifest(build_manifest, None)
    app.state.build_manifest = configured_manifest

    def auth(value, signature):
        if not secret or not hmac.compare_digest(sign(value, secret), signature):
            raise HTTPException(403, "Invalid gateway signature")

    def cloud_ready():
        return bool(getattr(provider, "api_key", None) or getattr(provider, "primary_key", None))

    @app.get("/health")
    def health(x_gateway_signature: str = Header(default="")):
        auth({"op": "health"}, x_gateway_signature)
        primary = cloud_ready()
        standby = bool(getattr(provider, "standby_key", ""))
        if primary and standby:
            detail = "云端主备密钥已配置"
        elif primary:
            detail = "云端密钥已配置；备用槽未配置，仅走主槽"
        else:
            detail = "云端密钥未配置"
        return {
            "status": "available" if primary else "unconfigured",
            "gateway_role": gateway_role,
            "primary": "available" if primary else "unconfigured",
            "standby": "available" if standby else "unconfigured",
            "detail": detail,
            "runtime_identity": app.state.runtime_identity.public(),
        }

    @app.get("/requests/{request_id}")
    def status(request_id: str, x_gateway_signature: str = Header(default="")):
        auth({"op": "status", "request_id": request_id}, x_gateway_signature)
        with store.read() as repo:
            try:
                result = repo.get(request_id, "send")
            except KeyError:
                raise HTTPException(404, "No dispatch record")
        return result

    @app.post("/dispatch")
    def dispatch(envelope: Envelope):
        request = envelope.request.model_dump()
        approval = envelope.approval
        signed = {"request": request, "approval": approval}
        if envelope.formal_release is not None:
            signed["formal_release"] = envelope.formal_release
        if envelope.cloud_envelope is not None:
            signed["cloud_envelope"] = envelope.cloud_envelope
        auth(signed, envelope.signature)
        if request.get("transport") == "cloud" and not cloud_endpoint_allowed(request.get("target", "")):
            raise HTTPException(403, "Cloud endpoint is outside gateway allowlist")
        _validate_cloud_envelope(envelope.cloud_envelope, request)
        try:
            dispatch_scope(request)
            if startup_profile in {"demo", "integration"}:
                from .synthetic_scope import validate_synthetic_request
                validate_synthetic_request(request)
        except ValueError as error:
            raise HTTPException(403, str(error)) from error
        if digest(request) != approval.get("request_hash"):
            raise HTTPException(403, "Approval hash mismatch")
        if approval.get("actor_role") != "approver" or not approval.get("actor"):
            raise HTTPException(403, "Named approver is required")
        if approval.get("dependencies") != request.get("dependencies"):
            raise HTTPException(403, "Approval dependencies mismatch")
        try:
            expired = datetime.fromisoformat(approval["expires_at"]) <= datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(403, "Invalid expiry")
        if expired or not request["policy"].get("approved_for_dispatch"):
            raise HTTPException(403, "Approval expired or policy blocked")
        wire = request.get("wire_payload") or {}
        wire_error = wire_contract_error(wire)
        if wire_error:
            raise HTTPException(403, wire_error)
        if request["mode"] == "formal" and (request["policy"].get("risk_completion") != "complete" or request["policy"].get("demo_exception")):
            raise HTTPException(403, "Formal dispatch gates are incomplete")
        if request["mode"] == "demo" and not request["policy"].get("demo_exception"):
            raise HTTPException(403, "Missing synthetic demonstration scope")
        formal = envelope.formal_release
        if startup_profile == "production" and request["transport"] == "cloud" and formal is None:
            raise HTTPException(403, "Formal production cloud dispatch requires a scoped one-time grant")
        if startup_profile == "integration" and formal is not None:
            raise HTTPException(403, "Synthetic integration cannot consume a formal release grant")
        if startup_profile == "demo" and formal is not None:
            raise HTTPException(403, "Offline demo cannot consume a formal release grant")
        if request["transport"] not in {"cloud", "mock"}:
            raise HTTPException(403, "Gateway only accepts cloud dispatch or offline mock requests")
        if request["transport"] == "mock" and startup_profile != "demo":
            raise HTTPException(403, "Mock dispatch is restricted to the offline demo profile")
        dual_slot = (request.get("dependencies") or {}).get("dual_slot") if request["transport"] == "cloud" else None
        if request["transport"] == "cloud":
            slots = dual_slot if isinstance(dual_slot, dict) else {}
            approved_targets = []
            for name in ("primary", "standby"):
                slot = slots.get(name) or {}
                target = slot.get("target")
                if not target:
                    continue
                if not cloud_endpoint_allowed(target):
                    raise HTTPException(403, "Cloud endpoint is outside gateway allowlist")
                if name == "primary" and slot.get("model") and request.get("body", {}).get("model") not in (None, "", slot["model"]):
                    raise HTTPException(403, "Request model is not the approved primary slot")
                approved_targets.append(target)
            if not approved_targets:
                raise HTTPException(403, "No approved cloud recipient")
            if request["target"] not in approved_targets:
                raise HTTPException(403, "Request target is not an approved recipient")
            if formal is not None:
                formal_policy = FormalReleasePolicy.model_validate((formal.get("policy") or {}))
                standby_slot = slots.get("standby")
                if standby_slot:
                    if (formal_policy.scope_kind != "request" or not formal_policy.allowed_standby_target
                            or standby_slot.get("target") != formal_policy.allowed_standby_target
                            or standby_slot.get("model") != formal_policy.allowed_standby_model):
                        raise HTTPException(403, "Standby slot is outside the signed formal policy scope")
                if not slots.get("primary") or slots["primary"].get("target") != request["target"]:
                    raise HTTPException(403, "Formal request target must match its primary slot")
        with store.transaction() as repo:
            try:
                old = repo.get(request["request_id"], "send")
                if old["request_hash"] != digest(request):
                    raise HTTPException(409, "Request id collision")
                return old
            except KeyError:
                pass
            if request["transport"] == "cloud" and not cloud_ready():
                raise HTTPException(409, "Cloud credential is not configured")
            formal_claim = None
            if startup_profile == "production" and request["transport"] == "cloud":
                formal_claim = _persist_and_claim_formal(repo, formal, request, approval,
                                                         app.state.runtime_identity,
                                                         app.state.build_manifest)
            record = {"id": request["request_id"], "request_hash": digest(request), "status": "sending",
                      "at": now(), "result": None, "attempts": [], "authorized_recipients": [],
                      "formal_claim_id": formal_claim["id"] if formal_claim else None}
            repo.put("send", record)

        def persist_attempt(attempts, authorized):
            record["attempts"] = attempts
            record["authorized_recipients"] = authorized
            with store.transaction() as repo:
                repo.put("send", record)

        try:
            if request["transport"] == "mock":
                import json
                facts = json.loads(request["body"]["messages"][1]["content"])["facts"]
                result = {"claims": [{"text": f["text"], "source_ids": [f["id"]]} for f in facts],
                          "unused_fact_ids": [], "gaps": []}
                record.update(status="complete", result=result)
            elif hasattr(provider, "dispatch"):
                outcome = provider.dispatch(request["target"], request["body"], dual_slot=dual_slot,
                                           persist_attempt=persist_attempt)
                record.update(outcome.ledger_fields())
                if outcome.status == "complete":
                    record.update(status="complete", result=outcome.result)
                else:
                    record.update(status="unknown", error="调用后结果不明；禁止自动重发，请核对服务商记录")
            else:
                result = provider.send(request["target"], request["body"])
                record.update(status="complete", result=result)
        except Exception:
            # Never log request contents, keys, or provider error bodies.
            record.update(status="unknown", error="调用后结果不明；禁止自动重发，请核对服务商记录")
        with store.transaction() as repo:
            repo.put("send", record)
            if record.get("formal_claim_id"):
                outcome = {"status": record["status"],
                           "error_code": "gateway_unknown" if record["status"] == "unknown" else ""}
                complete_gateway_claim(repo, record["formal_claim_id"], outcome)
        return record

    return app


_ENVELOPE_REQUIRED_KEYS = (
    "case_ref", "task_id", "cause_id", "context_version_id",
    "domain_runtime_snapshot_id", "request_hash", "contract_version", "facts",
)


def _validate_cloud_envelope(cloud_envelope, request):
    """V2.2 CloudContext check: snapshot-bound cloud tasks must carry a
    consistent envelope. Fail-closed on missing or drifting fields. Legacy
    requests without a snapshot dependency are unaffected."""
    if request.get("transport") != "cloud":
        return
    snapshot_dep = (request.get("dependencies") or {}).get("domain_runtime_snapshot_id")
    if not snapshot_dep:
        return
    if not isinstance(cloud_envelope, dict):
        raise HTTPException(403, "Cloud task envelope required for snapshot-bound requests")
    missing = [key for key in _ENVELOPE_REQUIRED_KEYS
               if cloud_envelope.get(key) in (None, "", [])]
    if missing:
        raise HTTPException(403, f"Cloud task envelope missing fields: {', '.join(missing)}")
    if cloud_envelope["task_id"] != request.get("task_id"):
        raise HTTPException(403, "Cloud task envelope task mismatch")
    if cloud_envelope["domain_runtime_snapshot_id"] != snapshot_dep:
        raise HTTPException(403, "Cloud task envelope snapshot mismatch")
    if cloud_envelope["request_hash"] != digest(request):
        raise HTTPException(403, "Cloud task envelope request hash mismatch")
    if cloud_envelope["context_version_id"] != (request.get("dependencies") or {}).get("context_version_id"):
        raise HTTPException(403, "Cloud task envelope context version mismatch")
    wire_facts = (request.get("wire_payload") or {}).get("facts")
    if wire_facts is not None and cloud_envelope["facts"] != wire_facts:
        raise HTTPException(403, "Cloud task envelope facts drift from wire payload")
    if cloud_envelope.get("case_ref") == request.get("case_id"):
        raise HTTPException(403, "Cloud task envelope leaks the raw case id")


def _persist_and_claim_formal(repo, bundle, request, approval, identity, manifest):
    """Persist the signed, minimal grant projection locally, then claim once.

    This endpoint is reached only after HMAC verification of the whole envelope.
    The gateway never accepts a client-supplied build manifest as authority.
    """
    if not isinstance(bundle, dict) or bundle.get("version") != 1:
        raise HTTPException(403, "Invalid formal release bundle")
    if manifest is None or identity.status != "verified":
        raise HTTPException(403, "Gateway has no verified local release build identity")
    try:
        frozen = FrozenFormalRequest.model_validate(bundle.get("frozen_request"))
        policy = FormalReleasePolicy.model_validate(bundle.get("policy"))
        grant = OneTimeDispatchGrant.model_validate(bundle.get("grant"))
        projection = bundle.get("projection")
        if not isinstance(projection, dict):
            raise FormalReleaseError("signed formal projection is missing")
        if frozen.request_hash != digest(request) or frozen.request_id != request.get("request_id"):
            raise FormalReleaseError("frozen formal request does not match signed dispatch request")
        if policy.status != "armed_once" or policy.consumed_dispatches != 0:
            raise FormalReleaseError("release policy is not an available single-use policy")
        if (policy.scope_kind == "request" and policy.bound_request_hash != frozen.request_hash
                or policy.scope_kind == "first_acceptance" and frozen.tuple != FIRST_RELEASE_TUPLE):
            raise FormalReleaseError("release policy is bound to another request scope")
        if (policy.build_manifest_hash != identity.runtime_identity_hash
                or frozen.build_manifest_hash != identity.runtime_identity_hash
                or policy.tuple != frozen.tuple or policy.allowed_target != frozen.target
                or policy.allowed_model != frozen.model):
            raise FormalReleaseError("signed policy is outside local gateway build or request scope")
        if bool(policy.allowed_standby_target) != bool(frozen.standby_target) or (
                frozen.standby_target and (
                    policy.allowed_standby_target != frozen.standby_target
                    or policy.allowed_standby_model != frozen.standby_model
                    or policy.allowed_standby_provider_profile_hash != frozen.standby_provider_profile_hash)):
            raise FormalReleaseError("signed policy standby scope does not match frozen request")
        if (grant.release_policy_id != policy.id or grant.request_hash != frozen.request_hash
                or grant.build_manifest_hash != frozen.build_manifest_hash
                or grant.tuple != frozen.tuple or grant.state not in {"issued", "reserved"}):
            raise FormalReleaseError("signed one-time grant is outside frozen request scope")
        expected_projection = {
            "request_hash": frozen.request_hash,
            "target": frozen.target,
            "model": frozen.model,
            "provider_profile_hash": frozen.provider_profile_hash,
        }
        if projection != expected_projection:
            raise FormalReleaseError("signed projection does not match frozen request")
        for kind, item, contract in (
            ("formal_release_policy", policy, FormalReleasePolicy),
            ("one_time_dispatch_grant", grant, OneTimeDispatchGrant),
        ):
            try:
                prior = contract.model_validate(repo.get(item.id, kind))
            except KeyError:
                repo.put(kind, item.model_dump(mode="json"))
            else:
                if prior != item:
                    # Never let a later client projection overwrite a consumed,
                    # claimed, or otherwise changed local record.
                    raise FormalReleaseError(f"local {kind} record already differs from signed projection")
        return gateway_claim(repo, frozen=frozen, approval=approval, grant_id=grant.id,
                             gateway_request_id=request["request_id"], projection=projection,
                             runtime_identity=identity, build_manifest=manifest)
    except (FormalReleaseError, ValueError, TypeError) as error:
        raise HTTPException(403, str(error)) from error
