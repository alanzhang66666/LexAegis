import json
from pathlib import Path
from .contracts import DomainPack, TaskDefinition

TASKS = [
    TaskDefinition(id="fact_summary", name="事实摘要", available=True, output_type="claims"),
    TaskDefinition(id="timeline", name="时间线", output_type="timeline"),
    TaskDefinition(id="evidence_inventory", name="证据整理", output_type="evidence"),
    TaskDefinition(id="issue_extraction", name="争点提取", output_type="issues"),
]


def import_pack(repo, raw):
    pack = DomainPack.model_validate(raw)
    if pack.status == "published" and not pack.review_record:
        raise ValueError("正式规则包必须具有审核记录")
    if not set(pack.task_ids) <= {t.id for t in TASKS}:
        raise ValueError("任务尚未注册")
    record = {"id": f"pack:{pack.id}:{pack.version}", **pack.model_dump()}
    record["domain_id"] = pack.id
    record["id"] = f"pack:{pack.id}:{pack.version}"
    existing = repo.list("pack")
    if any(p["id"] == record["id"] and p != record for p in existing):
        raise ValueError("相同版本不可覆盖，请发布新版本")
    repo.put("pack", record)
    return record


def seed_packs(repo):
    if not repo.list("pack"):
        for path in sorted((Path(__file__).resolve().parent.parent / "packs").glob("*.json")):
            import_pack(repo, json.loads(path.read_text()))
