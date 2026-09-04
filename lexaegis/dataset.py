"""Deterministic semi-synthetic corpus scaffolding without real case content."""
import random

from .util import digest


GROUPS = ("original", "find_replace", "consistent_pseudonym", "task_minimal", "ianvs_experimental")


def build_semisynthetic_manifest(count=100, seed=20260905):
    if count != 100:
        raise ValueError("首个冻结方案固定为 100 份案例")
    rng = random.Random(seed)
    records = []
    events = ("拖欠工资", "解除劳动合同", "加班费争议", "未签订书面合同", "工伤待遇争议")
    for index in range(count):
        case = {"id": f"semi_labor_{index+1:03d}", "synthetic": True,
                "structure_source": "abstract_only", "person": f"合成人物{index+1:03d}",
                "event": events[index % len(events)], "amount": 3000 + rng.randrange(0, 18) * 500,
                "annotation_status": "pending_double_annotation", "labels": [], "adjudication": None}
        case["content_hash"] = digest(case)
        records.append(case)
    shuffled = list(records)
    rng.shuffle(shuffled)
    split = {record["id"]: "development" if index < 70 else "blind" for index, record in enumerate(shuffled)}
    manifest = {"schema_version": 1, "seed": seed, "count": count, "groups": list(GROUPS), "split": split,
                "records_hash": digest(records), "freeze_status": "unfrozen_pending_annotation"}
    return records, manifest


def validate_annotations(records):
    problems = []
    for record in records:
        annotators = {label.get("annotator") for label in record.get("labels", []) if label.get("annotator")}
        if len(annotators) < 2:
            problems.append(f"{record['id']}: 缺少双人独立标注")
        if not record.get("adjudication"):
            problems.append(f"{record['id']}: 缺少第三人仲裁")
    return problems
