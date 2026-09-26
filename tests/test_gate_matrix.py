"""逐门负向矩阵：每个门禁至少一个失败条件的落点与处置分类。

代码门 G0/G2/G3/G5/G7/G8/G9 走 collect_outbound_blockers / edge_review_hits /
prohibition_hits 单一路径；G-product 由 formal_release.evaluate_release 产出；
G1/G4/G6/G10 是纸面门，负向路径是缺有效收据（见 test_formal_release_flow）。
"""
import pytest

from lexaegis.d_path import (
    LAYER_B_CLOSED,
    LAYER_B_CLOSED_IDS,
    UNJUDGED_COMBINATION,
    combination_input_hash,
)
from lexaegis.governance import pack_content_hash
from lexaegis.outbound_gate import (
    G0,
    G2,
    G3,
    G5,
    G7,
    G8,
    G9,
    CITATION_UNRESOLVED,
    EDGE_REVIEW_BLOCKED_PREFIX,
    ISOLATION_UNVERIFIED,
    KIND_ENGINEERING,
    KIND_MINIMIZATION,
    KIND_PROHIBITION,
    KIND_VERIFICATION,
    PACK_LEGAL_UNFROZEN,
    PACK_UNPUBLISHED,
    PROVIDER_INCOMPLETE,
    WEIGHTS_UNFROZEN,
    attach_disposition,
    collect_outbound_blockers,
    derive_disposition,
    edge_review_hits,
    prohibition_hits,
)

OFFICIAL_GATE_IDS = {G0, G2, G3, G5, G7, G8, G9, "G-product"}


def published_pack(**mutations):
    pack = {
        "schema_version": 2, "status": "published",
        "legal_status": "reviewed", "dispatch_allowed": True,
        "published_scope": {"case": "LA-001"},
        "risk_weights": {key: 0.2 for key in ("entity", "density", "context", "combination", "cross_round")},
        "legal_sources": [],
        "forbidden_terms": [],
    }
    pack.update(mutations)
    pack["content_hash"] = pack_content_hash(pack)
    return pack


def clean_case(**overrides):
    case = {"mode": "formal", "ledger_version": 0, "mapping": {},
            "combination_judgment": {"status": "pass",
                                     "input_hash": combination_input_hash("[[LEX:P0001]]", "")}}
    case.update(overrides)
    return case


def resisted_attacks():
    return [{"kind": kind, "outcome": "resisted"}
            for kind in ("identity", "candidate_set", "sensitive_inference", "cross_round")]


def collect(case=None, pack=None, **kwargs):
    kwargs.setdefault("emitted", "[[LEX:P0001]]")
    kwargs.setdefault("provider_results", [{"status": "pass"}])
    kwargs.setdefault("attacks", resisted_attacks())
    kwargs.setdefault("isolation_verified", True)
    return collect_outbound_blockers(case if case is not None else clean_case(),
                                     pack if pack is not None else published_pack(), **kwargs)


@pytest.mark.parametrize(
    ("mutate", "expected_gate", "expected_message", "expected_kind"),
    [
        # G5：未发布 / 法学未冻结 / 权重未冻结 / 法源悬空
        ({"pack": {"status": "draft"}}, G5, PACK_UNPUBLISHED, KIND_ENGINEERING),
        ({"pack": {"legal_status": "draft"}}, G5, PACK_LEGAL_UNFROZEN, KIND_ENGINEERING),
        ({"pack": {"risk_weights": {}}}, G5, WEIGHTS_UNFROZEN, KIND_ENGINEERING),
        ({"pack": {"unresolved_citations": ["labor-law-art"]}}, G5, CITATION_UNRESOLVED, KIND_ENGINEERING),
        # G3：服务商核验未过
        ({"provider_results": [{"status": "pending"}]}, G3, PROVIDER_INCOMPLETE, KIND_ENGINEERING),
        # G8：攻击未全部 resisted
        ({"attacks": [{"kind": "identity", "outcome": "succeeded"}]}, G8, "四类冻结攻击未全部达到 resisted", KIND_ENGINEERING),
        ({"attacks": []}, G8, "四类冻结攻击未全部达到 resisted", KIND_ENGINEERING),
        # G9：隔离未验证
        ({"isolation_verified": False}, G9, ISOLATION_UNVERIFIED, KIND_ENGINEERING),
        # G7：禁用词命中 / 组合判断缺失
        ({"emitted": "唯一岗位", "pack": {"forbidden_terms": ["唯一"]}}, G7, "组合线索风险", KIND_VERIFICATION),
        ({"case": {"combination_judgment": {"status": "missing"}}}, G7, UNJUDGED_COMBINATION, KIND_VERIFICATION),
        # G2：层 B 关闭
        ({"case": {"source_case_id": "LA-002"}}, G2, LAYER_B_CLOSED, KIND_ENGINEERING),
    ],
)
def test_each_gate_lands_on_its_own_negative(mutate, expected_gate, expected_message, expected_kind):
    kwargs = {}
    case = clean_case()
    pack = published_pack()
    for key, patch in mutate.items():
        if key == "pack":
            pack.update(patch)
            pack["content_hash"] = pack_content_hash(pack)
        elif key == "case":
            case.update(patch)
        else:
            kwargs[key] = patch
    hits = collect(case=case, pack=pack, **kwargs)
    matched = [hit for hit in hits if hit["id"] == expected_gate]
    assert matched, f"expected {expected_gate} hit in {hits}"
    assert any(expected_message in hit["message"] for hit in matched)
    assert all(hit["id"] in OFFICIAL_GATE_IDS for hit in hits)


@pytest.mark.parametrize("stable_id", sorted(LAYER_B_CLOSED_IDS))
def test_layer_b_each_closed_case_blocks_g2(stable_id):
    hits = collect(case=clean_case(source_case_id=stable_id))
    assert any(hit["id"] == G2 and hit["message"] == LAYER_B_CLOSED for hit in hits)


@pytest.mark.parametrize("stable_id", ["LA-001", "SMP-010", None])
def test_layer_b_open_cases_do_not_block_g2(stable_id):
    hits = collect(case=clean_case(source_case_id=stable_id))
    assert all(hit["id"] != G2 for hit in hits)


def test_g0_edge_review_block_maps_verification_not_vendor():
    hits = edge_review_hits({"decision": "block_external", "reason": "重新识别风险"})
    assert hits[0]["id"] == G0 and hits[0]["kind"] == KIND_VERIFICATION
    assert hits[0]["message"].startswith(EDGE_REVIEW_BLOCKED_PREFIX)


def test_g0_prohibition_incomplete_and_confirmed():
    pack = {"legal_sources": [{"id": "law1", "rule_nature": "statutory"}]}
    incomplete = {"protected_object_confirmed": True, "legal_source_ids": ["law1"]}
    hits = prohibition_hits({"prohibition_findings": [incomplete]}, pack)
    assert hits[0]["id"] == G0 and "硬性禁止四要件" in hits[0]["message"]
    confirmed = {key: True for key in ("protected_object_confirmed", "rule_prohibits_current_act",
                                      "applies_to_current_context", "minimization_insufficient")}
    confirmed["legal_source_ids"] = ["law1"]
    hits = prohibition_hits({"prohibition_findings": [confirmed]}, pack)
    assert hits[0]["id"] == G0 and hits[0]["kind"] == KIND_PROHIBITION


@pytest.mark.parametrize(
    ("gate_hit", "disposition", "readiness"),
    [
        ({"id": G0, "message": "命中规则硬性禁止项"}, "prohibited", "ready"),
        ({"id": G7, "message": UNJUDGED_COMBINATION}, "needs_verification", "ready"),
        ({"id": G2, "message": "仍包含未替换的登记主体"}, "needs_minimization", "ready"),
        ({"id": G9, "message": ISOLATION_UNVERIFIED}, "allowed", "not_ready"),
    ],
)
def test_disposition_and_readiness_follow_hit_kind(gate_hit, disposition, readiness):
    assert derive_disposition([gate_hit]) == (disposition, readiness)


def test_minimization_message_beats_engineering_readiness_latch():
    risk = {"gates": [
        {"id": G2, "message": "仍包含未替换的登记主体"},
        {"id": G9, "message": ISOLATION_UNVERIFIED},
    ]}
    attach_disposition(risk)
    assert risk["disposition"] == "needs_minimization"
    assert risk["system_readiness"] == "not_ready"


def test_clean_case_produces_zero_blockers():
    assert collect() == []
