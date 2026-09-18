import copy
import hashlib
from itertools import permutations
from pathlib import Path

import pytest

from lexaegis.legal_assets import (
    LEGAL_ASSET_REGISTRY_ID,
    LEGAL_ASSET_REGISTRY_KIND,
    LegalAssetImportError,
    build_existing_legal_asset_registry,
    group_legal_source_records,
    persist_legal_asset_registry,
)
from lexaegis.storage import Store


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def existing_registry():
    return build_existing_legal_asset_registry(ROOT)


def test_existing_assets_are_imported_with_conservative_states(existing_registry):
    assert existing_registry["legal_source_count"] == 140
    assert len(existing_registry["legal_sources"]) == 140

    kinds = {asset["kind"] for asset in existing_registry["assets"]}
    assert {
        "merged_legal_catalog",
        "rule_specification",
        "outbound_gate_table",
        "handoff_template",
        "signature_workbook",
        "approval_design",
        "labor_draft_pack",
        "current_template",
    } <= kinds

    design = next(asset for asset in existing_registry["assets"] if asset["kind"] == "approval_design")
    assert design["state"] == "design_only"
    assert design["conclusion"] == "unknown"
    assert all(
        asset["state"] == "unknown"
        for asset in existing_registry["assets"]
        if asset["kind"] in {"handoff_template", "signature_workbook", "current_template"}
    )
    assert any(
        "unknown" in row["source_fields"].values()
        for row in existing_registry["legal_sources"]
    )


def test_every_legal_source_row_keeps_the_catalog_asset_and_source_hash(existing_registry):
    assets = {asset["asset_id"]: asset for asset in existing_registry["assets"]}
    for row in existing_registry["legal_sources"]:
        assert row["source_assets"]
        for pointer in row["source_assets"]:
            assert pointer["asset_id"] in assets
            assert pointer["content_hash"] == assets[pointer["asset_id"]]["content_hash"]
            assert pointer["content_hash"].startswith("sha256:")


@pytest.mark.parametrize("missing_field", ["asset_id", "content_hash"])
def test_missing_row_provenance_rejects_the_complete_import_atomically(
    tmp_path, existing_registry, missing_field
):
    store = Store(tmp_path / "registry.sqlite")
    persist_legal_asset_registry(store, existing_registry)
    with store.read() as repo:
        before = repo.get(LEGAL_ASSET_REGISTRY_ID, LEGAL_ASSET_REGISTRY_KIND)

    invalid = copy.deepcopy(existing_registry)
    invalid["legal_sources"][73]["source_assets"][0][missing_field] = ""

    with pytest.raises(LegalAssetImportError, match="缺少来源资产标识或源内容哈希"):
        persist_legal_asset_registry(store, invalid)

    with store.read() as repo:
        after = repo.get(LEGAL_ASSET_REGISTRY_ID, LEGAL_ASSET_REGISTRY_KIND)
    assert after == before


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legal_source(
    record_id: str,
    *,
    title: str = "《测试法》",
    articles: list[str] | None = None,
    provision_text: str = "同一条文",
    version_note: str = "现行版本",
    source_name: str | None = None,
) -> dict:
    source_name = source_name or record_id
    source_hash = _digest(f"asset:{source_name}")
    provision_hash = _digest(provision_text)
    return {
        "id": record_id,
        "canonical_title": title,
        "articles": articles or ["第2条", "第1条"],
        "provision_hash": provision_hash,
        "provision_text_ref": provision_hash,
        "effective_from": "2026-01-01",
        "effective_to": "unknown",
        "citation_status": "draft_reference",
        "rule_nature": "statutory",
        "granularity": "article",
        "source_assets": [
            {
                "asset_id": f"asset:{source_name}",
                "content_hash": source_hash,
                "source_path": f"legal/sources/{source_name}.json",
            }
        ],
        "source_fields": {
            "version_note": version_note,
            "snapshot": "unknown",
        },
    }


def _group_projection(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    grouped, duplicates, variants = group_legal_source_records(records)
    row_states = sorted(
        (
            {
                "id": row["id"],
                "duplicate_group_id": row.get("duplicate_group_id"),
                "variant_group_id": row.get("variant_group_id"),
                "variant_status": row.get("variant_status"),
                "canonical_conclusion": row.get("canonical_conclusion"),
                "source_assets": row["source_assets"],
            }
            for row in grouped
        ),
        key=lambda row: row["id"],
    )
    return row_states, duplicates, variants


def test_exact_duplicates_share_stable_group_and_keep_each_source_pointer():
    first = _legal_source(
        "source-a",
        title=" 《测试法》 ",
        articles=["第2条、第1条"],
        source_name="catalog-a",
    )
    second = _legal_source(
        "source-b",
        articles=["第1条", "第2条"],
        source_name="catalog-b",
    )

    original = copy.deepcopy([first, second])
    grouped, duplicates, variants = group_legal_source_records([first, second])

    assert [first, second] == original
    assert len(duplicates) == 1
    assert variants == []
    duplicate = duplicates[0]
    assert duplicate["member_record_ids"] == ["source-a", "source-b"]
    assert [link["record_id"] for link in duplicate["source_links"]] == [
        "source-a",
        "source-b",
    ]
    assert {
        link["source_assets"][0]["asset_id"] for link in duplicate["source_links"]
    } == {"asset:catalog-a", "asset:catalog-b"}
    assert all(
        row["duplicate_group_id"] == duplicate["id"] for row in grouped
    )


def test_same_title_and_articles_preserve_text_and_version_variants_as_pending():
    exact_a = _legal_source("a", source_name="catalog-a")
    exact_b = _legal_source("b", source_name="catalog-b")
    changed_text = _legal_source(
        "text-variant",
        provision_text="不同条文",
        source_name="catalog-text",
    )
    changed_version = _legal_source(
        "version-variant",
        version_note="历史版本",
        source_name="catalog-version",
    )

    grouped, duplicates, variants = group_legal_source_records(
        [exact_a, changed_text, exact_b, changed_version]
    )

    assert len(grouped) == 4
    assert len(duplicates) == 1
    assert len(variants) == 1
    variant = variants[0]
    assert variant["member_record_ids"] == [
        "a",
        "b",
        "text-variant",
        "version-variant",
    ]
    assert variant["status"] == "pending"
    assert variant["canonical_conclusion"] == "pending"
    assert variant["conflict_reasons"] == [
        "provision_text",
        "version_metadata",
    ]
    assert all(row["variant_status"] == "pending" for row in grouped)
    assert all(row["canonical_conclusion"] == "pending" for row in grouped)
    assert {row["id"] for row in grouped} == {
        "a",
        "b",
        "text-variant",
        "version-variant",
    }


def test_duplicate_and_variant_grouping_is_independent_of_input_order():
    records = [
        _legal_source("a", source_name="catalog-a"),
        _legal_source("b", source_name="catalog-b"),
        _legal_source(
            "text-variant",
            provision_text="不同条文",
            source_name="catalog-text",
        ),
        _legal_source(
            "version-variant",
            version_note="历史版本",
            source_name="catalog-version",
        ),
    ]
    expected = _group_projection(records)

    for ordered_records in permutations(records):
        assert _group_projection(list(ordered_records)) == expected


def test_lawyer_law_article_38_is_retained_as_time_bounded_history(existing_registry):
    historical = next(
        row
        for row in existing_registry["legal_sources"]
        if row["id"] == "ls_014_d94ad0e714"
    )

    assert historical["canonical_title"] == "《中华人民共和国律师法》"
    assert historical["articles"] == ["第38条"]
    assert historical["citation_status"] == "historical"
    assert historical["effective_from"] == "2008-06-01"
    assert historical["effective_to"] == "2026-08-31"
    assert historical["source_fields"]["provision_text"].startswith("第三十八条")
    assert historical["temporal_mapping_ids"] == [
        "citation-mapping:lawyer-law:38-to-41:2026-09-01"
    ]


def test_lawyer_law_article_41_mapping_uses_existing_amendment_evidence_and_stays_pending(
    existing_registry,
):
    mapping = next(
        item
        for item in existing_registry["citation_mappings"]
        if item["id"] == "citation-mapping:lawyer-law:38-to-41:2026-09-01"
    )
    basis_asset = next(
        asset
        for asset in existing_registry["assets"]
        if asset["source_path"]
        == "docs/legal/案隐盾_系统法学规则与验收标准_v1.0.md"
    )

    assert mapping == {
        "id": "citation-mapping:lawyer-law:38-to-41:2026-09-01",
        "instrument": "《中华人民共和国律师法》",
        "from_article": "第38条",
        "to_article": "第41条",
        "effective_from": "2026-09-01",
        "mapping_basis": "amendment_sequence",
        "basis_artifact_hash": basis_asset["content_hash"],
        "status": "pending",
        "note": (
            "依据现有律师法修改决定及条文顺序调整记录推算；"
            "未取得修订后重新公布的完整文本，不得标记为现行第41条全文已逐字核验。"
        ),
    }
    assert not any(
        row["canonical_title"] == "《中华人民共和国律师法》"
        and row["articles"] == ["第41条"]
        for row in existing_registry["legal_sources"]
    )
