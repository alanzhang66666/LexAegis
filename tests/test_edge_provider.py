import json

import httpx
import pytest

from lexaegis import diagnostics, providers, service
from lexaegis.providers import (
    EXTRACT_FIELD_RETRY_USER,
    EXTRACT_PROMPT,
    EXTRACT_REFILL_USER,
    FACT_FIELDS,
    EdgeClient,
    ExtractTruncatedError,
    ProposedFact,
    extract_max_events,
    extract_max_facts,
    extract_max_tokens,
    facts_need_refill,
    merge_extract_facts,
)
from lexaegis.worker import EXTRACT_CHUNK_BLOCKS, EXTRACT_CHUNK_CHARS, chunk_extract_blocks, process_one
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
    limit = extract_max_facts()
    FakeHTTPClient.content = json.dumps({"facts": [
        {"field": "event", "value": "模拟事实", "source_ids": ["b1"]}
        for _ in range(limit + 1)
    ]})
    with pytest.raises(ValueError, match=str(limit)):
        client.extract(blocks)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "unsupported", "value": "模拟事实", "source_ids": ["b1"]}],
    })
    with pytest.raises(ValueError, match="合法 field"):
        client.extract(blocks)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["b1"], "quote": "不是原文"}],
    })
    kept = client.extract(blocks)
    assert kept[0]["value"] == "模拟事实"
    assert kept[0]["quote"] is None


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
    assert captured["body"]["max_tokens"] == extract_max_tokens()
    fmt = captured["body"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"]["properties"]["facts"]["type"] == "array"
    assert fmt["json_schema"]["schema"]["properties"]["facts"]["maxItems"] == extract_max_facts()
    assert fmt["json_schema"]["schema"]["properties"]["facts"]["items"]["properties"]["field"]["enum"] == list(FACT_FIELDS)
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert '"field":"entity|relation' not in captured["body"]["messages"][0]["content"]
    assert "entity|relation|event|date|amount|evidence" not in EXTRACT_PROMPT
    assert "|" not in EXTRACT_PROMPT


def test_extract_skips_pipe_field_and_keeps_valid_facts(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [
            {"field": "entity|relation|event|date|amount|evidence", "value": "应跳过", "source_ids": ["b1"]},
            {"field": "amount", "value": "12000元", "source_ids": ["b1"]},
        ],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert [fact["value"] for fact in result] == ["12000元"]
    assert result[0]["field"] == "amount"


def test_extract_prompt_uses_json_array_fields_not_pipes():
    assert json.dumps(list(FACT_FIELDS)) in EXTRACT_PROMPT
    assert "entity|relation|event|date|amount|evidence" not in EXTRACT_PROMPT
    assert "|" not in EXTRACT_PROMPT
    assert "|" not in EXTRACT_FIELD_RETRY_USER
    assert EXTRACT_FIELD_RETRY_USER == f'每个 field 必须是 {json.dumps(list(FACT_FIELDS))} 中的单个词。'


def test_extract_retries_once_when_first_response_is_all_pipe_fields(monkeypatch):
    calls = []
    pipe = json.dumps({
        "facts": [{"field": "entity|relation|event|date|amount|evidence", "value": "应跳过", "source_ids": ["b1"]}],
    })
    valid = json.dumps({
        "facts": [{"field": "amount", "value": "12000元", "source_ids": ["b1"]}],
    })

    class Sequential(FakeHTTPClient):
        contents = [pipe, valid]

        def post(self, url, json=None):
            self.content = self.contents[len(calls)]
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert [fact["field"] for fact in result] == ["amount"]
    assert [fact["value"] for fact in result] == ["12000元"]
    assert len(calls) == 2
    retry_users = [message["content"] for message in calls[1]["messages"] if message["role"] == "user"]
    assert EXTRACT_FIELD_RETRY_USER in retry_users
    assert "单个" in EXTRACT_FIELD_RETRY_USER
    assert json.dumps(list(FACT_FIELDS)) in EXTRACT_FIELD_RETRY_USER


def test_extract_all_pipe_second_response_raises_after_one_retry(monkeypatch):
    calls = []
    pipe = json.dumps({
        "facts": [{"field": "entity|relation|event|date|amount|evidence", "value": "应跳过", "source_ids": ["b1"]}],
    })

    class Sequential(FakeHTTPClient):
        def post(self, url, json=None):
            self.content = pipe
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    with pytest.raises(ValueError, match="合法 field"):
        EdgeClient("http://localhost:11434/v1", "edge-small").extract(
            [{"id": "b1", "text": "主张工资12000元"}],
        )
    assert len(calls) == 2
    retry_users = [message["content"] for message in calls[1]["messages"] if message["role"] == "user"]
    assert EXTRACT_FIELD_RETRY_USER in retry_users


def test_extract_quote_and_invalid_source_do_not_field_retry(monkeypatch):
    calls = []

    class Counting(FakeHTTPClient):
        def post(self, url, json=None):
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Counting)
    client = EdgeClient("http://localhost:11434/v1", "edge-small")
    blocks = [{"id": "b1", "text": "纯模拟材料"}]

    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["b1"], "quote": "不是原文"}],
    })
    calls.clear()
    kept = client.extract(blocks)
    assert kept[0]["quote"] is None and kept[0]["value"] == "模拟事实"
    assert len(calls) == 1

    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["missing"]}],
    })
    calls.clear()
    with pytest.raises(ValueError, match="来源"):
        client.extract(blocks)
    assert len(calls) == 1


def test_extract_keeps_valid_source_when_mixed_with_invalid(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [
            {"field": "event", "value": "模拟事实", "source_ids": ["missing"]},
            {"field": "amount", "value": "12000元", "source_ids": ["b1"]},
        ],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert [fact["field"] for fact in result] == ["amount"]
    assert result[0]["quote"] == "12000元"


def test_extract_retargets_source_when_value_is_in_other_block(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "amount", "value": "12000元", "source_ids": ["b1"]}],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract([
        {"id": "b1", "text": "无关段落"},
        {"id": "b2", "text": "主张工资12000元"},
    ])
    assert result[0]["source_ids"] == ["b2"]
    assert result[0]["quote"] == "12000元"


def test_extract_repairs_quote_from_verbatim_value(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "amount", "value": "12000元", "source_ids": ["b1"], "quote": "不是原文"}],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert result[0]["quote"] == "12000元"


def test_extract_caps_events_and_keeps_other_fields(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [{"field": "event", "value": f"事件{i}", "source_ids": ["b1"]} for i in range(12)]
        + [{"field": "amount", "value": "12000元", "source_ids": ["b1"]}],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert sum(1 for fact in result if fact["field"] == "event") == extract_max_events()
    assert [fact["field"] for fact in result if fact["field"] != "event"] == ["amount"]


def test_extract_drops_overlong_events(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [
            {"field": "event", "value": "短事件", "source_ids": ["b1"]},
            {"field": "event", "value": "长" * 200, "source_ids": ["b1"]},
            {"field": "amount", "value": "12000元", "source_ids": ["b1"]},
        ],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元短事件" + ("长" * 200)}],
    )
    assert [fact["field"] for fact in result] == ["amount", "event"]
    assert result[1]["value"] == "短事件"


def test_extract_falls_back_to_json_object_when_json_schema_rejected(monkeypatch):
    calls = []

    class Fallback(FakeHTTPClient):
        content = json.dumps({
            "facts": [{"field": "event", "value": "模拟事实", "source_ids": ["b1"]}],
        })

        def post(self, url, json=None):
            calls.append(json)
            if json["response_format"].get("type") == "json_schema":
                return httpx.Response(400, json={"error": "unsupported response_format"}, request=httpx.Request("POST", url))
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Fallback)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "纯模拟材料"}],
    )
    assert result[0]["field"] == "event"
    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert calls[1]["temperature"] == 0
    assert calls[1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_extract_field_retry_uses_json_object_after_schema_fallback(monkeypatch):
    calls = []
    object_replies = [
        json.dumps({
            "facts": [{"field": "entity|relation|event|date|amount|evidence", "value": "应跳过", "source_ids": ["b1"]}],
        }),
        json.dumps({
            "facts": [{"field": "amount", "value": "12000元", "source_ids": ["b1"]}],
        }),
    ]

    class FallbackThenRetry(FakeHTTPClient):
        def post(self, url, json=None):
            calls.append(json)
            if json["response_format"].get("type") == "json_schema":
                return httpx.Response(400, json={"error": "unsupported response_format"}, request=httpx.Request("POST", url))
            self.content = object_replies[sum(1 for body in calls if body["response_format"].get("type") == "json_object") - 1]
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", FallbackThenRetry)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "主张工资12000元"}],
    )
    assert result[0]["field"] == "amount"
    assert [body["response_format"].get("type") for body in calls] == ["json_schema", "json_object", "json_object"]
    retry_users = [message["content"] for message in calls[2]["messages"] if message["role"] == "user"]
    assert EXTRACT_FIELD_RETRY_USER in retry_users


def test_edge_extract_strips_minicpm_think_blocks(monkeypatch):
    facts = {"facts": [{"field": "event", "value": "模拟事实", "source_ids": ["b1"]}]}
    FakeHTTPClient.content = "<think>内部推理</think>" + json.dumps(facts, ensure_ascii=False)
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "纯模拟材料"}],
    )
    assert result[0]["value"] == "模拟事实"


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
    monkeypatch.setattr(EdgeClient, "extract", lambda self, blocks, **kwargs: [{
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


def test_proposed_fact_accepts_legacy_json_and_rejects_empty_alias():
    legacy = ProposedFact.model_validate({"field": "entity", "value": "林甲", "source_ids": ["b1"]})
    assert legacy.aliases == [] and legacy.role == "unknown" and legacy.not_stated is False
    extended = ProposedFact.model_validate({
        "field": "entity", "value": "林甲", "source_ids": ["b1"],
        "aliases": ["小林"], "role": "劳动者", "normalized": None,
        "quote": "林甲", "not_stated": False, "conflict_group": "g1",
    })
    assert extended.aliases == ["小林"] and extended.role == "劳动者"
    with pytest.raises(ValueError, match="空串"):
        ProposedFact.model_validate({"field": "entity", "value": "林甲", "source_ids": ["b1"], "aliases": [""]})


def test_extract_unwraps_fact_list_and_sends_id_text_only(monkeypatch):
    captured = {}

    class Capturing(FakeHTTPClient):
        content = json.dumps([
            {"field": "entity", "value": "林甲", "source_ids": ["b1"]},
        ])

        def post(self, url, json=None):
            captured["body"] = json
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Capturing)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "劳动者林甲主张工资", "locator": "段落 1", "bbox": [0, 0, 1, 1]}],
    )
    assert result[0]["value"] == "林甲"
    assert json.loads(captured["body"]["messages"][1]["content"]) == [{"id": "b1", "text": "劳动者林甲主张工资"}]


def test_extract_unwraps_single_object_array_and_unknown_role(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps([{
        "facts": [{
            "field": "entity", "value": "林甲", "source_ids": ["b1"],
            "role": "劳动者|用人单位", "quote": "林甲",
        }],
    }])
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "劳动者林甲主张工资"}],
    )
    assert result[0]["value"] == "林甲" and result[0]["role"] == "unknown"


def test_extract_accepts_extended_fields_when_quote_is_substring(monkeypatch):
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    FakeHTTPClient.content = json.dumps({
        "facts": [{
            "field": "entity", "value": "林甲", "source_ids": ["b1"],
            "aliases": ["小林"], "role": "劳动者", "quote": "林甲",
        }],
    })
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "劳动者林甲主张工资"}],
    )
    assert result[0]["aliases"] == ["小林"] and result[0]["quote"] == "林甲"


def test_chunk_extract_blocks_does_not_stuff_one_batch():
    blocks = [{"id": str(i), "text": "字" * 2500} for i in range(6)]
    batches = chunk_extract_blocks(blocks)
    assert len(batches) >= 2
    assert all(sum(len(block["text"]) for block in batch) <= EXTRACT_CHUNK_CHARS or len(batch) == 1 for batch in batches)


def test_chunk_extract_blocks_caps_block_count():
    blocks = [{"id": str(i), "text": "短"} for i in range(20)]
    batches = chunk_extract_blocks(blocks)
    assert len(batches) >= 2
    assert all(len(batch) <= EXTRACT_CHUNK_BLOCKS for batch in batches)


def test_parse_extract_raw_treats_truncated_json_as_recoverable():
    unterminated = '{"facts":[{"field":"event","value":"' + ("x" * 200)
    with pytest.raises(ExtractTruncatedError, match="截断"):
        providers.parse_extract_raw(unterminated)
    long_broken = '{"facts":[' + ("null," * 50) + '{"field":'
    with pytest.raises(ExtractTruncatedError, match="截断"):
        providers.parse_extract_raw(long_broken)
    with pytest.raises(json.JSONDecodeError):
        providers.parse_extract_raw("not-json")


def test_extract_retries_truncated_json_by_splitting_batch(monkeypatch):
    truncated = '{"facts":[{"field":"event","value":"' + ("x" * 300)
    contents = [
        truncated,
        json.dumps({"facts": [{"field": "event", "value": "事实一", "source_ids": ["b1"]}]}),
        json.dumps({"facts": [{"field": "event", "value": "事实二", "source_ids": ["b2"]}]}),
    ]
    calls = []

    class Sequential(FakeHTTPClient):
        def post(self, url, json=None):
            self.content = contents[len(calls)]
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract([
        {"id": "b1", "text": "第一段模拟材料"},
        {"id": "b2", "text": "第二段模拟材料"},
    ])
    assert [fact["value"] for fact in result] == ["事实一", "事实二"]
    assert len(calls) == 3
    assert [json.loads(body["messages"][1]["content"])[0]["id"] for body in calls[1:]] == ["b1", "b2"]


def test_extract_truncated_single_block_raises(monkeypatch):
    FakeHTTPClient.content = '{"facts":[{"field":"event","value":"' + ("x" * 300)
    monkeypatch.setattr(providers.httpx, "Client", FakeHTTPClient)
    with pytest.raises(ExtractTruncatedError, match="单块"):
        EdgeClient("http://localhost:11434/v1", "edge-small").extract(
            [{"id": "b1", "text": "纯模拟材料"}],
        )


def test_extract_second_pass_waits_for_recovered_parse(monkeypatch):
    truncated = '{"facts":[{"field":"event","value":"' + ("x" * 300)
    first = json.dumps({"facts": [{"field": "entity", "value": "林甲", "source_ids": ["b1"]}]})
    refill = json.dumps({
        "facts": [{"field": "entity", "value": "林甲", "source_ids": ["b1"], "quote": "林甲", "role": "劳动者"}],
    })
    second = json.dumps({
        "facts": [{"field": "event", "value": "主张工资", "source_ids": ["b2"], "quote": "主张工资"}],
    })
    contents = [truncated, first, refill, second]
    calls = []

    class Sequential(FakeHTTPClient):
        def post(self, url, json=None):
            self.content = contents[len(calls)]
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [
            {"id": "b1", "text": "劳动者林甲主张工资"},
            {"id": "b2", "text": "主张工资"},
        ],
        second_pass=True,
    )
    assert [fact["value"] for fact in result] == ["林甲", "主张工资"]
    assert result[0]["quote"] == "林甲"
    assert len(calls) == 4
    assert EXTRACT_REFILL_USER not in [message["content"] for message in calls[0]["messages"] if message["role"] == "user"]
    assert EXTRACT_REFILL_USER in [message["content"] for message in calls[2]["messages"] if message["role"] == "user"]


def test_extract_job_chunks_large_block_set(env, monkeypatch):
    case, document, _ = formal_material(env)
    settings = env["client"].get("/api/v1/bootstrap").json()["settings"]
    body = {key: settings[key] for key in ("cloud_url", "cloud_model", "edge_url", "deployment_mode", "isolation_verified")}
    body["edge_model"] = "edge-small"
    assert env["client"].put("/api/v1/settings", json=body).status_code == 200
    calls = []

    def fake_extract(self, blocks, **kwargs):
        calls.append(sum(len(block.get("text") or "") for block in blocks))
        return [{
            "field": "event",
            "value": f"分块{len(calls)}",
            "source_ids": [blocks[0]["id"]],
            "suggested_transform": "keep",
            "disclosure_reason": "测试",
            "aliases": [],
            "role": "unknown",
            "normalized": None,
        }]

    monkeypatch.setattr(EdgeClient, "extract", fake_extract)
    with env["app"].state.store.transaction() as repo:
        doc = repo.get(document["id"], "document")
        base = doc["ir"]["blocks"][0]
        doc["ir"]["blocks"] = [{**base, "id": f"{document['id']}:v1:extra{i}", "text": "字" * 2500} for i in range(6)]
        repo.put("document", doc, case["id"])
        current = service.get_case(repo, case["id"])
        service.queue_job(repo, case["id"], "extract", {"revision": current["revision"], "blocks": doc["ir"]["blocks"]})
    process_one(env["app"].state.store, env["root"], env["gate"])
    assert len(calls) >= 2
    assert all(size <= EXTRACT_CHUNK_CHARS or size == 2500 for size in calls)
    detail = env["client"].get(f"/api/v1/cases/{case['id']}").json()
    assert any(fact["value"].startswith("分块") for fact in detail["facts"])


def test_extract_job_keeps_later_batches_when_one_fails(env, monkeypatch):
    case, document, _ = formal_material(env)
    settings = env["client"].get("/api/v1/bootstrap").json()["settings"]
    body = {key: settings[key] for key in ("cloud_url", "cloud_model", "edge_url", "deployment_mode", "isolation_verified")}
    body["edge_model"] = "edge-small"
    assert env["client"].put("/api/v1/settings", json=body).status_code == 200
    calls = []

    def fake_extract(self, blocks, **kwargs):
        calls.append(len(blocks))
        if len(calls) == 1:
            raise ValueError("边侧模型未返回任何合法 field 的事实")
        return [{
            "field": "event",
            "value": f"分块{len(calls)}",
            "source_ids": [blocks[0]["id"]],
            "suggested_transform": "keep",
            "disclosure_reason": "测试",
            "aliases": [],
            "role": "unknown",
            "normalized": None,
        }]

    monkeypatch.setattr(EdgeClient, "extract", fake_extract)
    with env["app"].state.store.transaction() as repo:
        doc = repo.get(document["id"], "document")
        base = doc["ir"]["blocks"][0]
        doc["ir"]["blocks"] = [{**base, "id": f"{document['id']}:v1:extra{i}", "text": "短"} for i in range(20)]
        repo.put("document", doc, case["id"])
        current = service.get_case(repo, case["id"])
        service.queue_job(repo, case["id"], "extract", {"revision": current["revision"], "blocks": doc["ir"]["blocks"]})
    process_one(env["app"].state.store, env["root"], env["gate"])
    assert len(calls) >= 2
    detail = env["client"].get(f"/api/v1/cases/{case['id']}").json()
    assert any(fact["value"].startswith("分块") for fact in detail["facts"])


def test_extract_persists_aliases_on_fact(env, monkeypatch):
    case, _, _ = formal_material(env)
    settings = env["client"].get("/api/v1/bootstrap").json()["settings"]
    body = {key: settings[key] for key in ("cloud_url", "cloud_model", "edge_url", "deployment_mode", "isolation_verified")}
    body["edge_model"] = "edge-small"
    assert env["client"].put("/api/v1/settings", json=body).status_code == 200
    monkeypatch.setattr(EdgeClient, "extract", lambda self, blocks, **kwargs: [{
        "field": "entity",
        "value": "林甲",
        "source_ids": [blocks[0]["id"]],
        "suggested_transform": "pseudonymize",
        "disclosure_reason": "测试",
        "aliases": ["小林"],
        "role": "劳动者",
        "normalized": None,
        "quote": "林甲",
    }])
    queued = env["client"].post(f"/api/v1/cases/{case['id']}/extract")
    assert queued.status_code == 200
    process_one(env["app"].state.store, env["root"], env["gate"])
    entity = next(fact for fact in env["client"].get(f"/api/v1/cases/{case['id']}").json()["facts"] if fact["value"] == "林甲")
    assert entity["confirmed"] is False
    assert entity["aliases"] == ["小林"] and entity["role"] == "劳动者"
    assert entity["model_suggestion"]["aliases"] == ["小林"]


def test_doctor_edge_json_failure_is_not_fatal(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_MODEL", "edge-small")
    monkeypatch.setenv("LEX_EDGE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(EdgeClient, "health", lambda self: {"status": "available", "detail": "ok"})
    monkeypatch.setattr(EdgeClient, "extract", lambda self, blocks, timeout=8: (_ for _ in ()).throw(RuntimeError("down")))
    report = diagnostics.doctor_report()
    assert report["checks"]["edge_json"]["ok"] is False
    required = {key: item for key, item in report["checks"].items() if key not in ("edge_model", "edge_json", "isolation", "ocr")}
    assert report["ok"] == all(item["ok"] for item in required.values())


def test_doctor_edge_json_unconfigured_when_server_down(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_MODEL", "edge-small")
    monkeypatch.setenv("LEX_EDGE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(EdgeClient, "health", lambda self: {"status": "failed", "detail": "无法连接边侧模型服务"})
    report = diagnostics.doctor_report()
    assert report["checks"]["edge_json"]["status"] == "unconfigured"
    assert report["checks"]["edge_json"]["ok"] is True
    assert report["ok"] is True


def test_merge_extract_facts_unions_aliases_and_sources():
    merged = merge_extract_facts([
        {"field": "entity", "value": "林甲", "source_ids": ["b1"], "aliases": ["小林"], "role": "unknown", "quote": None},
        {"field": "entity", "value": "林甲", "source_ids": ["b2"], "aliases": ["甲"], "role": "劳动者", "quote": "林甲"},
        {"field": "amount", "value": "12000元", "source_ids": ["b1"], "aliases": []},
    ])
    entity = next(item for item in merged if item["field"] == "entity")
    assert entity["source_ids"] == ["b1", "b2"]
    assert entity["aliases"] == ["小林", "甲"]
    assert entity["role"] == "劳动者"
    assert entity["quote"] == "林甲"
    assert len(merged) == 2


def test_extract_keeps_first_pass_when_refill_truncates(monkeypatch):
    first = json.dumps({"facts": [{"field": "entity", "value": "林甲", "source_ids": ["b1"]}]})
    truncated = '{"facts":[{"field":"event","value":"' + ("x" * 300)
    contents = [first, truncated]
    calls = []

    class Sequential(FakeHTTPClient):
        def post(self, url, json=None):
            self.content = contents[len(calls)]
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "劳动者林甲主张工资"}],
        second_pass=True,
    )
    assert result[0]["value"] == "林甲"
    assert result[0]["quote"] == "林甲"
    assert len(calls) == 2


def test_extract_second_pass_fills_missing_quote(monkeypatch):
    calls = []
    first = json.dumps({"facts": [{"field": "entity", "value": "林甲", "source_ids": ["b1"]}]})
    second = json.dumps({
        "facts": [{"field": "entity", "value": "林甲", "source_ids": ["b1"], "quote": "林甲", "role": "劳动者"}],
    })

    class Sequential(FakeHTTPClient):
        contents = [first, second]

        def post(self, url, json=None):
            self.content = self.contents[len(calls)]
            calls.append(json)
            return super().post(url, json=json)

    monkeypatch.setattr(providers.httpx, "Client", Sequential)
    monkeypatch.setenv("LEX_EDGE_SECOND_PASS_THINKING", "1")
    result = EdgeClient("http://localhost:11434/v1", "edge-small").extract(
        [{"id": "b1", "text": "劳动者林甲主张工资"}],
        second_pass=True,
    )
    assert result[0]["quote"] == "林甲"
    assert result[0]["role"] == "劳动者"
    assert len(calls) == 2
    assert EXTRACT_REFILL_USER in [message["content"] for message in calls[1]["messages"] if message["role"] == "user"]
    assert calls[1]["chat_template_kwargs"]["enable_thinking"] is True
    assert facts_need_refill([{"field": "entity", "value": "林甲", "source_ids": ["b1"]}]) is True


def test_doctor_skips_edge_json_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    report = diagnostics.doctor_report()
    assert report["checks"]["edge_json"]["status"] == "unconfigured"
    assert report["checks"]["edge_json"]["ok"] is True
