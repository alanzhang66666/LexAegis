"""Content-addressed import of the repository's existing legal assets.

The importer is deliberately local-only. It records source bytes, deterministic
exact-duplicate groups, and conservative conflict states. It does not map citations
or infer legal conclusions.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .contracts import LegalSourceRecord
from .storage import Store


LEGAL_ASSET_REGISTRY_ID = "legal-assets:current"
LEGAL_ASSET_REGISTRY_KIND = "legal_asset_registry"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class LegalAssetImportError(ValueError):
    """Raised when an existing-asset import cannot be persisted safely."""


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _media_type(path: Path) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".json": "application/json",
        ".md": "text/markdown",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(path.suffix.lower(), "application/octet-stream")


def _unknown_for_blank(value: Any) -> Any:
    """Preserve structure while representing blank scalar fields as unknown."""
    if value is None or isinstance(value, str) and not value.strip():
        return "unknown"
    if isinstance(value, dict):
        return {key: _unknown_for_blank(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unknown_for_blank(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_group_id(prefix: str, key: Any) -> str:
    digest = hashlib.sha256(_canonical_json(key).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _normalized_title(value: Any) -> str:
    title = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", "", title)


def _normalized_articles(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    normalized: set[str] = set()
    for value in values or ["unknown"]:
        article_scope = re.sub(
            r"\s+", "", unicodedata.normalize("NFKC", str(value)).casefold()
        )
        normalized.update(
            part for part in re.split(r"[、,，;；]+", article_scope) if part
        )
    return sorted(normalized or {"unknown"})


def _version_metadata(row: dict[str, Any]) -> dict[str, str]:
    source_fields = row.get("source_fields")
    if not isinstance(source_fields, dict):
        source_fields = {}
    values = {
        "version": source_fields.get("version", row.get("version", "unknown")),
        "version_note": source_fields.get(
            "version_note", row.get("version_note", "unknown")
        ),
        "effective_from": row.get(
            "effective_from", source_fields.get("effective_from", "unknown")
        ),
        "effective_to": row.get(
            "effective_to", source_fields.get("effective_to", "unknown")
        ),
        "snapshot": source_fields.get("snapshot", row.get("snapshot", "unknown")),
    }
    return {
        key: unicodedata.normalize("NFKC", str(_unknown_for_blank(value))).strip()
        for key, value in values.items()
    }


def _member_source_links(rows: list[dict[str, Any]], indexes: list[int]) -> list[dict[str, Any]]:
    links = []
    for index in indexes:
        row = rows[index]
        pointers = copy.deepcopy(row.get("source_assets", []))
        pointers.sort(
            key=lambda pointer: (
                str(pointer.get("asset_id", "")),
                str(pointer.get("content_hash", "")),
                str(pointer.get("source_path", "")),
            )
        )
        links.append(
            {
                "record_id": str(row.get("id", "unknown")),
                "source_assets": pointers,
            }
        )
    return sorted(
        links,
        key=lambda link: (
            link["record_id"],
            _canonical_json(link["source_assets"]),
        ),
    )


def group_legal_source_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Group exact duplicates and conflicting variants without dropping any row.

    Group identifiers depend only on normalized normative content and version
    metadata. Member/source lists are sorted, so group output is independent of
    input row order while every row retains its own source pointers.
    """
    grouped_rows = copy.deepcopy(records)
    families: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    exact_keys: dict[int, tuple[str, str]] = {}

    for index, row in enumerate(grouped_rows):
        title = _normalized_title(row.get("canonical_title", "unknown"))
        articles = _normalized_articles(row.get("articles", ["unknown"]))
        family_key = (title, tuple(articles))
        version_metadata = _version_metadata(row)
        exact_key = (
            str(row.get("provision_hash", "unknown")),
            _canonical_json(version_metadata),
        )
        row["normalized_title"] = title
        row["normalized_articles"] = articles
        row["version_metadata"] = version_metadata
        row["duplicate_group_id"] = None
        families.setdefault(family_key, []).append(index)
        exact_keys[index] = exact_key

    duplicate_groups: list[dict[str, Any]] = []
    variant_groups: list[dict[str, Any]] = []
    for family_key in sorted(families):
        family_indexes = families[family_key]
        exact_buckets: dict[tuple[str, str], list[int]] = {}
        for index in family_indexes:
            exact_buckets.setdefault(exact_keys[index], []).append(index)

        for exact_key in sorted(exact_buckets):
            duplicate_indexes = exact_buckets[exact_key]
            if len(duplicate_indexes) < 2:
                continue
            duplicate_group_id = _stable_group_id(
                "legal-exact", [family_key, exact_key]
            )
            for index in duplicate_indexes:
                grouped_rows[index]["duplicate_group_id"] = duplicate_group_id
            duplicate_groups.append(
                {
                    "id": duplicate_group_id,
                    "normalized_title": family_key[0],
                    "normalized_articles": list(family_key[1]),
                    "provision_hash": exact_key[0],
                    "version_metadata": json.loads(exact_key[1]),
                    "member_record_ids": sorted(
                        str(grouped_rows[index].get("id", "unknown"))
                        for index in duplicate_indexes
                    ),
                    "source_links": _member_source_links(
                        grouped_rows, duplicate_indexes
                    ),
                }
            )

        if len(exact_buckets) < 2:
            continue
        variant_group_id = _stable_group_id("legal-variant", family_key)
        text_conflict = len({key[0] for key in exact_buckets}) > 1
        version_conflict = len({key[1] for key in exact_buckets}) > 1
        for index in family_indexes:
            grouped_rows[index]["variant_group_id"] = variant_group_id
            grouped_rows[index]["variant_status"] = "pending"
            grouped_rows[index]["canonical_conclusion"] = "pending"
        variant_groups.append(
            {
                "id": variant_group_id,
                "normalized_title": family_key[0],
                "normalized_articles": list(family_key[1]),
                "status": "pending",
                "canonical_conclusion": "pending",
                "conflict_reasons": [
                    reason
                    for reason, present in (
                        ("provision_text", text_conflict),
                        ("version_metadata", version_conflict),
                    )
                    if present
                ],
                "member_record_ids": sorted(
                    str(grouped_rows[index].get("id", "unknown"))
                    for index in family_indexes
                ),
                "source_links": _member_source_links(grouped_rows, family_indexes),
            }
        )

    duplicate_groups.sort(key=lambda group: group["id"])
    variant_groups.sort(key=lambda group: group["id"])
    return grouped_rows, duplicate_groups, variant_groups


def _under_root(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise LegalAssetImportError(f"法律资产不在仓库根目录内：{path}") from exc


def _asset_record(root: Path, path: Path, kind: str, state: str = "unknown") -> dict[str, Any]:
    relative = _under_root(root, path)
    if not path.is_file():
        raise LegalAssetImportError(f"缺少现有法律资产：{relative.as_posix()}")
    content_hash = _sha256(path.read_bytes())
    return {
        "asset_id": f"asset:{relative.as_posix()}",
        "kind": kind,
        "state": state,
        "conclusion": "unknown",
        "source_path": relative.as_posix(),
        "media_type": _media_type(path),
        "content_hash": content_hash,
        "content_ref": content_hash,
    }


def _required_asset_paths(root: Path) -> list[tuple[Path, str, str]]:
    handoff_root = root / "docs" / "legal" / "法计交接"
    templates_root = root / "legal" / "templates"
    handoff = [
        (
            path,
            "signature_workbook" if path.name == "案隐盾_法计交接签署册.docx" else "handoff_template",
            "unknown",
        )
        for path in sorted(handoff_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    ]
    templates = [
        (path, "current_template", "unknown")
        for path in sorted(templates_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    ]
    if not handoff:
        raise LegalAssetImportError("未找到现有法计交接模板")
    if not templates:
        raise LegalAssetImportError("未找到现有法律模板")
    return [
        (root / "legal" / "sources" / "总法源目录_合并版.json", "merged_legal_catalog", "unknown"),
        (root / "legal" / "sources" / "总法源目录_合并版.xlsx", "merged_legal_catalog", "unknown"),
        (
            root / "docs" / "legal" / "案隐盾_系统法学规则与验收标准_v1.0.md",
            "rule_specification",
            "unknown",
        ),
        (root / "docs" / "PROJECT_MAP.md", "outbound_gate_table", "unknown"),
        (
            root / "docs" / "legal" / "人工审批页面说明_设计稿.docx",
            "approval_design",
            "design_only",
        ),
        (root / "packs" / "labor_v2_draft.json", "labor_draft_pack", "unknown"),
        *handoff,
        *templates,
    ]


def _catalog_source_record(
    row: dict[str, Any], index: int, catalog_asset: dict[str, Any]
) -> dict[str, Any]:
    normalized = _unknown_for_blank(row)
    title = normalized.get("title", "unknown")
    row_id = normalized.get("id", "unknown")
    articles = normalized.get("articles") or ["unknown"]
    if isinstance(articles, str):
        articles = [articles]
    provision_text = normalized.get("provision_text", "unknown")
    provision_hash = _sha256(str(provision_text).encode("utf-8"))
    source_assets = [
        {
            "asset_id": catalog_asset["asset_id"],
            "content_hash": catalog_asset["content_hash"],
            "source_path": catalog_asset["source_path"],
        }
    ]
    record = LegalSourceRecord(
        id=str(row_id),
        canonical_title=str(title),
        articles=[str(article) for article in articles],
        provision_hash=provision_hash,
        provision_text_ref=provision_hash,
        effective_from=str(normalized.get("effective_from", "unknown")),
        effective_to=str(normalized.get("effective_to", "unknown")),
        citation_status=normalized.get("citation_status", "unknown"),
        rule_nature=normalized.get("rule_nature", "unknown"),
        granularity=normalized.get("granularity", "unknown"),
        source_assets=source_assets,
    ).model_dump(mode="json")
    record["catalog_row_number"] = index
    record["source_fields"] = normalized
    return record


def build_existing_legal_asset_registry(
    root: Path, *, expected_catalog_rows: int | None = 140
) -> dict[str, Any]:
    """Read and hash only the legal assets already present below ``root``."""
    from .contracts import CitationMapping

    root = root.resolve()
    assets = [
        _asset_record(root, path, kind, state)
        for path, kind, state in _required_asset_paths(root)
    ]
    catalog_asset = next(
        asset
        for asset in assets
        if asset["source_path"] == "legal/sources/总法源目录_合并版.json"
    )
    catalog_path = root / catalog_asset["source_path"]
    try:
        catalog_rows = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegalAssetImportError("现有合并法源目录无法读取") from exc
    if not isinstance(catalog_rows, list) or not all(isinstance(row, dict) for row in catalog_rows):
        raise LegalAssetImportError("现有合并法源目录必须是对象行列表")
    if expected_catalog_rows is not None and len(catalog_rows) != expected_catalog_rows:
        raise LegalAssetImportError(
            f"现有合并法源目录应为 {expected_catalog_rows} 行，实际为 {len(catalog_rows)} 行"
        )

    legal_sources = [
        _catalog_source_record(row, index, catalog_asset)
        for index, row in enumerate(catalog_rows, start=1)
    ]
    legal_sources, duplicate_groups, variant_groups = group_legal_source_records(
        legal_sources
    )

    lawyer_law_article_38 = next(
        (
            source
            for source in legal_sources
            if source["id"] == "ls_014_d94ad0e714"
            and source["canonical_title"] == "《中华人民共和国律师法》"
            and source["articles"] == ["第38条"]
        ),
        None,
    )
    if lawyer_law_article_38 is None:
        raise LegalAssetImportError("缺少律师法旧第38条历史记录")
    lawyer_law_article_38["citation_status"] = "historical"
    lawyer_law_article_38["effective_to"] = "2026-08-31"

    amendment_basis_asset = next(
        (
            asset
            for asset in assets
            if asset["source_path"]
            == "docs/legal/案隐盾_系统法学规则与验收标准_v1.0.md"
        ),
        None,
    )
    if amendment_basis_asset is None:
        raise LegalAssetImportError("缺少律师法38/41条顺序映射的现有证据资产")
    citation_mapping = CitationMapping(
        id="citation-mapping:lawyer-law:38-to-41:2026-09-01",
        instrument="《中华人民共和国律师法》",
        from_article="第38条",
        to_article="第41条",
        effective_from="2026-09-01",
        mapping_basis="amendment_sequence",
        basis_artifact_hash=amendment_basis_asset["content_hash"],
        status="pending",
        note=(
            "依据现有律师法修改决定及条文顺序调整记录推算；"
            "未取得修订后重新公布的完整文本，不得标记为现行第41条全文已逐字核验。"
        ),
    ).model_dump(mode="json")
    lawyer_law_article_38["temporal_mapping_ids"] = [citation_mapping["id"]]

    registry: dict[str, Any] = {
        "id": LEGAL_ASSET_REGISTRY_ID,
        "schema_version": 1,
        "state": "unknown",
        "legal_source_count": len(legal_sources),
        "exact_duplicate_group_count": len(duplicate_groups),
        "variant_group_count": len(variant_groups),
        "assets": assets,
        "legal_sources": legal_sources,
        "citation_mappings": [citation_mapping],
        "exact_duplicate_groups": duplicate_groups,
        "variant_groups": variant_groups,
    }
    registry["registry_hash"] = _sha256(
        json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    validate_legal_asset_registry(registry)
    return registry


def validate_legal_asset_registry(registry: dict[str, Any]) -> None:
    """Validate source provenance before any registry state can be replaced."""
    assets = registry.get("assets")
    rows = registry.get("legal_sources")
    if not isinstance(assets, list) or not isinstance(rows, list):
        raise LegalAssetImportError("法律资产注册表结构无效")
    assets_by_id: dict[str, dict[str, Any]] = {}
    for asset in assets:
        asset_id = asset.get("asset_id") if isinstance(asset, dict) else None
        content_hash = asset.get("content_hash") if isinstance(asset, dict) else None
        if not asset_id or not isinstance(content_hash, str) or not _SHA256.fullmatch(content_hash):
            raise LegalAssetImportError("法律资产缺少来源资产标识或源内容哈希")
        assets_by_id[asset_id] = asset

    for row in rows:
        row_id = row.get("id", "unknown") if isinstance(row, dict) else "unknown"
        pointers = row.get("source_assets") if isinstance(row, dict) else None
        if not isinstance(pointers, list) or not pointers:
            raise LegalAssetImportError(f"法源行 {row_id} 缺少来源资产标识或源内容哈希")
        for pointer in pointers:
            asset_id = pointer.get("asset_id") if isinstance(pointer, dict) else None
            content_hash = pointer.get("content_hash") if isinstance(pointer, dict) else None
            if not asset_id or not isinstance(content_hash, str) or not _SHA256.fullmatch(content_hash):
                raise LegalAssetImportError(f"法源行 {row_id} 缺少来源资产标识或源内容哈希")
            asset = assets_by_id.get(asset_id)
            if asset is None or asset["content_hash"] != content_hash:
                raise LegalAssetImportError(f"法源行 {row_id} 的来源资产或源内容哈希不匹配")


def persist_legal_asset_registry(store: Store, registry: dict[str, Any]) -> dict[str, Any]:
    """Atomically replace the complete registry after validating every source row."""
    validate_legal_asset_registry(registry)
    with store.transaction() as repo:
        repo.put(LEGAL_ASSET_REGISTRY_KIND, registry, scope="existing-assets")
    return {
        "registry_id": registry["id"],
        "registry_hash": registry.get("registry_hash", "unknown"),
        "legal_source_count": len(registry["legal_sources"]),
        "asset_count": len(registry["assets"]),
        "state": registry.get("state", "unknown"),
    }


def import_existing_legal_assets(store: Store, root: Path) -> dict[str, Any]:
    """Build and atomically persist the repository's existing legal-asset registry."""
    registry = build_existing_legal_asset_registry(root)
    return persist_legal_asset_registry(store, registry)
