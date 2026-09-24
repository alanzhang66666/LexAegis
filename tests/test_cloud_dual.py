import json

import httpx
import pytest
from fastapi.testclient import TestClient

from lexaegis import launcher
from lexaegis.cloud import (
    DEFAULT_CLOUD_HOSTS,
    DualSlotProvider,
    allowed_cloud_hosts,
    approved_dual_slot,
    assemble_chat_completion,
    standby_host,
    wire_contract_error,
)
from lexaegis.gateway import create_gateway
from lexaegis.worker import process_one
from .conftest import approve, demo_task
from .test_workflow import task_state


def _claims(text="[[LEX:P0001]]", source="f1"):
    return {"claims": [{"text": text, "source_ids": [source]}]}


def _sse(payload, usage=None, reasoning=None):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    lines = []
    if reasoning:
        lines.append("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": reasoning}}]}) + "\n")
    for index in range(0, len(content), 8):
        lines.append("data: " + json.dumps({"choices": [{"delta": {"content": content[index:index + 8]}}]}) + "\n")
    if usage:
        lines.append("data: " + json.dumps({"choices": [], "usage": usage}) + "\n")
    lines.append("data: [DONE]\n")
    return httpx.Response(200, content="".join(lines), headers={"content-type": "text/event-stream"})


class ScriptedTransport(httpx.BaseTransport):
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []
        self.bodies = []

    def handle_request(self, request):
        self.calls.append(str(request.url))
        self.bodies.append(json.loads(request.content.decode()) if request.content else {})
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        if callable(script):
            return script(request)
        return script


class InterruptAfterContent:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"{\\"claims\\":"}}]}'
        raise httpx.ReadError("cut")


class InterruptClient:
    def stream(self, *args, **kwargs):
        return InterruptAfterContent()


class TimeoutAfterAccept:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def iter_lines(self):
        raise httpx.ReadTimeout("first byte")

    def read(self):
        raise httpx.ReadTimeout("first byte")


class TimeoutAfterAcceptClient:
    def stream(self, *args, **kwargs):
        return TimeoutAfterAccept()


def _provider(*scripts, primary="primary-key", standby="standby-key"):
    transport = ScriptedTransport(scripts)
    client = httpx.Client(transport=transport, timeout=5, follow_redirects=False, trust_env=False)
    return DualSlotProvider(primary, standby, client=client), transport


def _send_cloud(env, provider, label):
    gateway_app = create_gateway(env["temp"] / label, secret="unit-test-secret-32-characters-long", provider=provider)
    gateway = TestClient(gateway_app)
    env["client"].put("/api/v1/settings", json={
        "cloud_url": "https://api.openai.com/v1", "cloud_model": "test-model",
        "edge_url": "http://localhost:11434/v1", "edge_model": "",
    })
    case, task = demo_task(env, transport="cloud")
    task = approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    process_one(env["app"].state.store, env["root"], gateway)
    with gateway_app.state.store.read() as repo:
        record = repo.get(task["request"]["request_id"], "send")
    return case, task, record


def test_default_allowlist_includes_dual_hosts():
    assert {"api.deepseek.com", "dashscope.aliyuncs.com"} <= allowed_cloud_hosts()
    assert "api.deepseek.com" in DEFAULT_CLOUD_HOSTS


def test_standby_accepts_allowlisted_maas_host(monkeypatch):
    host = "workspace.cn-beijing.maas.aliyuncs.com"
    monkeypatch.setenv("LEX_CLOUD_STANDBY_HOST", host)
    monkeypatch.setenv("LEX_CLOUD_ALLOWED_HOSTS", f"api.deepseek.com,{host}")
    assert standby_host() == host
    assert approved_dual_slot()["standby"]["target"] == f"https://{host}/compatible-mode/v1/chat/completions"


def test_standby_rejects_unlisted_or_non_maas_host(monkeypatch):
    monkeypatch.setenv("LEX_CLOUD_STANDBY_HOST", "evil.example.com")
    monkeypatch.setenv("LEX_CLOUD_ALLOWED_HOSTS", "api.deepseek.com,evil.example.com")
    assert standby_host() == "dashscope.aliyuncs.com"
    monkeypatch.setenv("LEX_CLOUD_STANDBY_HOST", "workspace.cn-beijing.maas.aliyuncs.com")
    monkeypatch.delenv("LEX_CLOUD_ALLOWED_HOSTS", raising=False)
    assert standby_host() == "dashscope.aliyuncs.com"


def test_wire_allows_field_but_rejects_local_keys():
    wire = {"contract_version": 2, "task": {"id": "fact_summary", "version": "2.0"},
            "facts": [{"id": "f1", "text": "[[LEX:P0001]]", "field": "entity"}]}
    assert wire_contract_error(wire) is None
    leaked = {"contract_version": 2, "task": {"id": "fact_summary", "version": "2.0"},
              "facts": [{"id": "f1", "text": "x", "mapping": {"a": "b"}}]}
    assert wire_contract_error(leaked)


def test_pre_generation_401_does_not_expand_recipients():
    claims = _claims()
    provider, transport = _provider(httpx.Response(401, json={"error": "no"}), _sse(claims))
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {
        "model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "{}"}],
    }, dual_slot=provider_slot())
    assert outcome.status == "unknown"
    assert outcome.selected_slot == "primary"
    assert outcome.disclosure_state == "possible"
    assert outcome.generation_started is False
    assert len(transport.calls) == 1
    assert "deepseek" in transport.calls[0]
    assert transport.bodies[0].get("thinking") == {"type": "disabled"}
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0]["disclosure_state"] == "possible"


def test_connect_failure_failsover_before_generation():
    claims = _claims()
    provider, transport = _provider(httpx.ConnectError("refused"), _sse(claims))
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []}, dual_slot=provider_slot())
    assert outcome.status == "complete" and outcome.selected_slot == "standby"
    assert outcome.attempts[0]["disclosure_state"] == "undisclosed"
    assert len(transport.calls) == 2


def test_unapproved_standby_is_not_invented_on_connect_failure():
    claims = _claims()
    provider, transport = _provider(httpx.ConnectError("refused"), _sse(claims))
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []})
    assert outcome.status == "unknown"
    assert outcome.selected_slot == "primary"
    assert outcome.disclosure_state == "undisclosed"
    assert len(transport.calls) == 1


def test_generation_started_does_not_call_standby():
    provider, transport = _provider(_sse("{", reasoning="scratch"), _sse(_claims()))
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []})
    assert outcome.status == "unknown"
    assert outcome.generation_started is True
    assert outcome.selected_slot == "primary"
    assert len(transport.calls) == 1


def test_invalid_json_does_not_failover():
    provider, transport = _provider(_sse("{not-json"), _sse(_claims()))
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []})
    assert outcome.status == "unknown"
    assert outcome.generation_started is True
    assert len(transport.calls) == 1


def test_stream_interrupt_after_tokens_is_unknown():
    provider = DualSlotProvider("primary-key", "standby-key", client=InterruptClient())
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []}, dual_slot=provider_slot())
    assert outcome.status == "unknown"
    assert outcome.generation_started is True
    assert outcome.selected_slot == "primary"
    assert outcome.disclosure_state == "possible"


def test_timeout_after_primary_accepts_body_does_not_failover():
    provider = DualSlotProvider("primary-key", "standby-key", client=TimeoutAfterAcceptClient())
    persisted = []

    def persist(attempts, authorized):
        persisted.append((list(attempts), list(authorized)))

    outcome = provider.dispatch(
        "https://api.deepseek.com/v1/chat/completions",
        {"model": "deepseek-v4-flash", "messages": []},
        dual_slot=provider_slot(),
        persist_attempt=persist,
    )
    assert outcome.status == "unknown"
    assert outcome.selected_slot == "primary"
    assert outcome.generation_started is False
    assert outcome.disclosure_state == "possible"
    assert outcome.attempts[0]["transmission_state"] == "response_received"
    assert persisted[0][0][0]["finished_at"] is None
    assert persisted[-1][0][0]["disclosure_state"] == "possible"
    assert [item["slot"] for item in persisted[0][1]] == ["primary", "standby"]


def test_usage_is_copied_to_outcome():
    usage = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
    provider, _ = _provider(_sse(_claims(), usage=usage), standby="")
    outcome = provider.dispatch("https://api.deepseek.com/v1/chat/completions", {"model": "deepseek-v4-flash", "messages": []})
    assert outcome.status == "complete"
    assert outcome.ledger_fields()["total_tokens"] == 8


def test_assemble_does_not_keep_reasoning_content():
    claims = _claims()
    provider, _ = _provider(_sse(claims, reasoning="内部思考"), standby="")
    result, started, _ = assemble_chat_completion(
        "https://api.deepseek.com/v1/chat/completions",
        {"model": "deepseek-v4-flash", "messages": []},
        "primary-key",
        client=provider._client,
    )
    assert started is True
    assert result == claims


def test_gateway_server_error_does_not_hit_standby(integration_env):
    env = integration_env
    provider, transport = _provider(httpx.Response(401, json={"error": "no"}), _sse(_claims()))
    case, task, record = _send_cloud(env, provider, "gw-unauthorized")
    assert record["status"] == "unknown"
    assert record["selected_slot"] == "primary"
    assert record["disclosure_state"] == "possible"
    assert record["result"] is None
    assert record["attempts"]
    assert record["attempts"][0]["disclosure_state"] == "possible"
    assert "mapping" not in json.dumps(record)
    assert task_state(env, case["id"], task["id"])["status"] == "unknown"
    assert len(transport.calls) == 1


def test_gateway_unknown_after_content_does_not_hit_standby(integration_env):
    env = integration_env
    provider, transport = _provider(_sse("{broken"), _sse(_claims()))
    case, task, record = _send_cloud(env, provider, "gw-broken-json")
    assert record["status"] == "unknown"
    assert record["generation_started"] is True
    assert record["selected_slot"] == "primary"
    assert record["result"] is None
    assert len(transport.calls) == 1
    assert task_state(env, case["id"], task["id"])["status"] == "unknown"


def test_mock_demo_path_unchanged(demo_env):
    env = demo_env
    case, task = demo_task(env)
    task = approve(env, task)
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/send").status_code == 200
    assert process_one(env["app"].state.store, env["root"], env["gate"])
    finished = task_state(env, case["id"], task["id"])
    assert finished["status"] == "complete"
    assert finished["artifact"]["provenance"] == "simulation"


def test_launcher_service_ports_follow_env(monkeypatch):
    monkeypatch.setenv("LEX_API_PORT", "18765")
    monkeypatch.setenv("LEX_GATEWAY_PORT", "18766")
    assert launcher.service_ports() == ("18765", "18766")


def test_align_local_gateway_url_rewrites_loopback_port_mismatch():
    assert launcher.align_local_gateway_url("http://127.0.0.1:8766", "18766") == "http://127.0.0.1:18766"
    assert launcher.align_local_gateway_url("http://localhost:8766", "18766") == "http://localhost:18766"
    assert launcher.align_local_gateway_url("http://127.0.0.1:18766", "18766") == "http://127.0.0.1:18766"
    assert launcher.align_local_gateway_url("http://[::1]:8766", "18766") == "http://[::1]:18766"
    assert launcher.align_local_gateway_url(None, "8766") == "http://127.0.0.1:8766"
    assert launcher.align_local_gateway_url("https://gateway.example.com:8766", "18766") == "https://gateway.example.com:8766"


def test_launcher_strips_cloud_keys_from_api_env():
    env = {
        "PATH": "/bin", "LEX_GATEWAY_SECRET": "gate",
        "LEX_CLOUD_API_KEY": "legacy", "LEX_CLOUD_PRIMARY_KEY": "primary", "LEX_CLOUD_STANDBY_KEY": "standby",
    }
    stripped = launcher.app_process_env(env)
    assert stripped["LEX_GATEWAY_SECRET"] == "gate"
    assert "LEX_CLOUD_API_KEY" not in stripped
    assert "LEX_CLOUD_PRIMARY_KEY" not in stripped
    assert "LEX_CLOUD_STANDBY_KEY" not in stripped


def test_launcher_strips_local_password_from_gateway_env():
    env = {
        "PATH": "/bin", "LEX_LOCAL_PASSWORD": "local", "LEX_EDGE_MODEL": "edge-small",
        "LEX_EDGE_URL": "http://127.0.0.1:8080/v1", "LEX_CLOUD_PRIMARY_KEY": "primary",
    }
    gateway_env = {key: value for key, value in env.items()
                   if key not in ("LEX_LOCAL_PASSWORD", "LEX_EDGE_MODEL", "LEX_EDGE_URL")}
    assert "LEX_LOCAL_PASSWORD" not in gateway_env
    assert gateway_env["LEX_CLOUD_PRIMARY_KEY"] == "primary"


def test_api_bind_host_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("LEX_BIND_HOST", raising=False)
    assert launcher.api_bind_host() == "127.0.0.1"
    monkeypatch.setenv("LEX_BIND_HOST", "   ")
    assert launcher.api_bind_host() == "127.0.0.1"


def test_api_bind_host_accepts_ip_literals(monkeypatch):
    monkeypatch.setenv("LEX_BIND_HOST", "0.0.0.0")
    assert launcher.api_bind_host() == "0.0.0.0"
    monkeypatch.setenv("LEX_BIND_HOST", " 127.0.0.1 ")
    assert launcher.api_bind_host() == "127.0.0.1"


def test_api_bind_host_rejects_hostnames(monkeypatch):
    for value in ("localhost", "0.0.0.0:8765", "example.com", "not-an-ip"):
        monkeypatch.setenv("LEX_BIND_HOST", value)
        with pytest.raises(SystemExit):
            launcher.api_bind_host()


def test_bind_host_is_loopback():
    assert launcher.bind_host_is_loopback("127.0.0.1")
    assert launcher.bind_host_is_loopback("::1")
    assert not launcher.bind_host_is_loopback("0.0.0.0")
    assert not launcher.bind_host_is_loopback("localhost")


def test_service_commands_keep_gateway_on_loopback():
    gateway_command, api_command = launcher.service_commands("8765", "8766", "0.0.0.0")
    assert gateway_command[gateway_command.index("--host") + 1] == "127.0.0.1"
    assert gateway_command[gateway_command.index("--port") + 1] == "8766"
    assert "lexaegis.gateway:create_gateway" in gateway_command
    assert api_command[api_command.index("--host") + 1] == "0.0.0.0"
    assert api_command[api_command.index("--port") + 1] == "8765"
    assert "lexaegis.api:create_app" in api_command


def test_service_commands_default_bind_host_is_loopback():
    gateway_command, api_command = launcher.service_commands("18765", "18766", launcher.DEFAULT_BIND_HOST)
    assert gateway_command[gateway_command.index("--host") + 1] == "127.0.0.1"
    assert api_command[api_command.index("--host") + 1] == "127.0.0.1"


def provider_slot():
    return {
        "primary": {"host": "api.deepseek.com", "target": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-v4-flash"},
        "standby": {"host": "dashscope.aliyuncs.com", "target": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen3.8-flash"},
    }
