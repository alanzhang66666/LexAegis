"""Gateway-only cloud slots. Stream tokens are assembled here, never forwarded to the workbench."""
import json
import os
import time
from urllib.parse import urlparse

import httpx

DEFAULT_CLOUD_HOSTS = "api.deepseek.com,dashscope.aliyuncs.com,dashscope-intl.aliyuncs.com,api.openai.com"
PRIMARY_HOST = "api.deepseek.com"
PRIMARY_TARGET = "https://api.deepseek.com/v1/chat/completions"
PRIMARY_MODEL = "deepseek-v4-flash"
STANDBY_HOSTS = ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com")
STANDBY_MODEL = "qwen3.8-flash"
MAAS_HOST_SUFFIX = ".maas.aliyuncs.com"
LOCAL_WIRE_KEYS = ("mapping", "original_value", "local_text", "anchors")
FACT_WIRE_KEYS = {"id", "text", "field"}
_BODY_KEYS = ("model", "messages", "temperature", "response_format")


class PreGenerationError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class GenerationUnknownError(Exception):
    def __init__(self, reason, *, slot=None, generation_started=True):
        self.reason = reason
        self.slot = slot
        self.generation_started = generation_started
        super().__init__(reason)


def primary_key_from_env():
    return os.getenv("LEX_CLOUD_PRIMARY_KEY") or os.getenv("LEX_CLOUD_API_KEY") or ""


def standby_key_from_env():
    return os.getenv("LEX_CLOUD_STANDBY_KEY") or ""


def _standby_host_permitted(host):
    if not host or "/" in host or ":" in host or host.startswith("."):
        return False
    if host in STANDBY_HOSTS:
        return True
    return host.endswith(MAAS_HOST_SUFFIX) and host in allowed_cloud_hosts()


def standby_host():
    host = (os.getenv("LEX_CLOUD_STANDBY_HOST") or STANDBY_HOSTS[0]).strip().lower()
    return host if _standby_host_permitted(host) else STANDBY_HOSTS[0]


def approved_dual_slot():
    host = standby_host()
    return {
        "primary": {"host": PRIMARY_HOST, "target": PRIMARY_TARGET, "model": PRIMARY_MODEL},
        "standby": {"host": host, "target": f"https://{host}/compatible-mode/v1/chat/completions", "model": STANDBY_MODEL},
        "thinking": "disabled",
        "failover": "pre_generation_only",
    }


def allowed_cloud_hosts():
    return {item.strip() for item in os.getenv("LEX_CLOUD_ALLOWED_HOSTS", DEFAULT_CLOUD_HOSTS).split(",") if item.strip()}


def cloud_endpoint_allowed(target):
    url = urlparse(target)
    return (
        url.scheme == "https"
        and url.hostname in allowed_cloud_hosts()
        and not url.username and not url.password and not url.query and not url.fragment
        and url.port in (None, 443)
        and url.path.endswith("/chat/completions")
    )


def wire_contract_error(wire):
    if not isinstance(wire, dict) or set(wire) != {"contract_version", "task", "facts"} or wire.get("contract_version") != 2:
        return "Invalid cloud wire contract"
    if any(key in str(wire).lower() for key in LOCAL_WIRE_KEYS):
        return "Local-only fields are forbidden on the wire"
    facts = wire.get("facts")
    if not isinstance(facts, list):
        return "Invalid cloud wire contract"
    for item in facts:
        if not isinstance(item, dict) or not {"id", "text"} <= set(item) or not set(item) <= FACT_WIRE_KEYS:
            return "Local-only fields are forbidden on the wire"
        if any(key in item for key in LOCAL_WIRE_KEYS):
            return "Local-only fields are forbidden on the wire"
    return None


def _http_reason(status):
    if status in (401, 403):
        return "unauthorized" if status == 401 else "forbidden"
    if status in (408, 429):
        return "timeout" if status == 408 else "rate_limited"
    if status >= 500:
        return "server_error"
    return "http_error"


def _slot_body(body, slot):
    clean = {key: body[key] for key in _BODY_KEYS if key in body}
    clean["model"] = slot["model"]
    clean["temperature"] = 0
    clean["response_format"] = {"type": "json_object"}
    clean["stream"] = True
    if slot.get("host") == PRIMARY_HOST or "deepseek" in (slot.get("host") or ""):
        clean["thinking"] = {"type": "disabled"}
    clean.pop("enable_thinking", None)
    return clean


def _delta_parts(event):
    choices = event.get("choices") if isinstance(event, dict) else None
    if not isinstance(choices, list) or not choices:
        return "", ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = delta.get("content") or message.get("content") or ""
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or message.get("reasoning_content") or ""
    return content if isinstance(content, str) else "", reasoning if isinstance(reasoning, str) else ""


def assemble_chat_completion(target, body, api_key, *, client=None, timeout=90):
    if not api_key:
        raise PreGenerationError("unconfigured")
    payload = _slot_body(body, {"host": urlparse(target).hostname or "", "model": body.get("model") or PRIMARY_MODEL})
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream"}
    close = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)
        close = True
    started = False
    parts = []
    usage = None
    try:
        try:
            with client.stream("POST", target, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    raise PreGenerationError(_http_reason(response.status_code))
                leftover = []
                saw_sse = False
                for line in response.iter_lines():
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    if not line:
                        continue
                    if line.startswith("data:"):
                        saw_sse = True
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            if started:
                                raise GenerationUnknownError("invalid_sse", generation_started=True)
                            leftover.append(line)
                            continue
                        content, reasoning = _delta_parts(event)
                        if content or reasoning:
                            started = True
                        if content:
                            parts.append(content)
                        if isinstance(event, dict) and event.get("usage"):
                            usage = event["usage"]
                    elif not saw_sse:
                        leftover.append(line)
                if not saw_sse:
                    raw = "\n".join(leftover).strip()
                    if not raw:
                        raw = response.read().decode("utf-8", errors="replace") if hasattr(response, "read") else ""
                    if not raw:
                        raise PreGenerationError("empty")
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError as error:
                        raise PreGenerationError("invalid_json") from error
                    message = (((parsed.get("choices") or [{}])[0] or {}).get("message") or {})
                    content = message.get("content") or ""
                    reasoning = message.get("reasoning_content") or ""
                    if content or reasoning:
                        started = True
                    usage = parsed.get("usage") or usage
                    if not content:
                        raise PreGenerationError("empty")
                    try:
                        return json.loads(content), started, usage
                    except json.JSONDecodeError as error:
                        raise GenerationUnknownError("invalid_json", generation_started=True) from error
        except GenerationUnknownError:
            raise
        except PreGenerationError:
            raise
        except httpx.TimeoutException as error:
            if started:
                raise GenerationUnknownError("timeout", generation_started=True) from error
            raise PreGenerationError("timeout") from error
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise PreGenerationError("connect") from error
        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.NetworkError) as error:
            if started:
                raise GenerationUnknownError("stream_interrupted", generation_started=True) from error
            raise PreGenerationError("connect") from error
        except httpx.HTTPError as error:
            if started:
                raise GenerationUnknownError("http_error", generation_started=True) from error
            raise PreGenerationError("http_error") from error
        assembled = "".join(parts)
        if not assembled:
            raise PreGenerationError("empty")
        try:
            return json.loads(assembled), started, usage
        except json.JSONDecodeError as error:
            raise GenerationUnknownError("invalid_json", generation_started=True) from error
    finally:
        if close:
            client.close()


class DispatchOutcome:
    def __init__(self, status, result=None, error=None, selected_slot=None, failover_reason=None,
                 generation_started=False, usage=None, duration_ms=None):
        self.status = status
        self.result = result
        self.error = error
        self.selected_slot = selected_slot
        self.failover_reason = failover_reason
        self.generation_started = generation_started
        self.usage = usage if isinstance(usage, dict) else None
        self.duration_ms = duration_ms

    def ledger_fields(self):
        fields = {
            "selected_slot": self.selected_slot,
            "failover_reason": self.failover_reason,
            "generation_started": self.generation_started,
        }
        if self.usage:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if key in self.usage:
                    fields[key] = self.usage[key]
        if self.duration_ms is not None:
            fields["duration_ms"] = self.duration_ms
        return fields


class DualSlotProvider:
    def __init__(self, primary_key=None, standby_key=None, client=None):
        self.primary_key = primary_key if primary_key is not None else primary_key_from_env()
        self.standby_key = standby_key if standby_key is not None else standby_key_from_env()
        self._client = client

    @classmethod
    def from_env(cls):
        return cls()

    @property
    def api_key(self):
        return self.primary_key

    def send(self, target, body, dual_slot=None):
        outcome = self.dispatch(target, body, dual_slot=dual_slot)
        if outcome.status == "complete":
            return outcome.result
        raise RuntimeError(outcome.error or "cloud_dispatch_failed")

    def dispatch(self, target, body, dual_slot=None):
        slots = dual_slot if isinstance(dual_slot, dict) else {}
        primary = dict(slots.get("primary") or {"host": PRIMARY_HOST, "target": target or PRIMARY_TARGET, "model": (body or {}).get("model") or PRIMARY_MODEL})
        standby = dict(slots.get("standby") or approved_dual_slot()["standby"])
        primary.setdefault("target", target or PRIMARY_TARGET)
        started_at = time.perf_counter()
        if not self.primary_key:
            return DispatchOutcome("failed", error="云端密钥未配置", selected_slot="primary", duration_ms=_elapsed_ms(started_at))
        first = self._attempt(primary, body, self.primary_key, "primary")
        first.duration_ms = _elapsed_ms(started_at)
        if first.status == "complete" or first.generation_started:
            if first.status != "complete":
                first.status = "unknown"
                first.error = first.error or "调用后结果不明；禁止自动重发，请核对服务商记录"
            return first
        if not self.standby_key:
            first.status = "unknown"
            first.error = first.error or "调用后结果不明；禁止自动重发，请核对服务商记录"
            return first
        second = self._attempt(standby, body, self.standby_key, "standby")
        second.failover_reason = first.error or "primary_unavailable"
        second.duration_ms = _elapsed_ms(started_at)
        if second.status != "complete":
            second.status = "unknown"
            second.error = second.error or "调用后结果不明；禁止自动重发，请核对服务商记录"
        return second

    def _attempt(self, slot, body, key, name):
        target = slot.get("target") or ""
        request_body = dict(body or {})
        request_body["model"] = slot.get("model") or request_body.get("model") or PRIMARY_MODEL
        try:
            result, started, usage = assemble_chat_completion(target, request_body, key, client=self._client)
            if not isinstance(result, dict):
                return DispatchOutcome("unknown", error="invalid_json", selected_slot=name, generation_started=True, usage=usage)
            return DispatchOutcome("complete", result=result, selected_slot=name, generation_started=started, usage=usage)
        except GenerationUnknownError as error:
            return DispatchOutcome("unknown", error=error.reason, selected_slot=name, generation_started=True)
        except PreGenerationError as error:
            return DispatchOutcome("unknown", error=error.reason, selected_slot=name, generation_started=False)


def _elapsed_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)
