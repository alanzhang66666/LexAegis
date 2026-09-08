"""Deterministic synthetic corpus and blind-comparison scaffolding.

The included records are conspicuously fictional. They provide technical
anchors and direct-identifier truth only; legal necessity and legal utility
remain unlabelled until the legal study protocol is approved.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .experiments import run_ianvs_profile
from .util import digest


GROUPS = ("original", "find_replace", "consistent_pseudonym", "task_minimal", "ianvs_experimental")

SEMI_LABOR_GENERATOR = "lexaegis.semi_labor.v1"
SEMI_LABOR_METHOD = "structure_abstracted_recombined_template"
SEMI_EVENTS = (
    "拖欠工资",
    "解除劳动合同",
    "加班费争议",
    "未签订书面合同",
    "工伤待遇争议",
    "绩效奖金争议",
    "调岗降薪争议",
    "社会保险争议",
)
SEMI_EMPLOYER_STEMS = (
    "模拟劳动",
    "虚构科技",
    "演示制造",
    "抽象物流",
    "重组服务",
    "合成贸易",
    "评测餐饮",
    "脚手架建筑",
    "对照运输",
    "门禁零售",
)
SEMI_EMPLOYER_FORMS = ("有限公司", "股份有限公司", "劳务派遣公司")
SEMI_EVIDENCE_KINDS = ("合成工资表", "合成考勤记录", "合成劳动合同摘录", "合成社保缴费清单")
SEMI_TEMPLATES = (
    (
        "{person}（电话{phone}，邮箱{email}，住址{address}）称其在{employer}任职，"
        "并就{event}提出请求；入职约{tenure}个月后发生争议，主张金额{amount}元。"
        "材料引用{evidence}。本文由结构抽象模板重组，不含真实案件原文。"
    ),
    (
        "申请人{person}与{employer}因{event}发生争议。通讯方式为{phone}、{email}，"
        "送达地址{address}。请求支付{amount}元，并提交{evidence}作为合成附件。"
    ),
    (
        "{employer}劳动人事材料（合成重组）记载：劳动者{person}提出{event}，"
        "金额{amount}元。联系人电话{phone}，邮箱{email}，住址{address}。"
        "对应{evidence}。"
    ),
    (
        "虚构仲裁申请书摘要：{person}请求裁决{employer}处理{event}，标的{amount}元。"
        "申请人住所{address}，电话{phone}，邮箱{email}。证据目录含{evidence}。"
    ),
)


def build_semisynthetic_records(count: int = 100, seed: int = 20260905) -> list[dict]:
    """Build 100 fictional, recombined labor-dispute scaffolds. No real case text."""
    if count != 100:
        raise ValueError("首个冻结方案固定为 100 份案例")
    rng = random.Random(seed)
    records = []
    for index in range(count):
        ordinal = index + 1
        person = f"合成人物{ordinal:03d}"
        event = SEMI_EVENTS[index % len(SEMI_EVENTS)]
        amount = 3000 + rng.randrange(0, 18) * 500
        employer = (
            f"{SEMI_EMPLOYER_STEMS[index % len(SEMI_EMPLOYER_STEMS)]}"
            f"{SEMI_EMPLOYER_FORMS[index % len(SEMI_EMPLOYER_FORMS)]}"
            f"（合成主体{ordinal:03d}）"
        )
        phone = f"1661000{ordinal:04d}"
        email = f"semi{ordinal:03d}@example.invalid"
        address = f"模拟市抽象区重组路{ordinal}号"
        evidence = f"{SEMI_EVIDENCE_KINDS[index % len(SEMI_EVIDENCE_KINDS)]}{ordinal:03d}号"
        tenure = 3 + index % 24
        date = f"2026-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}"
        narrative = SEMI_TEMPLATES[index % len(SEMI_TEMPLATES)].format(
            person=person, employer=employer, event=event, amount=amount,
            phone=phone, email=email, address=address, evidence=evidence, tenure=tenure,
        )
        appendix = (
            f"合成附录：争议日期记为{date}，事件类型为{event}，重组金额{amount}元。"
            f"本条仅用于结构抽象评测，不得作为正式外发依据。"
        )
        record = {
            "schema_version": 1,
            "id": f"semi_labor_{ordinal:03d}",
            "synthetic": True,
            "structure_source": "abstract_only",
            "person": person,
            "event": event,
            "amount": amount,
            "annotation_status": "pending_double_annotation",
            "labels": [],
            "adjudication": None,
            "provenance": {
                "method": SEMI_LABOR_METHOD,
                "generator_id": SEMI_LABOR_GENERATOR,
                "seed": seed,
                "contains_real_case_content": False,
                "structure_source": "abstract_only",
            },
            "task": {"id": "fact_summary", "version": "2.0"},
            "document": {
                "id": f"semi_doc_{ordinal:03d}",
                "version": 1,
                "blocks": [
                    {"id": "block_001", "text": narrative, "locator": "合成材料第 1 段", "page": 1},
                    {"id": "block_002", "text": appendix, "locator": "合成材料第 2 段", "page": 1},
                ],
            },
            "facts": [
                {"id": "fact_person", "field": "entity", "text": person, "source_ids": ["block_001"]},
                {"id": "fact_employer", "field": "entity", "text": employer, "source_ids": ["block_001"]},
                {"id": "fact_event", "field": "event", "text": event, "source_ids": ["block_001"]},
                {"id": "fact_date", "field": "date", "text": date, "source_ids": ["block_002"]},
                {"id": "fact_amount", "field": "amount", "text": f"{amount}元", "source_ids": ["block_001"]},
                {"id": "fact_evidence", "field": "evidence", "text": evidence, "source_ids": ["block_001"]},
            ],
            "annotations": {
                "annotator_a": None,
                "annotator_b": None,
                "adjudication": None,
                "status": "pending_legal_annotation",
            },
        }
        record["content_hash"] = digest({key: value for key, value in record.items() if key != "content_hash"})
        records.append(record)
    return records


def draft_semi_labor_core(records: list[dict], seed: int = 20260905) -> dict:
    """Draft identity for the unannotated 100-case scaffold (not a technical freeze)."""
    if len(records) != 100:
        raise ValueError("首个冻结方案固定为 100 份案例")
    ordered = sorted(records, key=lambda item: item["id"])
    rng = random.Random(seed)
    ids = [record["id"] for record in ordered]
    rng.shuffle(ids)
    split = {record_id: "development" if index < 70 else "blind" for index, record_id in enumerate(ids)}
    core = {
        "schema_version": 1,
        "seed": seed,
        "count": len(ordered),
        "groups": list(GROUPS),
        "split": split,
        "records_hash": digest(ordered),
        "record_hashes": {record["id"]: record["content_hash"] for record in ordered},
        "generator_version": SEMI_LABOR_GENERATOR,
        "generation_artifact": {
            "method": SEMI_LABOR_METHOD,
            "template_hash": digest({
                "events": SEMI_EVENTS,
                "templates": SEMI_TEMPLATES,
                "schema": "semi_labor.v1",
            }),
            "runtime_model_hash": "not_applicable",
            "runtime_prompt_hash": "not_applicable",
        },
        "dependency_hash": "unrecorded",
        "legal_annotation_status": "pending",
        "freeze_status": "unfrozen_pending_annotation",
    }
    return {**core, "freeze_hash": digest(core)}


def build_semisynthetic_manifest(count=100, seed=20260905):
    records = build_semisynthetic_records(count, seed)
    from .data_registry import build_semi_labor_manifest
    return records, build_semi_labor_manifest(records, seed).model_dump(mode="json")


def validate_annotations(records):
    problems = []
    for record in records:
        annotators = {label.get("annotator") for label in record.get("labels", []) if label.get("annotator")}
        if len(annotators) < 2:
            problems.append(f"{record['id']}: 缺少双人独立标注")
        if not record.get("adjudication"):
            problems.append(f"{record['id']}: 缺少第三人仲裁")
    return problems


MOCK_EVENTS = (
    ("拖欠工资", "2026-01-15", 12500, 18),
    ("解除劳动合同", "2026-02-03", 8000, 9),
    ("加班费争议", "2026-03-12", 4600, 27),
    ("未签订书面合同", "2026-04-08", 16000, 61),
    ("工伤待遇争议", "2026-05-19", 9800, 34),
    ("绩效奖金争议", "2026-06-06", 7200, 12),
    ("调岗降薪争议", "2026-07-21", 6000, 22),
    ("社会保险争议", "2026-08-17", 5400, 45),
)


def _spans(text: str, values: list[tuple[str, str]]) -> list[dict]:
    findings = []
    for category, value in values:
        start = text.index(value)
        findings.append({
            "category": category,
            "value": value,
            "start": start,
            "end": start + len(value),
            "source_id": "block_001",
        })
    return findings


def build_mock_corpus(count: int = 8, seed: int = 20260905) -> list[dict]:
    """Build a small AI-authored, deterministic, wholly fictional corpus."""
    if not 2 <= count <= len(MOCK_EVENTS):
        raise ValueError(f"模拟数据数量须在 2 至 {len(MOCK_EVENTS)} 之间")
    rng = random.Random(seed)
    records = []
    for index, (event, date, amount, duration_days) in enumerate(MOCK_EVENTS[:count], 1):
        person = f"合成人物{index:03d}"
        employer = f"模拟企业{chr(64 + index)}有限公司"
        phone = f"1660000{index:04d}"
        email = f"mock{index:03d}@example.invalid"
        address = f"模拟市测试区虚构路{index}号"
        evidence = f"合成证据{index:03d}号工资表"
        text = (
            f"{person}（电话{phone}，邮箱{email}，住址{address}）称其在"
            f"{employer}任职，并就{event}提出请求；争议日期为{date}，"
            f"主张金额{amount}元。材料引用{evidence}。"
        )
        direct_values = [
            ("person_name", person),
            ("organization", employer),
            ("phone", phone),
            ("email", email),
            ("address", address),
        ]
        record = {
            "schema_version": 1,
            "id": f"mock_labor_{index:03d}",
            "synthetic": True,
            "provenance": {
                "method": "deterministic_ai_authored_template",
                "generator_id": "lexaegis.mock_labor.v1",
                "seed": seed,
                "contains_real_case_content": False,
            },
            "task": {"id": "fact_summary", "version": "2.0"},
            "document": {
                "id": f"mock_doc_{index:03d}",
                "version": 1,
                "blocks": [{
                    "id": "block_001",
                    "text": text,
                    "locator": "合成材料第 1 段",
                    "page": 1,
                }],
            },
            "facts": [
                {"id": "fact_person", "field": "entity", "text": person, "source_ids": ["block_001"]},
                {"id": "fact_employer", "field": "entity", "text": employer, "source_ids": ["block_001"]},
                {"id": "fact_event", "field": "event", "text": event, "source_ids": ["block_001"]},
                {"id": "fact_date", "field": "date", "text": date, "source_ids": ["block_001"]},
                {"id": "fact_amount", "field": "amount", "text": f"{amount}元", "source_ids": ["block_001"]},
                {"id": "fact_evidence", "field": "evidence", "text": evidence, "source_ids": ["block_001"]},
            ],
            "technical_truth": {
                "direct_identifiers": _spans(text, direct_values),
                "feature_vector": [
                    amount / 20000,
                    index / len(MOCK_EVENTS),
                    duration_days / 90,
                    1.0,
                ],
                "feature_schema": [
                    "normalized_claim_amount",
                    "synthetic_event_category",
                    "normalized_duration_days",
                    "evidence_present",
                ],
            },
            "annotations": {
                "annotator_a": None,
                "annotator_b": None,
                "adjudication": None,
                "status": "pending_legal_annotation",
            },
        }
        record["content_hash"] = digest({key: value for key, value in record.items() if key != "content_hash"})
        records.append(record)
    rng.shuffle(records)
    return records


def freeze_mock_corpus(records: list[dict], *, seed: int = 20260905,
                       dependency_hash: str = "unrecorded",
                       generator_version: str = "lexaegis.mock_labor.v1") -> dict:
    if len(records) < 2:
        raise ValueError("冻结数据至少需要两条记录")
    for record in records:
        if record.get("synthetic") is not True or record.get("provenance", {}).get("contains_real_case_content") is not False:
            raise ValueError("当前冻结命令只接受明确声明不含真实案件内容的模拟数据")
        core = {key: value for key, value in record.items() if key != "content_hash"}
        if record.get("content_hash") != digest(core):
            raise ValueError(f"{record.get('id', 'unknown')}: 内容哈希不一致")
    ordered = sorted(records, key=lambda item: item["id"])
    rng = random.Random(seed)
    ids = [record["id"] for record in ordered]
    rng.shuffle(ids)
    development_count = max(1, min(len(ids) - 1, round(len(ids) * .7)))
    split = {
        record_id: "development" if index < development_count else "blind"
        for index, record_id in enumerate(ids)
    }
    core = {
        "schema_version": 2,
        "seed": seed,
        "count": len(ordered),
        "groups": list(GROUPS),
        "split": split,
        "records_hash": digest(ordered),
        "record_hashes": {record["id"]: record["content_hash"] for record in ordered},
        "generator_version": generator_version,
        "generation_artifact": {
            "method": "deterministic_ai_authored_template",
            "template_hash": digest({"events": MOCK_EVENTS, "schema": "mock_labor.v1"}),
            "runtime_model_hash": "not_applicable",
            "runtime_prompt_hash": "not_applicable",
        },
        "dependency_hash": dependency_hash,
        "legal_annotation_status": "pending",
        "freeze_status": "frozen_technical_mock",
    }
    return {**core, "freeze_hash": digest(core)}


def write_records_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as JSONL; refuse to overwrite an existing file."""
    ordered = sorted(records, key=lambda item: item["id"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for record in ordered:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_records_jsonl(path: Path) -> list[dict]:
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _replace_identifiers(text: str, record: dict, replacements: dict[str, str]) -> str:
    values = record["technical_truth"]["direct_identifiers"]
    for finding in sorted(values, key=lambda item: len(item["value"]), reverse=True):
        text = text.replace(finding["value"], replacements[finding["category"]])
    return text


def transform_mock_record(record: dict, group: str) -> dict:
    if group not in GROUPS[:-1]:
        raise ValueError("文本对照只支持四个核心组；Ianvs 组由数值实验引擎生成")
    raw = record["document"]["blocks"][0]["text"]
    if group == "original":
        payload = raw
        source_ids = ["block_001"]
    elif group == "find_replace":
        payload = _replace_identifiers(raw, record, {
            "person_name": "某劳动者",
            "organization": "某用人单位",
            "phone": "[电话已删除]",
            "email": "[邮箱已删除]",
            "address": "[地址已删除]",
        })
        source_ids = ["block_001"]
    else:
        payload = _replace_identifiers(raw, record, {
            "person_name": "[[LEX:P0001]]",
            "organization": "[[LEX:O0001]]",
            "phone": "[[LEX:C0001]]",
            "email": "[[LEX:C0002]]",
            "address": "[[LEX:L0001]]",
        })
        source_ids = ["block_001"]
        if group == "task_minimal":
            selected = [
                fact for fact in record["facts"]
                if fact["field"] in {"event", "date", "amount", "evidence"}
            ]
            payload = "；".join(fact["text"] for fact in selected)
            source_ids = sorted({source for fact in selected for source in fact["source_ids"]})
    output = {
        "case_id": record["id"],
        "group": group,
        "payload": payload,
        "source_ids": source_ids,
        "experimental_only": True,
        "legal_necessity_determined": False,
    }
    output["output_hash"] = digest(output)
    return output


def run_mock_comparison(records: list[dict], manifest: dict) -> dict:
    frozen = freeze_mock_corpus(
        records,
        seed=manifest["seed"],
        dependency_hash=manifest.get("dependency_hash", "unrecorded"),
        generator_version=manifest.get("generator_version", "lexaegis.mock_labor.v1"),
    )
    if manifest.get("freeze_hash") != frozen["freeze_hash"]:
        raise ValueError("数据、划分或冻结配置已经变化")
    aggregates = {}
    group_hashes = {}
    for group in GROUPS[:-1]:
        outputs = [transform_mock_record(record, group) for record in records]
        exposures = []
        for record, output in zip(records, outputs):
            identifiers = record["technical_truth"]["direct_identifiers"]
            exposures.append(sum(item["value"] in output["payload"] for item in identifiers))
        aggregates[group] = {
            "outcome": "measured_on_mock_technical_truth",
            "case_count": len(outputs),
            "mean_payload_characters": sum(len(item["payload"]) for item in outputs) / len(outputs),
            "direct_identifier_exposure_count": sum(exposures),
            "source_traceability_rate": sum(bool(item["source_ids"]) for item in outputs) / len(outputs),
            "process_cost_proxy": {
                "outcome": "measured_operation_count_not_human_time",
                "review_item_count": len(outputs),
                "transform_operation_count": (
                    0 if group == "original"
                    else sum(len(record["technical_truth"]["direct_identifiers"]) for record in records)
                    if group in {"find_replace", "consistent_pseudonym"}
                    else sum(len(record["facts"]) - 4 for record in records)
                ),
            },
        }
        group_hashes[group] = digest(outputs)

    vectors = [record["technical_truth"]["feature_vector"] for record in records]
    feature_schema = records[0]["technical_truth"]["feature_schema"]
    ianvs = run_ianvs_profile({
        "vectors": vectors,
        "input_model_hash": "sha256:" + digest({
            "generator": "lexaegis.synthetic_structured_features.v1",
            "feature_schema": feature_schema,
        }),
    }, seed=manifest["seed"], target_dim=2)
    aggregates["ianvs_experimental"] = {
        "outcome": "separate_vector_experiment",
        "case_count": len(records),
        "direct_identifier_exposure": {
            "outcome": "not_applicable",
            "detail": "向量反演需要真实目标模型与冻结攻击协议，不能以文本查找代替",
        },
        "distance_metrics": {
            item["algorithm"]: item.get("metrics", {})
            for item in ianvs["transforms"]
            if item["algorithm"] in {"jl", "random_projection", "pca"}
        },
        "process_cost_proxy": {
            "outcome": "not_comparable_to_text_workflow",
            "detail": "仅记录算法产物哈希；未测量人工流程耗时",
        },
    }
    group_hashes["ianvs_experimental"] = ianvs["report_hash"]
    core = {
        "schema_version": 1,
        "dataset_freeze_hash": manifest["freeze_hash"],
        "status": "complete_technical_mock_only",
        "groups": aggregates,
        "group_output_hashes": group_hashes,
        "legal_task_utility": {
            "outcome": "not_applicable",
            "detail": "法学方案和双人独立标注尚未完成，不生成或推断法律可用性分数",
        },
        "membership_inference": ianvs["membership_metrics"],
        "production_dispatch": False,
    }
    return {**core, "report_hash": digest(core)}
