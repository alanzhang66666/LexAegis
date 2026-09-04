import json

import httpx
import pytest

from lexaegis import providers, service
from lexaegis.providers import EdgeClient
from lexaegis.worker import process_one
from .test_workflow import formal_material


class FakeHTTPClient:
    content = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        body = {
            "choices": [{
                "message": {"content": self.content},
            }],
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def test_edge_contract_rejects_invalid_json_unknown_source_and_excess(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    client = EdgeClient("http://localhost:11434/v1", "edge-small")
    blocks = [{"id": "b1", "text": "纯模拟材料"}]

    FakeHTTPClient.content = "not-json"
    with pytest.raises(json.JSONDecodeError):
        client.extract(blocks)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["missing"]}],
    })
    with pytest.raises(ValueError, match="来源"):
        client.extract(blocks)
    FakeHTTPClient.content = json.dumps({"facts": [
        {"field": "event", "value": "模拟事实", "source_ids": ["b1"]}
        for _ in range(501)
    ]})
    with pytest.raises(ValueError, match="500"):
        client.extract(blocks)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "unsupported", "value": "模拟事实", "source_ids": ["b1"]}],
    })
    with pytest.raises(ValueError):
        client.extract(blocks)


def test_edge_request_uses_deterministic_json_contract(monkeypatch):
    captured = {}

    class Capturing(FakeHTTPClient):
        content = json.dumps({
            "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["b1"]}],
        })

        def post(self, url, json=None):
            captured.update(url=url, body=json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Capturing)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "纯模拟材料"}],
    )
    assert result[0]["source_ids"] == ["b1"]
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_material_change_during_edge_extraction_discards_result(env, monkeypatch):
    case, _, _ = formal_material(env)
    settings = env["client"].get("/api/v1/bootstrap").json()["settings"]
    body = {
        key: settings[key]
        for key in ("cloud_url", "cloud_model", "edge_url", "deployment_mode", "isolation_verified")
    }
    body["edge_model"] = "edge-small"
    assert env["client"].put("/api/v1/settings", json=body).status_code == 200
    queued = env["client"].post(f"/api/v1/cases/{case['id']}/extract")
    assert queued.status_code == 200
    monkeypatch.setattr(EdgeClient, "extract", lambda self, blocks: [{
        "field": "event",
        "value": "不应写入的过期结果",
        "source_ids": [blocks[0]["id"]],
        "suggested_transform": "delete",
        "disclosure_reason": "测试",
    }])
    with env["app"].state.store.transaction() as repo:
        current = service.get_case(repo, case["id"])
        service.touch_case(repo, current, "test.concurrent_material_change")
    process_one(env["app"].state.store, env["root"], env["gate"])
    detail = env["client"].get(f"/api/v1/cases/{case['id']}").json()
    assert all(fact["value"] != "不应写入的过期结果" for fact in detail["facts"])
    assert next(job for job in detail["jobs"] if job["id"] == queued.json()["id"])["status"] == "failed"
