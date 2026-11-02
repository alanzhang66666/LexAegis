"""Versioned provider HTTP body bytes. No keys, headers, raw files or send rights.

The approval binds a deterministic projection of its frozen request. Gateway
and transport recompute that projection. A receipt means an attempt was prepared
for transport, not that a recipient received or legally accepted it.
"""
import hashlib
import json
from urllib.parse import urlparse

SERIALIZER = "lexaegis-chat-json-v1"
BODY_KEYS = ("model", "messages", "temperature", "response_format")


def provider_body(body, slot):
    if not isinstance(body, dict) or not isinstance(slot.get("model"), str) or not slot["model"]:
        raise ValueError("invalid wire body or model")
    clean = {key: body[key] for key in BODY_KEYS if key in body}
    clean.update(model=slot["model"], temperature=0, response_format={"type": "json_object"}, stream=True)
    if "deepseek" in (slot.get("host") or ""):
        clean["thinking"] = {"type": "disabled"}
    return clean


def serialize_body(target, body, model):
    slot = {"host": urlparse(target).hostname or "", "model": model}
    return json.dumps(provider_body(body, slot), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def body_receipt(target, body, model):
    content = serialize_body(target, body, model)
    return receipt_for_content(target, model, content)


def receipt_for_content(target, model, content):
    return {"target": target, "model": model, "serializer": SERIALIZER,
            "body_sha256": hashlib.sha256(content).hexdigest(), "body_size": len(content)}


def approval_binding(request):
    if request.get("transport") != "cloud":
        raise ValueError("wire binding only applies to cloud requests")
    slots = (request.get("dependencies") or {}).get("dual_slot")
    if not isinstance(slots, dict) or not isinstance(slots.get("primary"), dict):
        raise ValueError("approved primary wire slot is missing")
    primary = slots["primary"]
    if primary.get("target") != request.get("target") or primary.get("model") != (request.get("body") or {}).get("model"):
        raise ValueError("wire primary slot does not match the frozen request")
    result = {}
    for name in ("primary", "standby"):
        slot = slots.get(name)
        if slot is None:
            continue
        if not isinstance(slot, dict) or not isinstance(slot.get("target"), str) or not slot["target"]:
            raise ValueError("invalid approved wire slot")
        result[name] = body_receipt(slot["target"], request.get("body"), slot.get("model"))
    return {"version": 1, "slots": result}


def require_binding(request, supplied):
    expected = approval_binding(request)
    # Canonical comparison also distinguishes bool from integer, unlike ==.
    if (not isinstance(supplied, dict) or json.dumps(supplied, sort_keys=True, allow_nan=False)
            != json.dumps(expected, sort_keys=True, allow_nan=False)):
        raise ValueError("approved HTTP wire body binding is missing or changed; reapproval required")
    return expected


def validate_attempt(binding, attempt):
    expected = binding["slots"].get(attempt.get("slot"))
    if not expected or any(attempt.get(key) != expected[key] for key in ("target", "model", "serializer")):
        raise ValueError("wire attempt is outside approved slot")
    if (attempt.get("prepared_wire_body_sha256") != expected["body_sha256"]
            or type(attempt.get("wire_body_size")) is not int or attempt["wire_body_size"] != expected["body_size"]):
        raise ValueError("wire attempt bytes differ from approval")
    actual = attempt.get("attempted_wire_body_sha256")
    if actual is not None and actual != expected["body_sha256"]:
        raise ValueError("transport wire bytes differ from approval")
    return expected["body_sha256"]
