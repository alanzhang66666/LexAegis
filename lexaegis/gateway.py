"""Only this service owns a cloud key. Its volume contains no original materials."""
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from .contracts import ApprovedRequest
from .providers import OpenAICompatibleProvider
from .storage import Store
from .util import digest, now, sign


class Envelope(BaseModel):
    request: ApprovedRequest
    approval: dict
    signature: str


def create_gateway(data_dir=None, secret=None, provider=None):
    root = Path(data_dir or os.getenv("LEX_GATEWAY_DIR", ".data/gateway"))
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    store = Store(root / "gateway.sqlite")
    secret = secret or os.getenv("LEX_GATEWAY_SECRET", "")
    provider = provider or OpenAICompatibleProvider(os.getenv("LEX_CLOUD_API_KEY", ""))
    app = FastAPI(title="LexAegis Egress Gateway", docs_url=None, redoc_url=None)
    app.state.store = store

    def auth(value, signature):
        if not secret or not hmac.compare_digest(sign(value, secret), signature):
            raise HTTPException(403, "Invalid gateway signature")

    @app.get("/health")
    def health(x_gateway_signature: str = Header(default="")):
        auth({"op": "health"}, x_gateway_signature)
        return {"status": "available" if getattr(provider, "api_key", None) else "unconfigured", "detail": "云端密钥已配置" if getattr(provider, "api_key", None) else "云端密钥未配置"}

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
        try:
            expired = datetime.fromisoformat(approval["expires_at"]) <= datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(403, "Invalid expiry")
        if expired or not request["policy"].get("approved_for_dispatch"):
            raise HTTPException(403, "Approval expired or policy blocked")
        if request["mode"] == "formal":
            # Defense in depth: v1 has no implemented complete attack suite.
            raise HTTPException(403, "Formal dispatch unavailable until verified risk suite is implemented")
        if not request["policy"].get("demo_exception"):
            raise HTTPException(403, "Missing synthetic demonstration scope")
        if request["transport"] == "cloud":
            url = urlparse(request["target"])
            allowed = {h.strip() for h in os.getenv("LEX_CLOUD_ALLOWED_HOSTS", "api.openai.com").split(",")}
            if url.scheme != "https" or url.hostname not in allowed or url.username or url.password or url.query or url.fragment or url.port not in (None, 443) or not url.path.endswith("/chat/completions"):
                raise HTTPException(403, "Cloud endpoint is outside gateway allowlist")
            if not getattr(provider, "api_key", None):
                raise HTTPException(409, "Cloud credential is not configured")
        with store.transaction() as repo:
            try:
                old = repo.get(request["request_id"], "send")
                if old["request_hash"] != digest(request):
                    raise HTTPException(409, "Request id collision")
                return old
            except KeyError:
                pass
            record = {"id": request["request_id"], "request_hash": digest(request), "status": "sending", "at": now(), "result": None}
            repo.put("send", record)
        try:
            if request["transport"] == "mock":
                import json
                facts = json.loads(request["body"]["messages"][1]["content"])["facts"]
                result = {"claims": [{"text": f["text"], "source_ids": [f["id"]]} for f in facts]}
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
