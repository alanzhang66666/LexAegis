"""Deterministic synthetic corpus and blind-comparison scaffolding.

The included records are conspicuously fictional. They provide technical
anchors and direct-identifier truth only; legal necessity and legal utility
remain unlabelled until the legal study protocol is approved.
"""
from __future__ import annotations

import json
import random
import time
from datetime import date
from pathlib import Path

from .experiments import (
    UNSCORED_COMPARABLE,
    aggregate_comparable_rows,
    assert_honest_comparable_report,
    isolated_identity_probe,
    legal_utility_proxies,
    load_comparable_labels,
    pending_labels_document,
    run_ianvs_profile,
)
from .util import digest


GROUPS = ("original", "find_replace", "consistent_pseudonym", "task_minimal", "ianvs_experimental")
METHOD_GROUPS = (
    "find_replace",
    "consistent_pseudonym",
    "task_matrix",
    "generic_privacy_utility",
    "legal_constraint",
)
COMPARABLE_ARTIFACT_KEYS = (
    "case_id", "group", "payload", "source_ids", "fact_outputs",
    "experimental_only", "legal_necessity_determined", "production_dispatch",
    "latency_ms", "attempt_count", "output_hash",
)
FIND_REPLACE_TABLE = {
    "person_name": "某劳动者",
    "organization": "某用人单位",
    "phone": "[电话已删除]",
    "email": "[邮箱已删除]",
    "address": "[地址已删除]",
}
OVERLAY_NOTE = (
    "加班条件覆盖只从合成原文可核对线索派生（主张字样、日历星期），"
    "不是双人标注，不得当作法学标签。"
)

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


def default_eval_pack_path() -> Path:
    return Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json"


def default_comparable_path(dataset_id: str) -> Path:
    return Path(".data") / "comparable" / f"{dataset_id}.json"


def load_eval_pack(path: Path | None = None) -> dict:
    from .registry import validate_pack
    raw = json.loads((path or default_eval_pack_path()).read_text(encoding="utf-8"))
    pack = validate_pack(raw).model_dump()
    if pack.get("dispatch_allowed") is not False:
        raise ValueError("评测案由包 dispatch_allowed 必须为 false")
    return pack


def task_matrix_fallback(pack: dict, task_type: str, field: str) -> dict:
    fallback = {"necessity": "uncertain", "transform": "delete", "reason": "未定义适用规则", "forbidden": False}
    rules = {item["field"]: item for item in pack.get("rules") or []}
    if pack.get("schema_version") == 2:
        matrix = [item for item in pack.get("task_field_matrix") or [] if item.get("task_id") == task_type]
        if not matrix:
            return {**fallback, "reason": "任务字段矩阵缺失，按保守策略处理"}
        item = next((row for row in matrix if row.get("field") == field), None)
        if not item:
            return {**fallback, "reason": "字段未出现在任务矩阵中，按保守策略处理"}
        rule = rules.get(field, fallback)
        forbidden = bool(rule.get("forbidden"))
        return {
            "necessity": item.get("necessity") or "uncertain",
            "transform": "delete" if forbidden else rule.get("transform") or "delete",
            "reason": item.get("rationale") or rule.get("reason") or fallback["reason"],
            "forbidden": forbidden,
        }
    return rules.get(field, fallback)


def experiment_sub_purpose(record: dict) -> str | None:
    event = next((fact.get("text") or "" for fact in record.get("facts") or [] if fact.get("field") == "event"), "")
    return "核对加班" if "加班" in event else None


def _derived_day_nature(date_text: str) -> str | None:
    try:
        parsed = date.fromisoformat(date_text)
    except ValueError:
        return None
    return "rest_day" if parsed.weekday() >= 5 else "weekday"


def disclosure_facts_from_record(record: dict) -> list[dict]:
    source = _record_text(record)
    overtime = experiment_sub_purpose(record) == "核对加班"
    facts = []
    for fact in record.get("facts") or []:
        item = {
            "id": fact["id"],
            "field": fact["field"],
            "value": fact.get("text") or fact.get("value") or "",
            "source_ids": list(fact.get("source_ids") or []),
        }
        if fact["id"] == "fact_person":
            item["subject_role"] = "worker"
        elif fact["id"] == "fact_employer":
            item["subject_role"] = "employer"
        if overtime:
            if "主张" in source or "提出请求" in source:
                item["claim_stance"] = "claim"
            if fact["field"] == "date":
                day_nature = _derived_day_nature(item["value"])
                if day_nature:
                    item["day_nature"] = day_nature
            if fact["field"] == "evidence":
                item["evidence_attribution"] = item["value"]
        facts.append(item)
    return facts


def mappings_from_record(record: dict) -> list[dict]:
    index = int(str(record["id"]).rsplit("_", 1)[-1])
    entries = []
    for finding in record["technical_truth"]["direct_identifiers"]:
        category = finding["category"]
        if category == "person_name":
            token = f"[[LEX:P{index:04d}]]"
        elif category == "organization":
            token = f"[[LEX:O{index:04d}]]"
        else:
            continue
        entries.append({
            "entity_id": f"entity_{category}_{index:04d}",
            "wire_token": token,
            "original_value": finding["value"],
            "aliases": [],
            "source_ids": [finding.get("source_id") or "block_001"],
        })
    return entries


def _record_text(record: dict) -> str:
    return record["document"]["blocks"][0]["text"]


def _record_index(record: dict) -> int:
    return int(str(record["id"]).rsplit("_", 1)[-1])


def _fact_row(fact, output, transform_name, *, necessity="uncertain", status="candidate",
              selected_candidate_id=None, block_reasons=None, candidate_count=0):
    return {
        "fact_id": fact.get("id"),
        "field": fact.get("field"),
        "output": output,
        "transform": transform_name,
        "necessity": necessity,
        "status": status,
        "selected_candidate_id": selected_candidate_id,
        "block_reasons": list(block_reasons or []),
        "candidate_count": candidate_count,
    }


def _wrap_artifact(record: dict, group: str, payload: str, source_ids: list[str],
                   fact_outputs: list[dict], started: float) -> dict:
    artifact = {
        "case_id": record["id"],
        "group": group,
        "payload": payload,
        "source_ids": sorted(set(source_ids)),
        "fact_outputs": fact_outputs,
        "experimental_only": True,
        "legal_necessity_determined": False,
        "production_dispatch": False,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "attempt_count": 1,
    }
    artifact["output_hash"] = digest({key: value for key, value in artifact.items() if key not in {"output_hash", "latency_ms"}})
    return artifact


def _artifact_find_replace(record: dict, started: float) -> dict:
    raw = _record_text(record)
    payload = _replace_identifiers(raw, record, FIND_REPLACE_TABLE)
    outputs = []
    for fact in record["facts"]:
        outputs.append(_fact_row(fact, _replace_identifiers(fact["text"], record, FIND_REPLACE_TABLE), "find_replace"))
    return _wrap_artifact(record, "find_replace", payload, ["block_001"], outputs, started)


def _pseudonym_table(record: dict) -> dict[str, str]:
    index = _record_index(record)
    return {
        "person_name": f"[[LEX:P{index:04d}]]",
        "organization": f"[[LEX:O{index:04d}]]",
        "phone": f"[[LEX:C{index:04d}]]",
        "email": f"[[LEX:C{index + 20:04d}]]",
        "address": f"[[LEX:L{index:04d}]]",
    }


def _artifact_pseudonym(record: dict, started: float) -> dict:
    table = _pseudonym_table(record)
    raw = _record_text(record)
    payload = _replace_identifiers(raw, record, table)
    outputs = []
    for fact in record["facts"]:
        outputs.append(_fact_row(fact, _replace_identifiers(fact["text"], record, table), "pseudonymize"))
    return _wrap_artifact(record, "consistent_pseudonym", payload, ["block_001"], outputs, started)


def _artifact_task_matrix(record: dict, pack: dict, mappings: list[dict], started: float) -> dict:
    from .disclosure import fallback_decision
    facts = disclosure_facts_from_record(record)
    outputs = []
    parts = []
    source_ids = []
    for fact in facts:
        fallback = task_matrix_fallback(pack, "fact_summary", fact["field"])
        decision = fallback_decision(fact, fallback, mappings)
        outputs.append(_fact_row(
            fact, decision.get("output") or "", decision.get("transform") or "delete",
            necessity=decision.get("necessity") or "uncertain",
            status=decision.get("status") or "candidate",
            block_reasons=decision.get("block_reasons"),
        ))
        if decision.get("output"):
            parts.append(decision["output"])
            source_ids.extend(fact.get("source_ids") or [])
    return _wrap_artifact(record, "task_matrix", "；".join(parts), source_ids, outputs, started)


def _artifact_generic(record: dict, mappings: list[dict], started: float) -> dict:
    from .policy import transform
    raw = _record_text(record)
    payload = transform(raw, "generalize", mappings)
    outputs = []
    contacts = {item["value"] for item in record["technical_truth"]["direct_identifiers"]
                if item["category"] in {"phone", "email", "address"}}
    for fact in record["facts"]:
        method = "delete" if fact["text"] in contacts else "generalize"
        output = transform(fact["text"], method, mappings)
        outputs.append(_fact_row(fact, output, method))
    return _wrap_artifact(record, "generic_privacy_utility", payload, ["block_001"], outputs, started)


def _artifact_legal(record: dict, pack: dict, mappings: list[dict], started: float,
                    *, drop_hard_constraints: bool = False) -> dict:
    from .disclosure import build_disclosure_decision, infer_sub_purpose
    from .policy import transform
    facts = disclosure_facts_from_record(record)
    purpose = infer_sub_purpose(facts, "fact_summary", experiment_sub_purpose(record))
    outputs = []
    parts = []
    source_ids = []
    group = "legal_constraint_no_hard_constraints" if drop_hard_constraints else "legal_constraint"
    for fact in facts:
        fallback = task_matrix_fallback(pack, "fact_summary", fact["field"])
        decision = build_disclosure_decision(fact, pack, "fact_summary", mappings, fallback, purpose, facts)
        if drop_hard_constraints and decision.get("rule_id") and decision.get("status") not in {"review", "restricted"}:
            decision = {
                **decision,
                "output": transform(fact.get("value") or "", "generalize", mappings),
                "transform": "generalize",
                "selected_candidate_id": "unconstrained_generalize",
                "block_reasons": [],
            }
        outputs.append(_fact_row(
            fact, decision.get("output") or "", decision.get("transform") or "delete",
            necessity=decision.get("necessity") or "uncertain",
            status=decision.get("status") or "candidate",
            selected_candidate_id=decision.get("selected_candidate_id"),
            block_reasons=decision.get("block_reasons"),
            candidate_count=len(decision.get("candidates") or []),
        ))
        if decision.get("output"):
            parts.append(decision["output"])
            source_ids.extend(fact.get("source_ids") or [])
    return _wrap_artifact(record, group, "；".join(parts), source_ids, outputs, started)


def emit_comparable_artifact(record: dict, group: str, pack: dict | None = None,
                             mappings: list[dict] | None = None, *,
                             drop_hard_constraints: bool = False) -> dict:
    if group not in METHOD_GROUPS:
        raise ValueError(f"对照只支持五组方法：{', '.join(METHOD_GROUPS)}")
    pack = pack or load_eval_pack()
    mappings = mappings if mappings is not None else mappings_from_record(record)
    started = time.monotonic()
    if group == "find_replace":
        return _artifact_find_replace(record, started)
    if group == "consistent_pseudonym":
        return _artifact_pseudonym(record, started)
    if group == "task_matrix":
        return _artifact_task_matrix(record, pack, mappings, started)
    if group == "generic_privacy_utility":
        return _artifact_generic(record, mappings, started)
    return _artifact_legal(record, pack, mappings, started, drop_hard_constraints=drop_hard_constraints)


def frozen_auxiliary_directory(records: list[dict]) -> list[dict]:
    items = []
    for record in records:
        person = None
        phone = None
        email = None
        for finding in record["technical_truth"]["direct_identifiers"]:
            if finding["category"] == "person_name":
                person = finding["value"]
            elif finding["category"] == "phone":
                phone = finding["value"]
            elif finding["category"] == "email":
                email = finding["value"]
        if not person:
            continue
        items.append({"candidate": person, "clue": phone or ""})
        if email:
            items.append({"candidate": person, "clue": email})
    return items


def identity_label_for(record: dict, labels: dict | None) -> str | None:
    tagged = ((labels or {}).get("records") or {}).get(record["id"]) or {}
    if tagged.get("identity"):
        return tagged["identity"]
    for finding in record.get("technical_truth", {}).get("direct_identifiers") or []:
        if finding.get("category") == "person_name":
            return finding.get("value")
    return None


def _score_artifact(record: dict, artifact: dict, auxiliary: list[dict], labels: dict | None) -> dict:
    identity = identity_label_for(record, labels)
    probe = isolated_identity_probe(artifact["payload"], auxiliary, {"identity": identity} if identity else None)
    proxies = legal_utility_proxies(record, artifact)
    return {
        "case_id": record["id"],
        "group": artifact["group"],
        "split": None,
        "output_hash": artifact["output_hash"],
        "latency_ms": artifact["latency_ms"],
        "attempt_count": artifact["attempt_count"],
        "identity_top1": probe["ranks"]["top1"],
        "identity_topk": probe["ranks"]["topk"],
        "attacker_view_hash": probe["attacker_view_hash"],
        "protocol_outcome": probe["protocol_outcome"],
        "isolation": probe["isolation"],
        **proxies,
    }


def run_comparable_comparison(records: list[dict], manifest: dict, *, labels: dict | None = None,
                              pack: dict | None = None, split: str = "all") -> dict:
    if manifest.get("dispatch_allowed") is not False:
        raise ValueError("对照只接受 dispatch_allowed=false 的评测集")
    frozen = freeze_mock_corpus(
        records,
        seed=manifest["seed"],
        dependency_hash=manifest.get("dependency_hash", "unrecorded"),
        generator_version=manifest.get("generator_version", "lexaegis.mock_labor.v1"),
    )
    if manifest.get("freeze_hash") != frozen["freeze_hash"]:
        raise ValueError("数据、划分或冻结配置已经变化")
    labels = labels or pending_labels_document()
    pack = pack or load_eval_pack()
    auxiliary = frozen_auxiliary_directory(records)
    selected = []
    for record in records:
        bucket = (manifest.get("split") or {}).get(record["id"])
        if split != "all" and bucket != split:
            continue
        selected.append(record)
    if not selected:
        raise ValueError("当前划分没有可对照记录")

    artifacts = {group: [] for group in METHOD_GROUPS}
    rows_by_group = {group: [] for group in METHOD_GROUPS}
    split_rows = {"development": {group: [] for group in METHOD_GROUPS},
                  "blind": {group: [] for group in METHOD_GROUPS}}
    ablation_keep = []
    ablation_drop = []

    for record in selected:
        mappings = mappings_from_record(record)
        bucket = (manifest.get("split") or {}).get(record["id"])
        for group in METHOD_GROUPS:
            artifact = emit_comparable_artifact(record, group, pack, mappings)
            artifacts[group].append(artifact)
            row = _score_artifact(record, artifact, auxiliary, labels)
            row["split"] = bucket
            rows_by_group[group].append(row)
            if bucket in split_rows:
                split_rows[bucket][group].append(row)
        keep = emit_comparable_artifact(record, "legal_constraint", pack, mappings)
        drop = emit_comparable_artifact(record, "legal_constraint", pack, mappings, drop_hard_constraints=True)
        keep_row = _score_artifact(record, keep, auxiliary, labels)
        drop_row = _score_artifact(record, drop, auxiliary, labels)
        ablation_keep.append(keep_row)
        ablation_drop.append(drop_row)

    original_text = _record_text(selected[0])
    original_identity = identity_label_for(selected[0], labels)
    positive = isolated_identity_probe(original_text, auxiliary, {"identity": original_identity} if original_identity else None)
    negative = isolated_identity_probe("", auxiliary, {"identity": original_identity} if original_identity else None)

    groups = {}
    group_hashes = {}
    for group in METHOD_GROUPS:
        groups[group] = aggregate_comparable_rows(rows_by_group[group])
        group_hashes[group] = digest([item["output_hash"] for item in artifacts[group]])
    splits = {
        name: {group: aggregate_comparable_rows(split_rows[name][group]) for group in METHOD_GROUPS}
        for name in ("development", "blind")
        if split == "all" or split == name
    }
    core = {
        "schema_version": 1,
        "profile": "comparable-methods",
        "status": "complete_technical_mock_smoke",
        "scale": "pilot_smoke_n8_not_representative",
        "production_dispatch": False,
        "dataset_id": manifest.get("id") or "mock_labor",
        "dataset_version": manifest.get("version"),
        "dataset_freeze_hash": manifest["freeze_hash"],
        "dispatch_allowed": False,
        "legal_annotation_status": labels.get("status") or manifest.get("legal_annotation_status") or "pending",
        "downstream_model": {
            "outcome": "not_applicable",
            "id": "deterministic_local_transforms",
            "runtime_model_hash": "not_applicable",
            "runtime_prompt_hash": "not_applicable",
            "detail": "五组均为本地确定性变换，未调用下游生成模型；比较的是披露方法而不是模型差异",
        },
        "attack_budget": {
            "kind": "identity",
            "query_budget": 8,
            "k": 3,
            "same_budget_for_all_groups": True,
            "auxiliary": "frozen_local_synthetic_directory",
            "public_search": False,
        },
        "groups": groups,
        "group_output_hashes": group_hashes,
        "splits": splits,
        "artifacts": {
            group: [{key: item[key] for key in COMPARABLE_ARTIFACT_KEYS} for item in artifacts[group]]
            for group in METHOD_GROUPS
        },
        "controls": {
            "positive_identity": {
                "outcome": positive["ranks"]["outcome"],
                "top1": positive["ranks"]["top1"],
                "protocol_outcome": positive["protocol_outcome"],
                "source_hash": digest(original_text),
                "detail": "原文只作本地效用参照和隔离阳性对照，未送公共搜索",
            },
            "negative_identity": {
                "outcome": negative["ranks"]["outcome"],
                "top1": negative["ranks"]["top1"],
                "protocol_outcome": negative["protocol_outcome"],
                "detail": "空披露阳性对照：无候选不得记为 resisted",
            },
        },
        "ablations": {
            "drop_hard_constraints": {
                "question": "去掉法律硬约束、改用通用 generalize，日期或金额关系失败是否增加",
                "keep_hard_constraints": aggregate_comparable_rows(ablation_keep),
                "drop_hard_constraints": aggregate_comparable_rows(ablation_drop),
            }
        },
        "isolation": {
            "attacker_scorer_separated": True,
            "development_blind_split": True,
            "original_text_use": "local_utility_and_isolated_positive_control",
            "public_search": False,
            "labels_status": labels.get("status") or "pending",
            "overlay_note": OVERLAY_NOTE,
        },
        "method_notes": {
            "find_replace": "直接标识查找替换为角色标签或删除标记",
            "consistent_pseudonym": "同一主体在同一记录内使用稳定 token",
            "task_matrix": "当前案由包任务字段矩阵加一般整理缺省，不含加班硬约束候选",
            "generic_privacy_utility": "薄基线：已有 policy.generalize 与联系方式删除，不是新的研究堆栈",
            "legal_constraint": "Phase 2 disclosure.py 有界候选与硬约束；草稿包，非正式法源",
        },
        **UNSCORED_COMPARABLE,
        "annotation_labels": {
            "status": labels.get("status") or "pending",
            "annotator_a": labels.get("annotator_a"),
            "annotator_b": labels.get("annotator_b"),
            "adjudication": labels.get("adjudication"),
            "record_label_count": len((labels.get("records") or {})),
        },
    }
    report = {**core, "report_hash": digest({key: value for key, value in core.items()
                                            if key not in {"artifacts"}})}
    assert_honest_comparable_report(report)
    return report


def run_catalog_comparison(dataset_id: str = "mock_labor", *, labels_path=None,
                           split: str = "all") -> dict:
    from .data_registry import find_dataset
    path, manifest = find_dataset(dataset_id)
    records = read_records_jsonl(path.parent / manifest.records_path)
    labels = load_comparable_labels(labels_path)
    return run_comparable_comparison(records, manifest.model_dump(mode="json"), labels=labels, split=split)
