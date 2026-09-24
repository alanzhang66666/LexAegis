from lexaegis.d_path import LAYER_B_CLOSED, UNJUDGED_COMBINATION, combination_input_hash
from lexaegis.governance import pack_content_hash, publish_pack_record, validate_formal_gate
from lexaegis.outbound_gate import (
    G0,
    G2,
    G3,
    G5,
    G7,
    G8,
    G9,
    EDGE_REVIEW_BLOCKED_PREFIX,
    KIND_VERIFICATION,
    PACK_LEGAL_UNFROZEN,
    PACK_UNPUBLISHED,
    WEIGHTS_UNFROZEN,
    collect_outbound_blockers,
    edge_review_hits,
    product_dispatch_state,
)
from lexaegis.policy import assess


def reviewed_pack():
    return {
        "schema_version": 2,
        "id": "pack:synthetic:1.0",
        "domain_id": "synthetic",
        "name": "纯技术测试包",
        "version": "1.0",
        "status": "reviewed",
        "review_record": "测试审核记录",
        "reviewer": "测试复核人",
        "reviewed_at": "2026-09-05T00:00:00+00:00",
        "references": ["synthetic-reference"],
        "legal_status": "reviewed",
        "dispatch_allowed": True,
        "published_scope": {"technical_test_only": True},
        "risk_weights": {
            "entity": .2, "density": .2, "context": .2,
            "combination": .2, "cross_round": .2,
        },
    }


def _ready(output, *, mode="formal", source_case_id=None, judgment=None):
    case = {
        "mode": mode, "ledger_version": 0, "mapping": {}, "mapping_entries": [],
        "source_case_id": source_case_id,
    }
    if judgment is not None:
        case["combination_judgment"] = judgment
    facts = [{"id": "f1", "confirmed": True, "stale": False, "source_ids": [], "field": "event", "value": output}]
    decisions = [{"fact_id": "f1", "output": output, "necessity": "required", "status": "ready", "forbidden": False}]
    docs = [{"status": "ready", "ir": {"needs_review": False, "blocks": []}}]
    return case, facts, decisions, docs


def _gate_ids(result):
    return {hit["id"] for hit in result.get("gates") or []}


def test_product_dispatch_state_stays_blocked():
    assert product_dispatch_state() == "blocked"


def test_formal_cloud_collects_g5_g7_g8_g9():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张未支付劳动报酬。")
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert result["approval_allowed"] is False
    ids = _gate_ids(result)
    assert {G5, G7, G8, G9} <= ids
    assert PACK_UNPUBLISHED in result["blockers"]
    assert result["blockers"].count(PACK_UNPUBLISHED) == 1
    assert "适用的 V2 法学规则包尚未冻结并正式发布" not in result["blockers"]
    assert WEIGHTS_UNFROZEN in result["blockers"]
    assert PACK_LEGAL_UNFROZEN in result["blockers"]
    assert UNJUDGED_COMBINATION in result["blockers"]
    assert any(hit["id"] == G7 and hit["message"] == UNJUDGED_COMBINATION for hit in result["gates"])


def test_demo_and_local_skip_g2_g5_g7():
    text = "[[LEX:P0001]]主张解除。"
    demo, facts, decisions, docs = _ready(text, mode="demo")
    demo_risk = assess(demo, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "mock")
    assert {G2, G5, G7, G8, G9}.isdisjoint(_gate_ids(demo_risk))
    case, facts, decisions, docs = _ready(text, source_case_id="LA-005")
    local = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "local")
    assert G2 not in _gate_ids(local)
    assert G5 not in _gate_ids(local)
    assert G7 not in _gate_ids(local)
    assert LAYER_B_CLOSED not in local["blockers"]


def test_g2_layer_b_and_g7_forbidden_terms_on_formal_cloud():
    case, facts, decisions, docs = _ready("唯一岗位公开获奖。", source_case_id="LA-005")
    result = assess(
        case,
        {"forbidden_terms": ["唯一", "公开获奖"], "risk_weights": {}},
        facts, decisions, docs, [], "cloud",
    )
    assert LAYER_B_CLOSED in result["blockers"]
    assert any(hit["id"] == G2 for hit in result["gates"])
    assert any(hit["id"] == G7 and "组合线索" in hit["message"] for hit in result["gates"])


def test_g3_provider_fail_and_g8_not_resisted():
    hits = collect_outbound_blockers(
        {"mode": "formal"},
        {
            "schema_version": 2, "status": "published", "content_hash": "x",
            "legal_status": "reviewed", "dispatch_allowed": True,
            "published_scope": {"case": "LA-001"},
            "risk_weights": {key: 0.2 for key in ("entity", "density", "context", "combination", "cross_round")},
        },
        emitted="[[LEX:P0001]]",
        provider_results=[{"status": "fail"}],
        attacks=[{"kind": "identity", "outcome": "succeeded"}],
        isolation_verified=True,
    )
    ids = {hit["id"] for hit in hits}
    assert G3 in ids and G5 in ids and G8 in ids
    assert G9 not in ids


def test_g7_quasi_id_tagged():
    text = "（2024）京01民终123号维持原判。"
    case, facts, decisions, docs = _ready(
        text, judgment={"status": "pass", "input_hash": combination_input_hash(text, "")},
    )
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert any(hit["id"] == G7 and "准标识" in hit["message"] for hit in result["gates"])


def test_validate_formal_gate_wrapper_single_unpublished_line():
    published = publish_pack_record(reviewed_pack(), "named-reviewer")
    attacks = [
        {"kind": kind, "outcome": "resisted"}
        for kind in ("identity", "candidate_set", "sensitive_inference", "cross_round")
    ]
    assert not validate_formal_gate(published, [{"status": "pass"}], attacks, isolation_verified=True)
    published["risk_weights"]["entity"] = 0.9
    blockers = validate_formal_gate(published, [{"status": "pass"}], attacks, isolation_verified=True)
    assert PACK_UNPUBLISHED in blockers
    assert blockers.count(PACK_UNPUBLISHED) == 1
    assert pack_content_hash(published) != published["content_hash"]


def test_edge_review_block_is_g0_not_vendor_g3():
    assert edge_review_hits({"decision": "allow_human_review", "reason": "可复核"}) == []
    hits = edge_review_hits({"decision": "block_external", "reason": "组合线索仍可能重新识别主体"})
    assert len(hits) == 1
    assert hits[0]["id"] == G0
    assert hits[0]["id"] != G3
    assert hits[0]["message"].startswith(EDGE_REVIEW_BLOCKED_PREFIX)
    assert hits[0]["kind"] == KIND_VERIFICATION
