"""Only this service owns a cloud key. Its volume contains no original materials."""
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from .cloud import DualSlotProvider, cloud_endpoint_allowed, wire_contract_error
from .contracts import ApprovedRequest
from .runtime_identity import runtime_identity
from .storage import Store
from .util import digest, now, restrict_mode, sign


class Envelope(BaseModel):
    request: ApprovedRequest
    approval: dict
    signature: str


def create_gateway(data_dir=None, secret=None, provider=None, build_manifest=None):
    root = Path(data_dir or os.getenv("LEX_GATEWAY_DIR", ".data/gateway"))
    root.mkdir(parents=True, exist_ok=True)
    restrict_mode(root, 0o700)
    store = Store(root / "gateway.sqlite")
    secret = secret or os.getenv("LEX_GATEWAY_SECRET", "")
    provider = provider or DualSlotProvider.from_env()
    app = FastAPI(title="LexAegis Egress Gateway", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.runtime_identity = runtime_identity("gateway", build_manifest)

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
        auth({"request": request, "approval": approval}, envelope.signature)
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
            if not cloud_ready():
                raise HTTPException(409, "Cloud credential is not configured")
        with store.transaction() as repo:
            try:
                old = repo.get(request["request_id"], "send")
                if old["request_hash"] != digest(request):
                    raise HTTPException(409, "Request id collision")
                return old
            except KeyError:
                pass
            record = {"id": request["request_id"], "request_hash": digest(request), "status": "sending",
                      "at": now(), "result": None, "attempts": [], "authorized_recipients": []}
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
        return record

    return app
