"""Versioned evaluation corpora as repository assets (not runtime cases).

Scans `data/*/dataset.json`. Does not write SQLite. Formal dispatch is always false.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .dataset import (
    build_mock_corpus,
    freeze_mock_corpus,
    read_records_jsonl,
    write_records_jsonl,
)
from .util import digest


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetProvenance(RegistryModel):
    method: str
    contains_real_case_content: Literal[False]
    structure_source: Literal["none", "abstract_only", "authorized_template"] = "none"
    authorization_record: str | None = None


class PackRef(RegistryModel):
    id: str
    version: str
    content_hash: str | None = None


class GenerationArtifact(RegistryModel):
    method: str
    template_hash: str
    runtime_model_hash: str = "not_applicable"
    runtime_prompt_hash: str = "not_applicable"


class DatasetManifest(RegistryModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    name: str
    version: str
    kind: Literal["fully_synthetic", "structure_abstracted_semisynthetic", "pack_regression"]
    status: Literal["draft", "frozen", "annotated", "retired"]
    domain_id: str
    compatible_core: str = ">=0.2,<2"
    pack_ref: PackRef | None = None
    task_ids: list[str]
    seed: int
    generator_id: str
    generator_version: str
    records_hash: str
    freeze_hash: str
    record_hashes: dict[str, str]
    dependency_hash: str = "unrecorded"
    split: dict[str, Literal["development", "blind"]]
    provenance: DatasetProvenance
    legal_annotation_status: Literal["pending", "partial", "complete"] = "pending"
    dispatch_allowed: Literal[False] = False
    groups: list[str]
    count: int
    records_path: str = "records.jsonl"
    generation_artifact: GenerationArtifact | None = None
    freeze_status: str | None = None


class CatalogEntry(RegistryModel):
    id: str
    version: str
    kind: Literal["fully_synthetic", "structure_abstracted_semisynthetic", "pack_regression"]
    status: Literal["draft", "frozen", "annotated", "retired"]
    path: str
    freeze_hash: str


class DatasetCatalog(RegistryModel):
    schema_version: Literal[1] = 1
    datasets: list[CatalogEntry]


MOCK_LABOR_ID = "mock_labor"
MOCK_LABOR_VERSION = "1.0.0"
MOCK_LABOR_DIRNAME = "mock_labor_v1"


def default_data_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def write_json_once(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _catalog_path(root: Path) -> Path:
    return Path(root) / "catalog.json"


def load_catalog(root: Path | None = None) -> DatasetCatalog:
    path = _catalog_path(root or default_data_root())
    return DatasetCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))


def iter_dataset_files(root: Path | None = None) -> list[Path]:
    return sorted((root or default_data_root()).glob("*/dataset.json"))


def load_manifest(path: Path) -> DatasetManifest:
    return DatasetManifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def list_datasets(root: Path | None = None) -> list[dict]:
    root = Path(root or default_data_root())
    items = []
    for path in iter_dataset_files(root):
        manifest = load_manifest(path)
        items.append({
            "id": manifest.id,
            "version": manifest.version,
            "kind": manifest.kind,
            "status": manifest.status,
            "path": path.parent.relative_to(root).as_posix(),
            "freeze_hash": manifest.freeze_hash,
        })
    return items


def find_dataset(dataset_id: str, root: Path | None = None) -> tuple[Path, DatasetManifest]:
    root = Path(root or default_data_root())
    matches = []
    for path in iter_dataset_files(root):
        manifest = load_manifest(path)
        if manifest.id == dataset_id:
            matches.append((path, manifest))
    if not matches:
        raise ValueError(f"未找到数据集 {dataset_id}")
    if len(matches) > 1:
        raise ValueError(f"数据集 {dataset_id} 存在多个版本，请先拆目录或升级唯一版本")
    return matches[0]


def _records_file(directory: Path, manifest: DatasetManifest) -> Path:
    relative = Path(manifest.records_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{manifest.id}: records_path 必须是数据集目录内的相对路径")
    return directory / relative


def _validate_records(manifest: DatasetManifest, records: list[dict]) -> list[str]:
    problems = []
    if len(records) != manifest.count:
        problems.append(f"{manifest.id}: 记录数 {len(records)} 与清单 count {manifest.count} 不一致")
    ids = [record.get("id") for record in records]
    if len(set(ids)) != len(ids):
        problems.append(f"{manifest.id}: 记录标识重复")
    for record in records:
        record_id = record.get("id", "unknown")
        if record.get("synthetic") is not True:
            problems.append(f"{record_id}: 未声明 synthetic=true")
        if record.get("provenance", {}).get("contains_real_case_content") is not False:
            problems.append(f"{record_id}: 未声明不含真实案件内容")
        core = {key: value for key, value in record.items() if key != "content_hash"}
        if record.get("content_hash") != digest(core):
            problems.append(f"{record_id}: 内容哈希不一致")
    id_set = {record_id for record_id in ids if record_id}
    if set(manifest.split) != id_set:
        problems.append(f"{manifest.id}: split 与记录标识不一致")
    if set(manifest.record_hashes) != id_set:
        problems.append(f"{manifest.id}: record_hashes 与记录标识不一致")
    for record in records:
        record_id = record.get("id")
        if record_id in manifest.record_hashes and record.get("content_hash") != manifest.record_hashes[record_id]:
            problems.append(f"{record_id}: 与清单 record_hashes 不一致")
    ordered = sorted(records, key=lambda item: item["id"])
    if digest(ordered) != manifest.records_hash:
        problems.append(f"{manifest.id}: records_hash 不一致")
    if manifest.kind == "fully_synthetic":
        try:
            frozen = freeze_mock_corpus(
                records,
                seed=manifest.seed,
                dependency_hash=manifest.dependency_hash,
                generator_version=manifest.generator_version,
            )
        except ValueError as error:
            problems.append(f"{manifest.id}: {error}")
            return problems
        if frozen["records_hash"] != manifest.records_hash:
            problems.append(f"{manifest.id}: records_hash 与冻结结果不一致")
        if frozen["freeze_hash"] != manifest.freeze_hash:
            problems.append(f"{manifest.id}: freeze_hash 不一致")
    if manifest.dispatch_allowed is not False:
        problems.append(f"{manifest.id}: dispatch_allowed 必须为 false")
    if manifest.provenance.contains_real_case_content is not False:
        problems.append(f"{manifest.id}: 清单不得声明含真实案件内容")
    return problems


def validate_tree(root: Path | None = None) -> dict:
    root = Path(root or default_data_root())
    problems: list[str] = []
    datasets: list[dict] = []
    if not root.is_dir():
        return {"ok": False, "problems": [f"缺少数据目录 {root}"], "datasets": []}
    catalog_file = _catalog_path(root)
    catalog = None
    if not catalog_file.is_file():
        problems.append("缺少 catalog.json")
    else:
        try:
            catalog = load_catalog(root)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            problems.append(f"catalog.json 无效: {error}")
    seen: dict[tuple[str, str], str] = {}
    scanned: dict[tuple[str, str], CatalogEntry] = {}
    for path in iter_dataset_files(root):
        relative_dir = path.parent.relative_to(root).as_posix()
        try:
            manifest = load_manifest(path)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            problems.append(f"{relative_dir}/dataset.json 无效: {error}")
            continue
        key = (manifest.id, manifest.version)
        if key in seen:
            problems.append(f"重复的 (id, version): {manifest.id} {manifest.version}")
        seen[key] = relative_dir
        scanned[key] = CatalogEntry(
            id=manifest.id,
            version=manifest.version,
            kind=manifest.kind,
            status=manifest.status,
            path=relative_dir,
            freeze_hash=manifest.freeze_hash,
        )
        datasets.append(scanned[key].model_dump(mode="json"))
        try:
            records = read_records_jsonl(_records_file(path.parent, manifest))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            problems.append(f"{manifest.id}: 无法读取记录 {error}")
            continue
        problems.extend(_validate_records(manifest, records))
    if catalog is not None:
        catalog_keys = []
        for entry in catalog.datasets:
            key = (entry.id, entry.version)
            catalog_keys.append(key)
            if key not in scanned:
                problems.append(f"catalog 引用了缺失数据集 {entry.id} {entry.version}")
                continue
            actual = scanned[key]
            if entry.model_dump() != actual.model_dump():
                problems.append(f"catalog 与 {actual.path}/dataset.json 索引不一致")
        if len(catalog_keys) != len(set(catalog_keys)):
            problems.append("catalog 中存在重复的 (id, version)")
        for key, actual in scanned.items():
            if key not in set(catalog_keys):
                problems.append(f"{actual.path} 未登记到 catalog.json")
    return {"ok": not problems, "problems": problems, "datasets": datasets}


def build_mock_labor_manifest(frozen: dict) -> DatasetManifest:
    return DatasetManifest(
        id=MOCK_LABOR_ID,
        name="劳动争议完全合成评测集",
        version=MOCK_LABOR_VERSION,
        kind="fully_synthetic",
        status="frozen",
        domain_id="labor",
        task_ids=["fact_summary"],
        seed=frozen["seed"],
        generator_id=frozen["generator_version"],
        generator_version=frozen["generator_version"],
        records_hash=frozen["records_hash"],
        freeze_hash=frozen["freeze_hash"],
        record_hashes=frozen["record_hashes"],
        dependency_hash=frozen["dependency_hash"],
        split=frozen["split"],
        provenance=DatasetProvenance(
            method="deterministic_ai_authored_template",
            contains_real_case_content=False,
            structure_source="none",
        ),
        legal_annotation_status="pending",
        dispatch_allowed=False,
        groups=list(frozen["groups"]),
        count=frozen["count"],
        records_path="records.jsonl",
        generation_artifact=GenerationArtifact.model_validate(frozen["generation_artifact"]),
        freeze_status=frozen["freeze_status"],
    )


def write_catalog(root: Path, entries: list[CatalogEntry]) -> None:
    ordered = sorted(entries, key=lambda item: (item.id, item.version))
    path = _catalog_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(DatasetCatalog(datasets=ordered).model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def write_mock_labor_v1(root: Path | None = None) -> DatasetManifest:
    """Materialize the frozen 8-record mock; refuse to overwrite the same version."""
    root = Path(root or default_data_root())
    directory = root / MOCK_LABOR_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    records_path = directory / "records.jsonl"
    dataset_path = directory / "dataset.json"
    if records_path.exists() or dataset_path.exists():
        raise FileExistsError("同版本数据集不可覆盖")
    records = build_mock_corpus()
    frozen = freeze_mock_corpus(records)
    manifest = build_mock_labor_manifest(frozen)
    write_records_jsonl(records_path, records)
    write_json_once(dataset_path, manifest.model_dump(mode="json", exclude_none=True))
    catalog_file = _catalog_path(root)
    entry = CatalogEntry(
        id=manifest.id,
        version=manifest.version,
        kind=manifest.kind,
        status=manifest.status,
        path=MOCK_LABOR_DIRNAME,
        freeze_hash=manifest.freeze_hash,
    )
    if catalog_file.exists():
        catalog = load_catalog(root)
        if any(item.id == entry.id and item.version == entry.version for item in catalog.datasets):
            raise FileExistsError("catalog 中已存在相同 (id, version)")
        write_catalog(root, [*catalog.datasets, entry])
    else:
        write_catalog(root, [entry])
    return manifest
