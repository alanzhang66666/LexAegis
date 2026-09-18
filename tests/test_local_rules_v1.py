import json
from pathlib import Path

from lexaegis.disclosure import GENERAL_SUB_PURPOSE, GUIDE_VERSION, infer_sub_purpose
from lexaegis.local_rules import (
    SYN_CASE_ID,
    display_for_purpose,
    evaluate_path_c,
    evaluate_syn_local_001,
    task_result_status,
)
from lexaegis.registry import validate_pack


def labor_pack():
    raw = json.loads((Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
    pack = validate_pack(raw)
    assert pack.dispatch_allowed is False
    assert pack.status == "draft"
    assert pack.legal_status == "pending_legal_review"
    return pack.model_dump()


def test_pack_stays_unpublished_after_v1_spec():
    pack = labor_pack()
    assert pack["version"] == "2.0.0-draft.3"
    assert pack["dispatch_allowed"] is False
    assert any(item["id"] == "local_entity" for item in pack["disclosure_rules"])
    assert GUIDE_VERSION in str(pack["references"])


def test_syn_local_001_local_regression():
    report = evaluate_syn_local_001(labor_pack())
    assert report["case_id"] == SYN_CASE_ID
    assert report["dispatch_allowed"] is False
    assert report["reference_origin"] == "ai_authored"
    assert report["run"] is True
    assert report["passed"], report["failures"]
    assert report["result_status"] in {"complete", "partial"}


def test_path_c_ten_local_cases():
    results = evaluate_path_c(labor_pack())
    assert [item["id"] for item in results] == [1, 2, 3, 4, 5, 6, 7, "8A", "8B", "8C", 9, "10A", "10B"]
    assert all(item["cloud"] is False and item["dispatch_allowed"] is False for item in results)
    failed = [item for item in results if not item["passed"]]
    assert not failed, failed
    by_id = {item["id"]: item for item in results}
    assert by_id["8C"]["result_status"] != "blocked"
    assert by_id["10B"]["result_status"] in {"blocked", "partial"}


def test_month_truncation_blocks_general_and_overtime():
    from lexaegis.disclosure import constraint_reasons
    fact = {"id": "d1", "field": "date", "value": "2023年3月1日解除", "confirmed": True, "source_ids": ["s1"]}
    rule = {"immutable_relations": ["date_relation"], "forbidden_default_transforms": ["date_month_truncation"]}
    candidate = {"kind": "moderate_generalize", "output": "2023年3月解除"}
    reasons = constraint_reasons(fact, candidate, rule, [], [fact])
    assert any("截月" in item and "阻断" in item for item in reasons)


def test_cross_task_display_does_not_rewrite_source():
    source = "2023年3月1日到岗"
    assert "2023年3月1日" in display_for_purpose(source, GENERAL_SUB_PURPOSE)
    assert display_for_purpose(source, "年度材料索引") == "2023年"
    assert source == "2023年3月1日到岗"


def test_required_wipe_is_blocked_not_success():
    assert task_result_status([
        {"necessity": "required", "output": "", "status": "restricted"},
        {"necessity": "conditional", "output": "", "status": "restricted"},
    ]) == "blocked"


def test_one_char_registered_name_does_not_wipe_entity():
    pack = labor_pack()
    facts = [
        {"id": "e1", "field": "entity", "value": "劳动者甲", "subject_role": "worker", "confirmed": True, "source_ids": ["s1"]},
        {"id": "e2", "field": "entity", "value": "X", "subject_role": "third_party", "confirmed": True, "source_ids": ["s1"]},
        {"id": "ev", "field": "event", "value": "劳动者甲提出工资请求", "confirmed": True, "source_ids": ["s1"]},
    ]
    mappings = [
        {"original_value": "劳动者甲", "wire_token": "[[LEX:P0001]]"},
        {"original_value": "X", "wire_token": "[[LEX:P0002]]"},
    ]
    from lexaegis.local_rules import decide_facts
    decisions = decide_facts(facts, pack, mappings, GENERAL_SUB_PURPOSE)
    by_id = {item["fact_id"]: item for item in decisions}
    assert by_id["e1"]["output"] == "[[LEX:P0001]]"
    assert "劳动者甲" not in (by_id["ev"]["output"] or "")


def test_explicit_sub_purpose_required_for_overtime():
    facts = [{"id": "f1", "field": "date", "value": "2025年3月12日加班", "hours": 3, "day_nature": "weekday"}]
    assert infer_sub_purpose(facts, "fact_summary") == GENERAL_SUB_PURPOSE
