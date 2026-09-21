import json

import httpx
import pytest

from lexaegis import providers
from lexaegis import service
from lexaegis.providers import EdgeClient
from .conftest import demo_task


class _FakeClient:
    content = "{}"

    def __init__(self, *args, **kwargs):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        self.calls.append((url, json))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": self.content}}]},
            request=httpx.Request("POST", url),
        )


def test_edge_review_uses_strict_json_contract_and_hashes_reply(monkeypatch):
    captured = {}

    class Capturing(_FakeClient):
        content = json.dumps({
            "decision": "allow_human_review",
            "reason": "候选内容可交人工复核。",
            "risk_codes": [],
            "evidence_fact_ids": ["F1"],
        })

        def post(self, url, json=None):
            captured.update(url=url, body=json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Capturing)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").review_outbound([
        {"id": "f1", "field": "event", "text": "合成材料"},
    ])
    assert result["decision"] == "allow_human_review"
    assert result["evidence_fact_ids"] == ["f1"]
    assert result["response_hash"].startswith("sha256:")
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["response_format"]["json_schema"]["schema"]["properties"]["decision"]["enum"] == [
        "block_external", "allow_human_review"
    ]


def test_edge_review_rejects_unknown_evidence_identifier(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", _FakeClient)
    _FakeClient.content = json.dumps({
        "decision": "block_external", "reason": "风险", "risk_codes": ["risk"],
        "evidence_fact_ids": ["not-present"],
    })
    with pytest.raises(ValueError, match="未输入"):
        EdgeClient("http://localhost:11434/v1", "edge-small").review_outbound([
            {"id": "f1", "field": "event", "text": "合成材料"},
        ])


def test_live_edge_allow_is_overridden_for_unredacted_direct_identifier_combo():
    result = service._edge_review_safety_floor({
        "source": "live_edge_model", "decision": "allow_human_review",
        "reason": "模型允许人工复核", "risk_codes": [], "evidence_fact_ids": ["id", "phone"],
    }, [
        {"id": "id", "field": "identity", "text": "身份证号 110101199001011234"},
        {"id": "phone", "field": "contact", "text": "手机号 13800138000"},
    ])
    assert result["decision"] == "block_external"
    assert result["model_decision"] == "allow_human_review"
    assert result["source"] == "live_edge_model_with_policy_floor"
    assert result["safety_floor"]["applied"] is True


@pytest.mark.parametrize(
    ("scenario", "decision"),
    [
        ("linkage", "block_external"),
        ("human_veto", "allow_human_review"),
        ("success", "allow_human_review"),
        ("stop", "block_external"),
    ],
)
def test_four_demo_boundaries_persist_auditable_edge_review(demo_env, scenario, decision):
    _case, task = demo_task(demo_env, scenario)
    result = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert result.status_code == 200, result.text
    review = result.json()["edge_review"]
    assert review["decision"] == decision
    assert review["source"] == "bundled_synthetic_fixture"
    assert review["response_hash"].startswith("sha256:")
    if decision == "block_external":
        assert result.json()["risk"]["approval_allowed"] is False
