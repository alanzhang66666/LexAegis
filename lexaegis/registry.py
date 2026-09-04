import json
from pathlib import Path
from .contracts import DomainPack, DomainPackV2, TaskDefinition, TaskDefinitionV2
from .governance import publish_pack_record
from .task_engine import registered_tasks

TASKS = [
    TaskDefinition(id="fact_summary", name="事实摘要", available=True, output_type="claims"),
    TaskDefinition(id="timeline", name="时间线", available=True, output_type="timeline"),
    TaskDefinition(id="evidence_inventory", name="证据整理", output_type="evidence"),
    TaskDefinition(id="issue_extraction", name="争点提取", output_type="issues"),
]


def task_definitions():
    return [TaskDefinitionV2.model_validate(task).model_dump() for task in registered_tasks().values()]


def pack_field_ids(pack):
    return {field if isinstance(field, str) else field["id"] for field in pack.get("fact_fields", [])}


def validate_pack(raw):
    schema_version = raw.get("schema_version", 1) if isinstance(raw, dict) else None
    if schema_version == 1:
        pack = DomainPack.model_validate(raw)
        if pack.status == "published":
            raise ValueError("v1 规则包只能保持 draft/demo，不能作为正式规则发布")
    elif schema_version == 2:
        pack = DomainPackV2.model_validate(raw)
    else:
        raise ValueError("不支持的案由包 schema_version")
    dump = pack.model_dump()
    registered = set(registered_tasks())
    if not set(pack.task_ids) <= registered:
        raise ValueError("任务尚未注册")
    if any(key.lower().endswith(("code", "expression", "script", "callable")) for key in _walk_keys(dump)):
        raise ValueError("案由包只能包含声明式数据，不允许代码或可执行表达式")
    return pack


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def import_pack(repo, raw):
    pack = validate_pack(raw)
    if getattr(pack, "status", None) == "published" and (not pack.review_record or not getattr(pack, "content_hash", None)):
        raise ValueError("正式规则包必须具有审核记录和冻结内容哈希")
    record = {"id": f"pack:{pack.id}:{pack.version}", **pack.model_dump()}
    record["domain_id"] = pack.id
    record["id"] = f"pack:{pack.id}:{pack.version}"
    existing = repo.list("pack")
    if any(p["id"] == record["id"] and p != record for p in existing):
        raise ValueError("相同版本不可覆盖，请发布新版本")
    repo.put("pack", record)
    return record


def publish_pack(repo, pack_id, actor):
    pack = repo.get(pack_id, "pack")
    published = publish_pack_record(pack, actor)
    # Publishing mutates lifecycle metadata only once. Published records remain immutable.
    if pack.get("status") == "published":
        raise ValueError("已发布版本不可重复发布或覆盖")
    repo.put("pack", published)
    return published


def seed_packs(repo):
    if not repo.list("pack"):
        installed = Path(__file__).resolve().parent / "packs"
        source = Path(__file__).resolve().parent.parent / "packs"
        root = installed if installed.exists() else source
        for path in sorted(root.glob("*.json")):
            import_pack(repo, json.loads(path.read_text(encoding="utf-8")))
