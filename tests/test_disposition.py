from lexaegis.d_path import LAYER_B_CLOSED, UNJUDGED_COMBINATION
from lexaegis.outbound_gate import (
    ATTACKS_NOT_RESISTED,
    G0,
    G2,
    G5,
    G7,
    KIND_ENGINEERING,
    KIND_MINIMIZATION,
    KIND_PROHIBITION,
    KIND_VERIFICATION,
    PACK_UNPUBLISHED,
    classify_kind,
    derive_disposition,
    product_dispatch_state,
)
from lexaegis.policy import assess
from tests.test_outbound_gate import _ready, reviewed_pack


def _kinds(result):
    return {(hit["message"], hit.get("kind")) for hit in result.get("gates") or []}


def test_kind_table_and_disposition_do_not_change_blockers():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张未支付劳动报酬。")
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert result["approval_allowed"] is False
    assert PACK_UNPUBLISHED in result["blockers"]
    assert UNJUDGED_COMBINATION in result["blockers"]
    assert ATTACKS_NOT_RESISTED in result["blockers"]
    assert result["disposition"] == "needs_verification"
    assert result["system_readiness"] == "not_ready"
    kinds = {hit["id"]: hit["kind"] for hit in result["gates"]}
    assert kinds[G5] == KIND_ENGINEERING
    assert kinds[G7] == KIND_VERIFICATION


def test_direct_identifier_is_minimization():
    case, facts, decisions, docs = _ready("劳动者张三主张解除。")
    result = assess(case, {"forbidden_terms": []}, facts, decisions, docs, [], "local")
    assert any(hit["kind"] == KIND_MINIMIZATION and hit["message"].startswith("仍包含直接标识") for hit in result["gates"])
    assert result["approval_allowed"] is False
    assert result["disposition"] == "needs_minimization"


def test_forbidden_terms_are_verification_not_prohibition():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]为唯一岗位并公开获奖。")
    result = assess(case, {"forbidden_terms": ["唯一", "公开获奖"]}, facts, decisions, docs, [], "local")
    assert any("组合线索风险" in hit["message"] and hit["kind"] == KIND_VERIFICATION for hit in result["gates"])
    assert not any(hit["kind"] == KIND_PROHIBITION for hit in result["gates"])
    assert result["approval_allowed"] is False


def test_layer_b_is_engineering():
    assert classify_kind(G2, LAYER_B_CLOSED) == KIND_ENGINEERING


def test_incomplete_prohibition_finding_stays_blocked_as_verification():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。")
    case["prohibition_findings"] = [{
        "category": "state_secret",
        "protected_object_confirmed": True,
        "rule_prohibits_current_act": False,
        "applies_to_current_context": False,
        "minimization_insufficient": False,
        "legal_source_ids": [],
    }]
    result = assess(case, reviewed_pack(), facts, decisions, docs, [], "local")
    assert result["approval_allowed"] is False
    assert result["disposition"] == "needs_verification"
    assert any(hit["id"] == G0 and "四要件未完成确认" in hit["message"] for hit in result["gates"])


def test_complete_prohibition_finding_is_prohibited_and_still_blocked():
    pack = reviewed_pack()
    pack["legal_sources"] = [{
        "id": "state_secret_law", "title": "中华人民共和国保守国家秘密法",
        "articles": ["第31条"], "rule_nature": "statutory", "granularity": "article",
        "citation_status": "draft_reference",
    }]
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。")
    case["prohibition_findings"] = [{
        "category": "state_secret",
        "protected_object_confirmed": True,
        "rule_prohibits_current_act": True,
        "applies_to_current_context": True,
        "minimization_insufficient": True,
        "legal_source_ids": ["state_secret_law"],
    }]
    result = assess(case, pack, facts, decisions, docs, [], "local")
    assert result["approval_allowed"] is False
    assert result["disposition"] == "prohibited"
    assert any(hit["kind"] == KIND_PROHIBITION for hit in result["gates"])


def test_derive_disposition_ignores_engineering_for_legal_state():
    gates = [
        {"id": G5, "message": PACK_UNPUBLISHED, "kind": KIND_ENGINEERING},
        {"id": G0, "message": "仍包含未替换的登记主体", "kind": KIND_MINIMIZATION},
    ]
    disposition, readiness = derive_disposition(gates)
    assert disposition == "needs_minimization"
    assert readiness == "not_ready"


def test_product_latch_unchanged():
    assert product_dispatch_state() == "blocked"
