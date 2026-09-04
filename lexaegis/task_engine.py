"""Versioned task registry, schema checks and pluggable execution."""
from __future__ import annotations

import json
from importlib.metadata import entry_points
from typing import Any

from .contracts import TaskDefinitionV2


TASK_DEFINITIONS = [
    {"schema_version": 2, "id": "fact_summary", "name": "事实摘要", "version": "2.0", "status": "available", "execution_type": "approved_cloud",
     "input_schema": {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "array"}}},
     "output_schema": {"type": "object", "required": ["claims"], "properties": {"claims": {"type": "array"}}},
     "prompt_template": "根据已批准事实生成事实摘要，每条陈述必须给出 source_ids。", "validator": "claims_v2", "transports": ["mock", "cloud"], "ui_renderer": "claims", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "timeline", "name": "时间线", "version": "2.0", "status": "available", "execution_type": "local_deterministic",
     "input_schema": {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "array"}}},
     "output_schema": {"type": "object", "required": ["events"], "properties": {"events": {"type": "array"}}},
     "validator": "timeline_v2", "transports": ["local"], "ui_renderer": "timeline", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "evidence_inventory", "name": "证据整理", "version": "2.0", "status": "unimplemented", "execution_type": "local_deterministic",
     "input_schema": {}, "output_schema": {}, "validator": "unimplemented", "transports": ["local"], "ui_renderer": "evidence", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "issue_extraction", "name": "争点提取", "version": "2.0", "status": "unimplemented", "execution_type": "approved_cloud",
     "input_schema": {}, "output_schema": {}, "validator": "unimplemented", "transports": ["cloud"], "ui_renderer": "issues", "max_payload_chars": 50000},
]


def run_timeline(payload: dict) -> dict:
    events = []
    for fact in payload["facts"]:
        if fact.get("field") == "date" or any(marker in fact.get("value", "") for marker in ("年", "月", "日")):
            events.append({"id": fact["id"], "text": fact["value"], "source_ids": fact.get("source_ids", [])})
    return {"events": events}


BUILTIN_HANDLERS = {"timeline": run_timeline}
BUILTIN_VALIDATORS = {"claims_v2", "timeline_v2", "unimplemented"}


def _plugins() -> dict[str, Any]:
    plugins = {}
    for entry in entry_points(group="lexaegis.tasks"):
        plugin = entry.load()
        definition = plugin.definition() if hasattr(plugin, "definition") else None
        if not isinstance(definition, dict):
            raise ValueError(f"无效任务扩展：{entry.name}")
        validated = TaskDefinitionV2.model_validate(definition).model_dump()
        if validated["id"] in plugins:
            raise ValueError(f"任务扩展标识冲突：{validated['id']}")
        plugins[validated["id"]] = plugin
    return plugins


def registered_tasks() -> dict[str, dict]:
    tasks = {}
    for raw in TASK_DEFINITIONS:
        definition = TaskDefinitionV2.model_validate(raw).model_dump()
        tasks[definition["id"]] = definition
    for task_id, plugin in _plugins().items():
        if task_id in tasks:
            raise ValueError(f"任务扩展与内置任务冲突：{task_id}")
        tasks[task_id] = TaskDefinitionV2.model_validate(plugin.definition()).model_dump()
    return tasks


def validate_json_schema(value: Any, schema: dict, path: str = "$") -> None:
    """Validate the deliberately small, data-only JSON Schema subset we expose."""
    if not schema:
        return
    allowed = {"type", "required", "properties", "items", "enum", "maxItems", "maxLength", "additionalProperties"}
    unsupported = set(schema) - allowed
    if unsupported:
        raise ValueError(f"{path} 使用了不支持的 JSON Schema 关键字：{sorted(unsupported)}")
    expected = schema.get("type")
    types = {
        "object": dict, "array": list, "string": str,
        "number": (int, float), "integer": int, "boolean": bool, "null": type(None),
    }
    if expected and (expected not in types or not isinstance(value, types[expected]) or (expected in ("number", "integer") and isinstance(value, bool))):
        raise ValueError(f"{path} 不符合类型 {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} 不在允许枚举中")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"{path} 缺少字段：{sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"{path} 含未声明字段")
        for key, child in value.items():
            if key in properties:
                validate_json_schema(child, properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"{path} 数组超出上限")
        if "items" in schema:
            for index, child in enumerate(value):
                validate_json_schema(child, schema["items"], f"{path}[{index}]")
    elif isinstance(value, str) and len(value) > schema.get("maxLength", len(value)):
        raise ValueError(f"{path} 字符串超出上限")


def _definition(task_id: str) -> dict:
    try:
        return registered_tasks()[task_id]
    except KeyError as error:
        raise ValueError("任务尚未注册") from error


def validate_task_payload(task_id: str, payload: dict) -> dict:
    definition = _definition(task_id)
    if len(json.dumps(payload, ensure_ascii=False)) > definition["max_payload_chars"]:
        raise ValueError("任务输入超过定义的负载上限")
    validate_json_schema(payload, definition["input_schema"])
    return definition


def execute_local(task_id: str, payload: dict) -> dict:
    definition = validate_task_payload(task_id, payload)
    if definition["status"] != "available" or definition["execution_type"] != "local_deterministic":
        raise ValueError("任务不可作为本地确定性任务执行")
    if task_id in BUILTIN_HANDLERS:
        result = BUILTIN_HANDLERS[task_id](payload)
    else:
        plugin = _plugins().get(task_id)
        if not plugin or not hasattr(plugin, "run"):
            raise ValueError("任务扩展未提供 run 处理器")
        result = plugin.run(payload)
    validate_json_schema(result, definition["output_schema"])
    return {**result, "provenance": "local_deterministic"}


def validate_cloud_result(task_id: str, raw: dict, task: dict, facts: list[dict]):
    definition = _definition(task_id)
    validate_json_schema(raw, definition["output_schema"])
    if definition["validator"] == "claims_v2":
        from .policy import check_claims
        return check_claims(raw, task, facts)
    plugin = _plugins().get(task_id)
    if plugin and hasattr(plugin, "validate_output"):
        return plugin.validate_output(raw, {"task": task, "facts": facts})
    if definition["validator"] not in BUILTIN_VALIDATORS:
        raise ValueError("任务结果验证器未安装")
    return raw
