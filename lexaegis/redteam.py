"""Isolated placeholder: explicitly reports missing strategy, never safety success."""
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

app = FastAPI(docs_url=None, redoc_url=None)


class AttackerView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["identity", "candidate_set", "sensitive_inference", "cross_round"]
    request: dict
    disclosed_history: list[dict] = Field(default_factory=list)
    auxiliary: list[dict] = Field(default_factory=list)
    query_budget: int = Field(default=3, ge=1, le=10)


@app.post("/evaluate")
def evaluate(view: AttackerView):
    return {"capability": "unimplemented", "completion": "incomplete", "outcome": "not_run", "protocol": view.protocol, "findings": [], "reason": "策略未实现，不得计为安全通过"}
