import json
import re
from pathlib import Path
from .contracts import DomainPack, DomainPackV2, TaskDefinition, TaskDefinitionV2
from .governance import publish_pack_record
from .task_engine import registered_tasks

TASKS = [
    TaskDefinition(id="fact_summary", name="事实摘要", available=True, output_type="claims"),
    TaskDefinition(id="timeline", name="时间线", available=True, output_type="timeline"),
    TaskDefinition(id="evidence_inventory", name="证据整理", available=True, output_type="evidence"),
    TaskDefinition(id="issue_extraction", name="争点提取", available=True, output_type="issues"),
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
    if schema_version == 2:
        fields = {item.id for item in pack.fact_fields}
        if len(fields) != len(pack.fact_fields):
            raise ValueError("事实字段标识不可重复")
        if any(rule.field not in fields for rule in pack.rules):
            raise ValueError("披露规则引用了未定义字段")
        matrix = pack.task_field_matrix
        if not matrix:
            generated = [
                {"task_id": task_id, "field": field, "necessity": "uncertain", "rationale": "待法学团队确认"}
                for task_id in pack.task_ids for field in sorted(fields)
            ]
            pack = DomainPackV2.model_validate({**pack.model_dump(), "task_field_matrix": generated})
            matrix = pack.task_field_matrix
        pairs = [(item.task_id, item.field) if hasattr(item, "task_id") else (item["task_id"], item["field"]) for item in matrix]
        if len(set(pairs)) != len(pairs):
            raise ValueError("任务—字段矩阵存在重复项")
        if any(task_id not in pack.task_ids or field not in fields for task_id, field in pairs):
            raise ValueError("任务—字段矩阵引用了未定义任务或字段")
        if set(pack.task_ids) - {task_id for task_id, _ in pairs}:
            raise ValueError("每个任务至少需要一项字段必要性定义")
        for spec in pack.direct_identifier_patterns:
            _validate_pattern(spec)
        allowed_weights = {"entity", "density", "context", "combination", "cross_round"}
        if set(pack.risk_weights) - allowed_weights or any(not 0 <= value <= 1 for value in pack.risk_weights.values()):
            raise ValueError("风险权重名称或范围无效")
        if pack.status == "published":
            if (set(pack.risk_weights) != allowed_weights or not pack.dispatch_allowed
                    or pack.legal_status != "reviewed" or not pack.published_scope):
                raise ValueError("正式案由包缺少冻结权重、法学发布状态或适用范围")
        _validate_disclosure_overlay(pack)
    return pack


def _validate_disclosure_overlay(pack):
    fields = {item.id for item in pack.fact_fields}
    sources = {item.id for item in pack.legal_sources}
    relations = {item.id for item in pack.immutable_relations}
    rule_ids = []
    for rule in pack.disclosure_rules:
        rule_ids.append(rule.id)
        if rule.task_id not in pack.task_ids:
            raise ValueError("披露规则引用了未注册任务")
        if any(field not in fields for field in rule.affected_fields):
            raise ValueError("披露规则引用了未定义字段")
        if any(source_id not in sources for source_id in rule.legal_source_ids):
            raise ValueError("披露规则引用了未定义法源")
        if any(relation_id not in relations for relation_id in rule.immutable_relations):
            raise ValueError("披露规则引用了未定义不可破坏关系")
        if rule.preferred_transform not in set(rule.allowed_transforms):
            raise ValueError("披露规则的缺省变换不在允许集合内")
    if len(set(rule_ids)) != len(rule_ids):
        raise ValueError("披露规则标识不可重复")
    if any(item.citation_status == "published" for item in pack.legal_sources) and pack.legal_status != "reviewed":
        raise ValueError("未完成法学审核的案由包不能把法源标成已发布")


def _validate_pattern(spec):
    if not isinstance(spec, dict) or not {"category", "pattern"} <= set(spec):
        raise ValueError("直接标识模式缺少 category 或 pattern")
    pattern = spec["pattern"]
    if not isinstance(pattern, str) or len(pattern) > 500 or "\n" in pattern:
        raise ValueError("直接标识模式长度或格式无效")
    if re.search(r"\\[1-9]|\(\?P=|\([^)]*[+*][^)]*\)[+*{]", pattern):
        raise ValueError("直接标识模式包含高风险回溯结构")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError("直接标识模式不是有效正则") from error


def run_pack_regressions(pack: dict) -> dict:
    rules = {item["field"]: item for item in pack.get("rules", [])}
    results = []
    for index, case in enumerate(pack.get("synthetic_cases", [])):
        failures = []
        for expected in case.get("expected_decisions", []):
            actual = rules.get(expected.get("field"))
            if not actual:
                failures.append(f"字段 {expected.get('field')} 无规则")
                continue
            for key in ("necessity", "transform", "forbidden"):
                if key in expected and actual.get(key) != expected[key]:
                    failures.append(f"{expected['field']}.{key} 不匹配")
        results.append({"id": case.get("id", f"case_{index+1}"), "passed": not failures, "failures": failures})
    return {"status": "passed" if results and all(item["passed"] for item in results) else ("failed" if results else "not_run"),
            "total": len(results), "results": results}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


_REFRESHABLE_PACK_STATUSES = frozenset({"demo", "draft"})


def _pack_record(pack):
    record = {"id": f"pack:{pack.id}:{pack.version}", **pack.model_dump()}
    record["domain_id"] = pack.id
    record["id"] = f"pack:{pack.id}:{pack.version}"
    return record


def import_pack(repo, raw):
    pack = validate_pack(raw)
    if getattr(pack, "status", None) == "published":
        raise ValueError("不得直接导入已发布状态；V2 包必须经过本实例的审核与发布生命周期")
    record = _pack_record(pack)
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
    installed = Path(__file__).resolve().parent / "packs"
    source = Path(__file__).resolve().parent.parent / "packs"
    root = installed if installed.exists() else source
    existing = {item["id"]: item for item in repo.list("pack")}
    for path in sorted(root.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not existing:
            import_pack(repo, raw)
            continue
        pack = validate_pack(raw)
        if pack.status == "published":
            continue
        record = _pack_record(pack)
        current = existing.get(record["id"])
        if current is None or current.get("status") not in _REFRESHABLE_PACK_STATUSES:
            continue
        if record.get("status") not in _REFRESHABLE_PACK_STATUSES:
            continue
        if current != record:
            repo.put("pack", record)
