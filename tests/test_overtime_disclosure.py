import json
from pathlib import Path

from lexaegis.disclosure import (
    LAWYER_LAW_ARTICLE,
    LAWYER_LAW_DATE,
    LAWYER_LAW_MAPPING,
    SEPARATE_JUDGMENT_NOTE,
    apply_candidate_transform,
    build_disclosure_decision,
    constraint_reasons,
    infer_sub_purpose,
    month_truncated,
    resolve_conditional_rule,
)
from lexaegis.policy import transform
from lexaegis.registry import validate_pack
from lexaegis.service import create_task
from tests.test_workflow import formal_material


def labor_pack():
    raw = json.loads((Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
    pack = validate_pack(raw)
    assert pack.dispatch_allowed is False
    assert pack.legal_status == "pending_legal_review"
    return pack.model_dump()


def _fallback(field="date"):
    return {"necessity": "uncertain", "transform": "delete", "reason": "未定义适用规则", "forbidden": False}


def _date_fact(**extra):
    fact = {
        "id": "f_date",
        "field": "date",
        "value": "劳动者主张2025年3月12日加班3小时",
        "source_ids": ["b1"],
        "confirmed": True,
        "hours": 3,
    }
    fact.update(extra)
    return fact


def test_upgraded_pack_stays_draft_and_valid():
    pack = labor_pack()
    assert pack["disclosure_rules"]
    assert pack["dispatch_allowed"] is False
    assert all(item["citation_status"] == "draft_reference" for item in pack["legal_sources"])
    lawyer = next(item for item in pack["legal_sources"] if item["id"] == "lawyer_law_2026_09_01")
    assert "第41条" in lawyer["articles"]
    assert lawyer["historical_mapping"]["2017_article_38"] == "2026-09-01第41条"


def test_overtime_rule_requires_known_day_nature():
    pack = labor_pack()
    fact = _date_fact()
    resolved = resolve_conditional_rule(pack, fact, "fact_summary", "核对加班")
    assert resolved is not None
    assert "day_nature_known" in resolved["unknown_conditions"]
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), "核对加班", [fact])
    assert decision["status"] == "review"
    assert decision["necessity"] == "uncertain"
    assert decision["transform"] == "delete"
    assert any("条件未知" in item for item in decision["block_reasons"])


def test_empty_or_unknown_condition_goes_to_review():
    pack = labor_pack()
    for day_nature in (None, "", "unknown"):
        fact = _date_fact(day_nature=day_nature)
        decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), "核对加班", [fact])
        assert decision["status"] == "review"
        assert decision["necessity"] == "uncertain"


def test_overtime_date_keeps_calendar_day_when_conditions_known():
    pack = labor_pack()
    fact = _date_fact(day_nature="weekday", claim_stance="claim")
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), "核对加班", [fact])
    assert decision["status"] == "candidate"
    assert decision["necessity"] == "conditional"
    assert "2025年3月12日" in decision["output"]
    assert not month_truncated(fact["value"], decision["output"])
    assert decision["selected_candidate_id"] == "original_precision"


def test_default_transform_does_not_truncate_date_to_month():
    pack = labor_pack()
    fact = _date_fact(day_nature="rest_day", hours=3)
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback("date"), "核对加班", [fact])
    generalized = transform(fact["value"], "generalize", {})
    moderate = apply_candidate_transform(fact["value"], "moderate_generalize", {})
    assert "2025年3月" in generalized and "12日" not in generalized
    assert "2025年3月12日" in moderate
    assert "2025年3月12日" in decision["output"]
    keep = next(item for item in decision["candidates"] if item["kind"] == "moderate_generalize")
    assert keep["allowed"]
    assert "2025年3月12日" in keep["output"]


def test_month_truncation_and_calendar_shift_rejected():
    pack = labor_pack()
    fact = _date_fact(day_nature="holiday", hours=3)
    rule = next(item for item in pack["disclosure_rules"] if item["id"] == "overtime_date")
    truncated = {"id": "bad_month", "kind": "moderate_generalize", "transform": "generalize", "output": "劳动者主张2025年3月加班3小时"}
    shifted = {"id": "bad_shift", "kind": "original_precision", "transform": "keep", "output": "劳动者主张2025年3月13日加班3小时"}
    assert any("截到月份" in item for item in constraint_reasons(fact, truncated, rule, {}, [fact]))
    assert any("平移日历" in item for item in constraint_reasons(fact, shifted, rule, {}, [fact]))


def test_candidate_hard_constraint_rejects_subject_and_negation_loss():
    pack = labor_pack()
    worker = {"id": "f1", "field": "entity", "value": "林甲", "subject_role": "worker", "confirmed": True}
    employer = {"id": "f2", "field": "entity", "value": "星桥示例科技有限公司", "subject_role": "employer", "confirmed": True}
    event = {
        "id": "f3", "field": "event", "value": "用人单位否认林甲加班3小时",
        "claim_stance": "deny", "hours": 3, "negated": True, "confirmed": True,
    }
    mappings = [
        {"original_value": "林甲", "wire_token": "[[LEX:P0001]]"},
        {"original_value": "星桥示例科技有限公司", "wire_token": "[[LEX:P0002]]"},
    ]
    swap = {"id": "swap", "kind": "tokenize", "transform": "pseudonymize", "output": "星桥示例科技有限公司"}
    flattened = {"id": "flat", "kind": "original_precision", "transform": "keep", "output": "林甲加班3小时"}
    entity_rule = next(item for item in pack["disclosure_rules"] if item["id"] == "overtime_entity")
    claim_rule = next(item for item in pack["disclosure_rules"] if item["id"] == "overtime_claim_stance")
    assert any("主体" in item for item in constraint_reasons(worker, swap, entity_rule, mappings, [worker, employer]))
    assert any("否认" in item or "主张" in item for item in constraint_reasons(event, flattened, claim_rule, mappings, [event]))


def test_processing_basis_judgments_are_separate_and_lawyer_law_uses_2026_article():
    pack = labor_pack()
    fact = _date_fact(day_nature="weekday", confidentiality_category="party_privacy", subject_category="natural_person")
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), "核对加班", [fact])
    basis = decision["processing_basis"]
    assert "safety_score" not in basis
    assert basis["necessity_judgment"] != basis["processability_judgment"] or basis["residual_risk_judgment"] != basis["necessity_judgment"]
    assert basis["processability_judgment"] == "review"
    secrecy = decision["confidentiality"]
    assert secrecy["lawyer_law_article"] == LAWYER_LAW_ARTICLE
    assert secrecy["lawyer_law_text_date"] == LAWYER_LAW_DATE
    assert LAWYER_LAW_MAPPING in secrecy["lawyer_law_mapping_note"]
    assert "38" not in (secrecy["lawyer_law_article"] or "")


def test_infer_sub_purpose_and_generic_facts_stay_conservative():
    generic = {"id": "g1", "field": "event", "value": "劳动者林甲主张工资12000元。"}
    assert infer_sub_purpose([generic], "fact_summary") is None
    pack = labor_pack()
    decision = build_disclosure_decision(generic, pack, "fact_summary", {}, _fallback("event"), None, [generic])
    assert decision["necessity"] == "uncertain"
    assert decision["transform"] == "delete"
    assert decision["rule_id"] is None


def test_dispatch_still_blocked_for_complete_overtime_scenario(env):
    case, document, _ = formal_material(env)
    block = document["ir"]["blocks"][0]
    client = env["client"]
    payload = {
        "field": "date",
        "value": "劳动者主张2025年3月12日加班3小时，用人单位否认。",
        "source_ids": [block["id"]],
        "confirmed": True,
        "claim_stance": "claim",
        "day_nature": "weekday",
        "hours": 3,
        "wage_base": "12000",
        "evidence_holder": "worker",
        "evidence_attribution": "打卡记录由劳动者持有",
        "confidentiality_category": "party_privacy",
    }
    assert client.post(f"/api/v1/cases/{case['id']}/facts", json=payload).status_code == 200
    created = client.post(f"/api/v1/cases/{case['id']}/tasks", json={"transport": "cloud", "sub_purpose": "核对加班"})
    assert created.status_code == 200, created.text
    task = created.json()
    assert task["sub_purpose"] == "核对加班"
    date_decision = next(item for item in task["decisions"] if item["field"] == "date")
    assert date_decision["candidates"]
    assert "2025年3月12日" in (date_decision["output"] or date_decision["candidates"][0]["output"] or "")
    evaluated = client.post(f"/api/v1/tasks/{task['id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.json()
    assert body["risk"]["approval_allowed"] is False
    assert any("尚未正式发布" in item for item in body["risk"]["blockers"])
    assert SEPARATE_JUDGMENT_NOTE in body["risk"]["findings"]
    with env["app"].state.store.transaction() as repo:
        pack = repo.get(task["pack_id"], "pack")
        assert pack["dispatch_allowed"] is False
        assert pack["legal_status"] == "pending_legal_review"
    assert client.post(
        f"/api/v1/tasks/{task['id']}/approve",
        json={"request_hash": body["request_hash"]},
    ).status_code == 409


def test_create_task_wires_overtime_overlay(env):
    case, document, _ = formal_material(env)
    block = document["ir"]["blocks"][0]
    env["client"].post(f"/api/v1/cases/{case['id']}/facts", json={
        "field": "day_nature", "value": "工作日", "source_ids": [block["id"]], "confirmed": True, "day_nature": "weekday",
    })
    with env["app"].state.store.transaction() as repo:
        task = create_task(repo, case["id"], "local", "fact_summary")
    assert task["sub_purpose"] == "核对加班"
    nature = next(item for item in task["decisions"] if item["field"] == "day_nature")
    assert nature["necessity"] == "conditional"
    assert nature["status"] == "candidate"


def test_sensitivity_forbid_outbound_clears_cloud_output():
    pack = labor_pack()
    fact = _date_fact(sensitivity_label="禁止外发", day_nature="weekday")
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), "核对加班", [fact])
    assert decision["transform"] == "delete"
    assert decision["output"] == ""
    assert decision["forbidden"] is True
    assert decision["sensitivity_label"] == "forbid_outbound"
    assert any("禁止外发" in item for item in decision["block_reasons"])


def test_sensitivity_human_review_stays_review():
    pack = labor_pack()
    fact = {"id": "f_name", "field": "entity", "value": "某劳动者", "source_ids": ["b1"], "confirmed": True,
            "sensitivity_label": "转人工"}
    decision = build_disclosure_decision(fact, pack, "fact_summary", {}, _fallback(), None, [fact])
    assert decision["status"] == "review"
    assert decision["transform"] == "delete"
    assert decision["output"] == ""
    assert any("转人工" in item for item in decision["block_reasons"])


def test_sensitivity_must_keep_on_fallback_only():
    pack = labor_pack()
    mappings = {"某公司": "[[LEX:P0001]]"}
    fact = {"id": "f_rel", "field": "relation", "value": "某公司劳动关系", "source_ids": ["b1"], "confirmed": True,
            "sensitivity_label": "必须保留"}
    decision = build_disclosure_decision(fact, pack, "fact_summary", mappings, _fallback(), None, [fact])
    assert decision["necessity"] == "required"
    assert decision["transform"] == "keep"
    assert decision["output"] == "某公司劳动关系"


def test_sensitivity_must_keep_does_not_override_overtime_rule():
    pack = labor_pack()
    mappings = {"李某": "[[LEX:P0001]]"}
    fact = {
        "id": "f_ent", "field": "entity", "value": "李某", "source_ids": ["b1"], "confirmed": True,
        "sensitivity_label": "必须保留", "day_nature": "weekday",
    }
    decision = build_disclosure_decision(fact, pack, "fact_summary", mappings, _fallback(), "核对加班", [fact])
    assert decision["rule_id"] == "overtime_entity"
    assert decision["transform"] == "pseudonymize"
    assert decision["output"] == "[[LEX:P0001]]"
