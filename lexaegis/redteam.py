"""Isolated red-team service. It rejects raw text, mappings, anchors and truth."""
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .attacks import evaluate as evaluate_attack
from .contracts import RiskProtocol

app = FastAPI(docs_url=None, redoc_url=None)


class AttackerView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: RiskProtocol | Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]
    request: dict
    disclosed_history: list[dict] = Field(default_factory=list)
    auxiliary: list[dict] = Field(default_factory=list)
    query_budget: int = Field(default=3, ge=1, le=10)


@app.post("/evaluate")
def evaluate(view: AttackerView):
    if isinstance(view.protocol, str):
        return {"capability": "unimplemented", "completion": "incomplete", "outcome": "not_run", "protocol": view.protocol,
                "evidence": ["兼容请求缺少冻结协议参数，不能运行或计为通过"]}
    protocol = view.protocol.model_dump()
    if protocol["status"] != "frozen" or not protocol.get("content_hash"):
        return {"capability": "available", "completion": "incomplete", "outcome": "not_run", "protocol": protocol["kind"], "evidence": ["协议未冻结"]}
    return evaluate_attack(protocol, view.request, view.disclosed_history, view.auxiliary)
