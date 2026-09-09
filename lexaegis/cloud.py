"""Gateway-only cloud slots. Stream tokens are assembled here, never forwarded to the workbench."""
import json
import os
import time
from urllib.parse import urlparse

import httpx

from .util import digest, now, uid

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
    def __init__(self, reason, *, left_local=False):
        self.reason = reason
        self.left_local = left_local
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
    """Default host catalog only. Do not use this to invent an unreviewed standby."""
    host = standby_host()
    return {
        "primary": {"host": PRIMARY_HOST, "target": PRIMARY_TARGET, "model": PRIMARY_MODEL},
        "standby": {"host": host, "target": f"https://{host}/compatible-mode/v1/chat/completions", "model": STANDBY_MODEL},
        "thinking": "disabled",
        "failover": "local_undisclosed_only",
    }


def chat_completions_target(url):
    if not url or not isinstance(url, str):
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path or ""
    if not path.endswith("/chat/completions"):
        path = path.rstrip("/") + "/chat/completions"
    host = parsed.hostname
    netloc = host if parsed.port in (None, 443) else f"{host}:{parsed.port}"
    target = f"https://{netloc}{path}"
    return target if cloud_endpoint_allowed(target) else None


def build_dispatch_slot(url, model, *, provider_id=None, role="primary"):
    target = chat_completions_target(url)
    if not target or not str(model or "").strip():
        return None
    return {
        "host": urlparse(target).hostname or "",
        "target": target,
        "model": str(model).strip(),
        "provider_id": provider_id or None,
        "role": role,
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


_CONNECT_FAILURES = (httpx.ConnectError, httpx.ConnectTimeout) + (
    (httpx.PoolTimeout,) if hasattr(httpx, "PoolTimeout") else ()
)


def assemble_chat_completion(target, body, api_key, *, client=None, timeout=90):
    if not api_key:
        raise PreGenerationError("unconfigured", left_local=False)
    payload = _slot_body(body, {"host": urlparse(target).hostname or "", "model": body.get("model") or PRIMARY_MODEL})
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream"}
    close = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)
        close = True
    started = False
    got_response = False
    parts = []
    usage = None
    try:
        try:
            with client.stream("POST", target, json=payload, headers=headers) as response:
                got_response = True
                if response.status_code >= 400:
                    raise PreGenerationError(_http_reason(response.status_code), left_local=True)
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
                        raise PreGenerationError("empty", left_local=True)
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError as error:
                        raise PreGenerationError("invalid_json", left_local=True) from error
                    message = (((parsed.get("choices") or [{}])[0] or {}).get("message") or {})
                    content = message.get("content") or ""
                    reasoning = message.get("reasoning_content") or ""
                    if content or reasoning:
                        started = True
                    usage = parsed.get("usage") or usage
                    if not content:
                        raise PreGenerationError("empty", left_local=True)
                    try:
                        return json.loads(content), started, usage
                    except json.JSONDecodeError as error:
                        raise GenerationUnknownError("invalid_json", generation_started=True) from error
        except GenerationUnknownError:
            raise
        except PreGenerationError:
            raise
        except _CONNECT_FAILURES as error:
            raise PreGenerationError("connect", left_local=False) from error
        except httpx.TimeoutException as error:
            if started:
                raise GenerationUnknownError("timeout", generation_started=True) from error
            raise PreGenerationError("timeout", left_local=True) from error
        except (httpx.ReadError, httpx.RemoteProtocolError) as error:
            if started:
                raise GenerationUnknownError("stream_interrupted", generation_started=True) from error
            raise PreGenerationError("connect", left_local=got_response or True) from error
        except httpx.NetworkError as error:
            if started:
                raise GenerationUnknownError("stream_interrupted", generation_started=True) from error
            raise PreGenerationError("connect", left_local=not isinstance(error, httpx.ConnectError)) from error
        except httpx.HTTPError as error:
            if started:
                raise GenerationUnknownError("http_error", generation_started=True) from error
            raise PreGenerationError("http_error", left_local=True) from error
        assembled = "".join(parts)
        if not assembled:
            raise PreGenerationError("empty", left_local=True)
        try:
            return json.loads(assembled), started, usage
        except json.JSONDecodeError as error:
            raise GenerationUnknownError("invalid_json", generation_started=True) from error
    finally:
        if close:
            client.close()


class DispatchOutcome:
    def __init__(self, status, result=None, error=None, selected_slot=None, failover_reason=None,
                 generation_started=False, usage=None, duration_ms=None, disclosure_state=None,
                 generation_state=None, transmission_state=None, attempts=None, authorized_recipients=None):
        self.status = status
        self.result = result
        self.error = error
        self.selected_slot = selected_slot
        self.failover_reason = failover_reason
        self.generation_started = generation_started
        self.usage = usage if isinstance(usage, dict) else None
        self.duration_ms = duration_ms
        if disclosure_state:
            self.disclosure_state = disclosure_state
        elif status == "complete":
            self.disclosure_state = "disclosed"
        elif generation_started:
            self.disclosure_state = "possible"
        else:
            self.disclosure_state = "undisclosed"
        self.generation_state = generation_state or (
            "complete" if status == "complete" else "started" if generation_started else "not_started"
        )
        self.transmission_state = transmission_state or (
            "response_received" if status == "complete" or generation_started else "not_left_local"
        )
        self.attempts = list(attempts or [])
        self.authorized_recipients = list(authorized_recipients or [])

    def ledger_fields(self):
        fields = {
            "selected_slot": self.selected_slot,
            "failover_reason": self.failover_reason,
            "generation_started": self.generation_started,
            "disclosure_state": self.disclosure_state,
            "generation_state": self.generation_state,
            "transmission_state": self.transmission_state,
            "attempts": self.attempts,
            "authorized_recipients": self.authorized_recipients,
        }
        if self.usage:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if key in self.usage:
                    fields[key] = self.usage[key]
        if self.duration_ms is not None:
            fields["duration_ms"] = self.duration_ms
        return fields


def _recipient(slot, name):
    target = slot.get("target") or ""
    return {
        "slot": name,
        "target": target,
        "model": slot.get("model") or "",
        "host": slot.get("host") or urlparse(target).hostname or "",
        "provider_id": slot.get("provider_id"),
    }


def _begin_attempt(slot, body, name):
    request_body = {key: (body or {}).get(key) for key in ("model", "messages", "temperature", "response_format") if key in (body or {})}
    request_body["model"] = slot.get("model") or request_body.get("model") or PRIMARY_MODEL
    return {
        "id": uid("attempt"),
        "slot": name,
        "target": slot.get("target") or "",
        "model": slot.get("model") or request_body["model"],
        "request_digest": digest(request_body),
        "started_at": now(),
        "finished_at": None,
        "generation_state": "not_started",
        "transmission_state": "not_left_local",
        "disclosure_state": "undisclosed",
        "error_type": None,
        "output_state": "none",
    }


def _finish_attempt(attempt, outcome):
    attempt["finished_at"] = now()
    attempt["generation_state"] = outcome.generation_state
    attempt["transmission_state"] = outcome.transmission_state
    attempt["disclosure_state"] = outcome.disclosure_state
    attempt["error_type"] = outcome.error
    if outcome.status == "complete":
        attempt["output_state"] = "complete"
    elif outcome.generation_started:
        attempt["output_state"] = "partial"
    else:
        attempt["output_state"] = "none"
    return attempt


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

    def dispatch(self, target, body, dual_slot=None, persist_attempt=None):
        slots = dual_slot if isinstance(dual_slot, dict) else {}
        primary = dict(slots.get("primary") or {
            "host": urlparse(target or PRIMARY_TARGET).hostname or PRIMARY_HOST,
            "target": target or PRIMARY_TARGET,
            "model": (body or {}).get("model") or PRIMARY_MODEL,
        })
        primary.setdefault("target", target or PRIMARY_TARGET)
        primary.setdefault("model", (body or {}).get("model") or PRIMARY_MODEL)
        raw_standby = slots.get("standby") if isinstance(slots.get("standby"), dict) else None
        standby = dict(raw_standby) if raw_standby and raw_standby.get("target") else None
        authorized = [_recipient(primary, "primary")]
        if standby:
            authorized.append(_recipient(standby, "standby"))
        started_at = time.perf_counter()
        attempts = []
        if not self.primary_key:
            return DispatchOutcome(
                "failed", error="云端密钥未配置", selected_slot="primary",
                disclosure_state="undisclosed", generation_state="not_started",
                transmission_state="not_left_local", attempts=attempts,
                authorized_recipients=authorized, duration_ms=_elapsed_ms(started_at),
            )

        def snapshot():
            return [dict(item) for item in attempts]

        def run(slot, key, name):
            attempt = _begin_attempt(slot, body, name)
            attempts.append(attempt)
            if persist_attempt:
                persist_attempt(snapshot(), authorized)
            outcome = self._attempt(slot, body, key, name)
            _finish_attempt(attempt, outcome)
            if persist_attempt:
                persist_attempt(snapshot(), authorized)
            outcome.attempts = list(attempts)
            outcome.authorized_recipients = authorized
            return outcome

        first = run(primary, self.primary_key, "primary")
        first.duration_ms = _elapsed_ms(started_at)
        if first.status == "complete":
            return first
        if first.generation_started or first.disclosure_state != "undisclosed":
            first.status = "unknown"
            first.error = first.error or "调用后结果不明；禁止自动重发，请核对服务商记录"
            return first
        if not standby or not self.standby_key:
            first.status = "unknown"
            first.error = first.error or "调用后结果不明；禁止自动重发，请核对服务商记录"
            return first
        second = run(standby, self.standby_key, "standby")
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
                return DispatchOutcome(
                    "unknown", error="invalid_json", selected_slot=name, generation_started=True, usage=usage,
                    disclosure_state="possible", generation_state="started", transmission_state="response_received",
                )
            return DispatchOutcome(
                "complete", result=result, selected_slot=name, generation_started=started, usage=usage,
                disclosure_state="disclosed", generation_state="complete", transmission_state="response_received",
            )
        except GenerationUnknownError as error:
            return DispatchOutcome(
                "unknown", error=error.reason, selected_slot=name, generation_started=True,
                disclosure_state="possible", generation_state="started", transmission_state="response_received",
            )
        except PreGenerationError as error:
            left = bool(getattr(error, "left_local", False))
            return DispatchOutcome(
                "unknown", error=error.reason, selected_slot=name, generation_started=False,
                disclosure_state="possible" if left else "undisclosed",
                generation_state="not_started",
                transmission_state="response_received" if left else "not_left_local",
            )


def _elapsed_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)
