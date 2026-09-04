"""Built-in task contracts and deterministic task execution."""
from importlib.metadata import entry_points


TASK_DEFINITIONS = [
    {"schema_version": 2, "id": "fact_summary", "name": "事实摘要", "version": "2.0", "status": "available", "execution_type": "approved_cloud",
     "input_schema": {"type": "object", "required": ["facts"]}, "output_schema": {"type": "object", "required": ["claims"]},
     "prompt_template": "根据已批准事实生成事实摘要，每条陈述必须给出 source_ids。", "validator": "claims_v2", "transports": ["mock", "cloud"], "ui_renderer": "claims", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "timeline", "name": "时间线", "version": "2.0", "status": "available", "execution_type": "local_deterministic",
     "input_schema": {"type": "object", "required": ["facts"]}, "output_schema": {"type": "object", "required": ["events"]},
     "validator": "timeline_v2", "transports": ["local"], "ui_renderer": "timeline", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "evidence_inventory", "name": "证据整理", "version": "2.0", "status": "unimplemented", "execution_type": "local_deterministic",
     "input_schema": {}, "output_schema": {}, "validator": "unimplemented", "transports": ["local"], "ui_renderer": "evidence", "max_payload_chars": 50000},
    {"schema_version": 2, "id": "issue_extraction", "name": "争点提取", "version": "2.0", "status": "unimplemented", "execution_type": "approved_cloud",
     "input_schema": {}, "output_schema": {}, "validator": "unimplemented", "transports": ["cloud"], "ui_renderer": "issues", "max_payload_chars": 50000},
]


def registered_tasks() -> dict[str, dict]:
    tasks = {task["id"]: dict(task) for task in TASK_DEFINITIONS}
    for entry in entry_points(group="lexaegis.tasks"):
        plugin = entry.load()
        definition = plugin.definition() if hasattr(plugin, "definition") else None
        if not isinstance(definition, dict) or definition.get("id") in tasks:
            raise ValueError(f"无效或冲突的任务扩展：{entry.name}")
        tasks[definition["id"]] = definition
    return tasks


def run_timeline(facts: list[dict]) -> dict:
    events = []
    for fact in facts:
        if fact.get("field") == "date" or any(marker in fact.get("value", "") for marker in ("年", "月", "日")):
            events.append({"id": fact["id"], "text": fact["value"], "source_ids": fact.get("source_ids", [])})
    return {"events": events, "provenance": "local_deterministic"}
