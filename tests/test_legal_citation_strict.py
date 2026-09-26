"""Legal-citation strictness for the G5 publication gate (spec 2.4)."""
import json
from pathlib import Path

from lexaegis.outbound_gate import (
    CITATION_NO_STATUTORY,
    CITATION_SUPERSEDED,
    CITATION_UNRESOLVED,
    citation_blockers,
    collect_outbound_blockers,
    validate_formal_gate,
)


def _src(sid, nature="statutory", granularity="article", status="draft_reference",
         articles=None, historical=None):
    return {
        "id": sid, "title": "测试法源", "articles": articles or ["第1条"],
        "citation_status": status, "rule_nature": nature,
        "granularity": granularity, "historical_mapping": historical or {},
    }


def _pack(legal_sources, disclosure_rules=None, sensitive=None, unresolved=None):
    return {
        "legal_sources": legal_sources,
        "disclosure_rules": disclosure_rules or [],
        "sensitive_object_rules": sensitive or [],
        "unresolved_citations": unresolved or [],
    }


def test_unresolved_reference_blocks_g5():
    pack = _pack(
        [_src("s1")],
        disclosure_rules=[{"id": "r1", "legal_source_ids": ["missing_source"]}],
    )
    blockers = citation_blockers(pack)
    assert any(m.startswith(CITATION_UNRESOLVED) for m in blockers)


def test_standard_only_citation_cannot_stand_alone():
    pack = _pack(
        [_src("s1", nature="standard_reference"),
         _src("s2", nature="statutory", granularity="instrument_scope")],
        disclosure_rules=[{"id": "r1", "legal_source_ids": ["s1", "s2"]}],
    )
    blockers = citation_blockers(pack)
    assert any(m.startswith(CITATION_NO_STATUTORY) for m in blockers)


def test_article_statutory_plus_standard_supplement_passes():
    pack = _pack(
        [_src("s1"), _src("s2", nature="standard_reference")],
        disclosure_rules=[{"id": "r1", "legal_source_ids": ["s1", "s2"]}],
    )
    assert citation_blockers(pack) == []


def test_empty_citation_section_is_not_flagged():
    pack = _pack([_src("s1")],
                 sensitive=[{"id": "pi1", "legal_source_ids": []}])
    assert citation_blockers(pack) == []


def test_pack_level_and_item_level_unresolved_citations():
    pack = _pack([_src("s1")], unresolved=["old:text:conflict"])
    assert any(m.startswith(CITATION_UNRESOLVED) for m in citation_blockers(pack))
    pack2 = _pack([_src("s1")],
                  sensitive=[{"id": "pi1", "legal_source_ids": ["s1"],
                              "unresolved_citations": ["v1-v2 text differs"]}])
    assert any(m.startswith(CITATION_UNRESOLVED) for m in citation_blockers(pack2))


def test_superseded_source_status_blocks():
    pack = _pack(
        [_src("s1"), _src("s_old", status="superseded")],
        disclosure_rules=[{"id": "r1", "legal_source_ids": ["s1", "s_old"]}],
    )
    assert any(m.startswith(CITATION_SUPERSEDED) for m in citation_blockers(pack))


def test_superseded_article_number_in_own_articles_blocks():
    dead = _src("lawyer", articles=["第38条"],
                historical={"2017_article_38": "2026-09-01第41条"})
    pack = _pack([dead])
    assert any(m.startswith(CITATION_SUPERSEDED) for m in citation_blockers(pack))
    live = _src("lawyer", articles=["第41条"],
                historical={"2017_article_38": "2026-09-01第41条"})
    assert citation_blockers(_pack([live])) == []


def test_gate_collect_and_validate_carry_citation_hits():
    pack = _pack(
        [_src("s1", nature="standard_reference")],
        disclosure_rules=[{"id": "r1", "legal_source_ids": ["s1"]}],
    )
    hits = collect_outbound_blockers({"mode": "formal"}, pack, attacks=[], isolation_verified=True)
    assert any(h["id"] == "G5" and h["message"].startswith(CITATION_NO_STATUTORY) for h in hits)
    assert any(m.startswith(CITATION_NO_STATUTORY) for m in
               validate_formal_gate(pack, [{"status": "pass"}], [], isolation_verified=True))


def test_repo_labor_pack_citation_audit_is_deterministic():
    pack = json.loads(Path("packs/labor_v2_draft.json").read_text(encoding="utf-8"))
    blockers = citation_blockers(pack)
    # Every flagged item must name its rule id so a reviewer can find it.
    for message in blockers:
        assert "：" in message or message == CITATION_UNRESOLVED
