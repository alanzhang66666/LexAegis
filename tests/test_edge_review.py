import json

import httpx
import pytest

from lexaegis import providers
from lexaegis import service
from lexaegis.outbound_gate import product_dispatch_state
from lexaegis.providers import EdgeClient
from lexaegis.service import DomainError
from .conftest import demo_task, post_as


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


def test_edge_review_prompt_lets_wage_dispute_reach_human_review():
    prompt = providers.EDGE_REVIEW_PROMPT
    assert "绝不授予发送或外发权限" in prompt
    for marker in ("唯一", "公开获奖", "公开表彰"):
        assert marker in prompt
    assert "普通工资争议" in prompt
    assert "decision 必须写成 allow_human_review" in prompt
    assert "禁止把 decision 写成 block_external" in prompt
    assert "任意两项" not in prompt


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
    body = result.json()
    review = body["edge_review"]
    assert review["decision"] == decision
    assert review["source"] == "bundled_synthetic_fixture"
    assert review["response_hash"].startswith("sha256:")
    if decision == "block_external":
        assert body["risk"]["approval_allowed"] is False
        edge_hits = [
            hit for hit in body["risk"]["gates"]
            if str(hit.get("message") or "").startswith("边侧模型审核未允许进入人工复核：")
        ]
        assert edge_hits
        assert {hit["id"] for hit in edge_hits} == {"G0"}
        assert not any(
            hit["id"] == "G3" and str(hit.get("message") or "").startswith("边侧模型审核")
            for hit in body["risk"]["gates"]
        )


def test_review_draft_prompt_does_not_grant_dispatch():
    prompt = providers.EDGE_REVIEW_DRAFT_PROMPT
    assert "绝不授予发送或外发权限" in prompt
    assert "不能代替 legal_reviewer 提交" in prompt
    assert "不得编造 id" in prompt


def test_review_draft_drops_unknown_catalog_ids(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", _FakeClient)
    _FakeClient.content = json.dumps({
        "suggested_conclusion": "allow_processing",
        "reason": "普通工资争议可交复核。",
        "fact_premise": "事实 F1 记载工资争议。",
        "authority_judgment": "只进入人工复核。",
        "external_processing_note": "按已冻结目标。",
        "minimization_note": "身份保持 token。",
        "final_basis": "依据输入事实。",
        "scope_note": "不授予发送权。",
        "evidence_fact_ids": ["F1", "F9"],
        "legal_source_ids": ["S1", "made-up"],
        "reviewed_condition_ids": ["C2"],
    })
    draft = EdgeClient("http://localhost:11434/v1", "edge-small").draft_review(
        [{"id": "fact-1", "field": "event", "text": "工资"}],
        [{"id": "src-1", "title": "劳动合同法"}],
        [{"id": "cond-1", "trigger": "工资"}],
    )
    assert draft["evidence_fact_ids"] == ["fact-1"]
    assert draft["legal_source_ids"] == ["src-1"]
    assert draft["reviewed_condition_ids"] == []
    assert draft["grants_dispatch"] is False
    assert draft["recorded"] is False
    assert draft["source"] == "live_edge_model"


def test_compose_review_draft_refuses_safety_floor_override():
    snapshot = {
        "edge_review": {
            "decision": "allow_human_review",
            "safety_floor": {"applied": True},
        },
        "facts": [],
        "case_mode": "demo",
    }
    with pytest.raises(DomainError, match="不生成复核底稿"):
        service.compose_review_draft(snapshot)


def test_review_draft_fills_worksheet_without_recording(demo_env, monkeypatch):
    monkeypatch.setenv("LEX_DEMO_LIVE_EDGE_REVIEW", "0")
    called = {"model": False}

    def refuse_model(*_args, **_kwargs):
        called["model"] = True
        raise AssertionError("demo fixture must not call the edge model")

    monkeypatch.setattr(EdgeClient, "draft_review", refuse_model)
    env = demo_env
    client = env["client"]
    _case, task = demo_task(env)
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    before = evaluated.json()
    assert before["edge_review"]["decision"] == "allow_human_review"
    denied = client.post(f"/api/v1/tasks/{task['id']}/review-draft")
    assert denied.status_code == 403
    drafted = post_as(env, "legal_reviewer", f"/api/v1/tasks/{task['id']}/review-draft")
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    assert called["model"] is False
    assert body["source"] == "bundled_synthetic_fixture"
    assert body["recorded"] is False
    assert body["grants_dispatch"] is False
    assert body["suggested_conclusion"] is None
    assert body["request_hash"] == before["request_hash"]
    assert "不授予发送权" in body["scope_note"]
    assert body["fact_premise"]
    assert body["legal_source_ids"] == []
    stored = client.get(f"/api/v1/cases/{task['case_id']}").json()
    current = next(item for item in stored["tasks"] if item["id"] == task["id"])
    assert current.get("legal_review") is None
    assert current["risk"]["approval_allowed"] == before["risk"]["approval_allowed"]
    assert product_dispatch_state() == "blocked"
    caps = client.get("/api/v1/capabilities").json()
    assert caps["validation"]["formal_dispatch"] == "blocked"


def test_review_draft_refuses_edge_block(demo_env, monkeypatch):
    monkeypatch.setenv("LEX_DEMO_LIVE_EDGE_REVIEW", "0")
    _case, task = demo_task(demo_env, "linkage")
    evaluated = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["edge_review"]["decision"] == "block_external"
    drafted = post_as(demo_env, "legal_reviewer", f"/api/v1/tasks/{task['id']}/review-draft")
    assert drafted.status_code == 409
    assert "不生成复核底稿" in drafted.json()["detail"]
