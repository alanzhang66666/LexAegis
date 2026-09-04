"""Isolated red-team service. It rejects edge-only data and authenticates jobs."""
import hmac
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .attacks import assert_isolated_payload, evaluate as evaluate_attack
from .contracts import RiskProtocol
from .governance import protocol_content_hash
from .util import sign

app = FastAPI(docs_url=None, redoc_url=None)


@app.exception_handler(ValueError)
async def invalid_payload(request, error):
    return JSONResponse({"detail": str(error)}, status_code=422)


class AttackerView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: RiskProtocol | Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]
    request: dict
    disclosed_history: list[dict] = Field(default_factory=list)
    auxiliary: list[dict] = Field(default_factory=list)
    query_budget: int = Field(default=3, ge=1, le=10)


class AttackEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view: AttackerView
    signature: str


@app.post("/evaluate")
def evaluate(envelope: AttackEnvelope):
    payload = envelope.view.model_dump(mode="json")
    secret = os.getenv("LEX_REDTEAM_SECRET", "")
    if not secret or not hmac.compare_digest(envelope.signature, sign(payload, secret)):
        raise HTTPException(403, "红队作业签名无效")
    view = envelope.view
    assert_isolated_payload({
        "request": view.request,
        "history": view.disclosed_history,
        "auxiliary": view.auxiliary,
    })
    if isinstance(view.protocol, str):
        return {"capability": "unimplemented", "completion": "incomplete", "outcome": "not_run", "protocol": view.protocol,
                "evidence": ["兼容请求缺少冻结协议参数，不能运行或计为通过"]}
    protocol = view.protocol.model_dump()
    if (protocol["status"] != "frozen" or not protocol.get("content_hash")
            or protocol["content_hash"] != protocol_content_hash(protocol)):
        return {"capability": "available", "completion": "incomplete", "outcome": "not_run", "protocol": protocol["kind"], "evidence": ["协议未冻结"]}
    return evaluate_attack(protocol, view.request, view.disclosed_history, view.auxiliary)
