"""Reconstruct permitted synthetic outputs at the independent gateway."""
import json
import re
from .demo import SCENARIOS
from .policy import transform
from .task_engine import request_system_prompt
from .util import digest


def validate_synthetic_request(request):
    manifest = (request.get("dependencies") or {}).get("synthetic_manifest_hash")
    seed = next((s for s in SCENARIOS.values() if digest(s) == manifest), None)
    if seed is None:
        raise ValueError("合成材料清单未登记")
    wire = request.get("wire_payload") or {}
    if not isinstance(wire, dict) or set(wire) != {"contract_version", "task", "facts"} or wire["contract_version"] != 2:
        raise ValueError("合成披露快照包含未登记字段或版本")
    task = wire.get("task")
    task_id = "fact_summary"
    if task != {"id": task_id, "version": "2.0"}:
        raise ValueError("合成外部调用仅支持内置事实摘要")
    mappings = {value: f"[[LEX:P{index:04d}]]" for index, (field, value) in
                enumerate((row for row in seed["facts"] if row[0] == "entity"), start=1)}
    allowed = {(field, transform(value, method, mappings))
               for field, value in seed["facts"]
               for method in ("keep", "pseudonymize", "generalize", "moderate_generalize")}
    facts = wire.get("facts")
    if not isinstance(facts, list) or not 0 < len(facts) <= len(seed["facts"]):
        raise ValueError("合成披露字段数量不匹配")
    seen_ids = set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"id", "field", "text"}:
            raise ValueError("合成披露包含额外字段")
        ident = fact.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"fact_[0-9a-f]{16}", ident) or ident in seen_ids:
            raise ValueError("合成事实标识不是系统生成的唯一引用")
        seen_ids.add(ident)
        if (fact.get("field"), fact.get("text")) not in allowed:
            raise ValueError("合成正文不是登记材料的允许处理结果")
    body = request.get("body") or {}
    if set(body) - {"model", "messages", "temperature", "response_format", "thinking"}:
        raise ValueError("合成请求包含任意附加正文")
    messages = body.get("messages") or []
    if len(messages) != 2 or messages[0] != {"role": "system", "content": request_system_prompt(task_id)}:
        raise ValueError("合成请求提示词与内置版本不一致")
    if set(messages[1]) != {"role", "content"} or messages[1]["role"] != "user":
        raise ValueError("合成请求消息结构不匹配")
    # Compare the bytes-as-text that will be sent, not json.loads equality:
    # duplicate JSON keys can hide arbitrary customer text discarded by a
    # parser while the model still receives the original string in full.
    if messages[1]["content"] != json.dumps(wire, ensure_ascii=False) or body.get("response_format") != {"type": "json_object"}:
        raise ValueError("实际正文与合成披露快照不一致")
    if body.get("temperature") != 0 or body.get("thinking", {"type": "disabled"}) != {"type": "disabled"}:
        raise ValueError("合成请求生成参数不匹配")
