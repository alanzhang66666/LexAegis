import json
import shutil
import sys

import pytest
from pydantic import ValidationError

from lexaegis.cli import main
from lexaegis.data_registry import (
    DatasetManifest,
    default_data_root,
    promote_semi_labor,
    validate_local_scaffold,
    validate_tree,
    write_semi_labor_v1,
)
from lexaegis.dataset import (
    GROUPS,
    build_mock_corpus,
    freeze_mock_corpus,
    read_records_jsonl,
    run_mock_comparison,
    transform_mock_record,
    validate_annotations,
    write_records_jsonl,
)
from lexaegis.util import digest


def test_small_mock_corpus_is_explicitly_synthetic_and_anchored():
    records = build_mock_corpus()
    assert len(records) == 8
    assert all(record["synthetic"] for record in records)
    assert all(record["provenance"]["contains_real_case_content"] is False for record in records)
    assert all("@example.invalid" in record["document"]["blocks"][0]["text"] for record in records)
    assert all(record["technical_truth"]["direct_identifiers"] for record in records)
    assert all(record["annotations"]["status"] == "pending_legal_annotation" for record in records)


def test_mock_freeze_is_reproducible_with_six_two_split():
    records = build_mock_corpus()
    first = freeze_mock_corpus(records, dependency_hash="sha256:lock")
    second = freeze_mock_corpus(records, dependency_hash="sha256:lock")
    assert first == second
    assert list(first["split"].values()).count("development") == 6
    assert list(first["split"].values()).count("blind") == 2
    assert first["legal_annotation_status"] == "pending"
    assert first["generation_artifact"]["template_hash"]
    assert first["generation_artifact"]["runtime_model_hash"] == "not_applicable"
    changed = [dict(record) for record in records]
    changed[0]["content_hash"] = "tampered"
    with pytest.raises(ValueError, match="哈希"):
        freeze_mock_corpus(changed)


def test_four_text_groups_are_traceable_and_do_not_fake_legal_necessity():
    record = build_mock_corpus()[0]
    original = transform_mock_record(record, "original")
    replaced = transform_mock_record(record, "find_replace")
    pseudo = transform_mock_record(record, "consistent_pseudonym")
    minimal = transform_mock_record(record, "task_minimal")
    assert record["technical_truth"]["direct_identifiers"][0]["value"] in original["payload"]
    assert not any(item["value"] in replaced["payload"] for item in record["technical_truth"]["direct_identifiers"])
    assert "[[LEX:P0001]]" in pseudo["payload"]
    assert len(minimal["payload"]) < len(pseudo["payload"])
    assert all(item["source_ids"] == ["block_001"] for item in (original, replaced, pseudo, minimal))
    assert all(item["legal_necessity_determined"] is False for item in (original, replaced, pseudo, minimal))


def test_comparison_reports_all_groups_but_no_legal_score_or_fake_mia():
    records = build_mock_corpus()
    manifest = freeze_mock_corpus(records)
    report = run_mock_comparison(records, manifest)
    assert set(report["groups"]) == set(GROUPS)
    assert report["legal_task_utility"]["outcome"] == "not_applicable"
    assert {item["outcome"] for item in report["membership_inference"].values()} == {"not_applicable"}
    assert report["production_dispatch"] is False
    assert report["groups"]["ianvs_experimental"]["outcome"] == "separate_vector_experiment"
    assert report["groups"]["original"]["process_cost_proxy"]["transform_operation_count"] == 0


def test_dataset_cli_generates_freezes_and_runs_without_overwrite(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "generate-mock", "--output", str(corpus)])
    main()
    assert len(json.loads(corpus.read_text(encoding="utf-8"))["records"]) == 8
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "freeze", "--input", str(corpus), "--output", str(manifest)])
    main()
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "run", "--input", str(corpus), "--manifest", str(manifest), "--output", str(report)])
    main()
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "complete_technical_mock_only"
    with pytest.raises(FileExistsError):
        main()


def test_repo_catalog_and_mock_labor_hashes_are_stable():
    records = build_mock_corpus()
    frozen = freeze_mock_corpus(records)
    root = default_data_root()
    stored = read_records_jsonl(root / "mock_labor_v1" / "records.jsonl")
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "mock_labor_v1" / "dataset.json").read_text(encoding="utf-8"))
    assert freeze_mock_corpus(stored)["freeze_hash"] == frozen["freeze_hash"]
    assert catalog["datasets"][0]["freeze_hash"] == frozen["freeze_hash"]
    assert manifest["freeze_hash"] == frozen["freeze_hash"]
    assert manifest["records_hash"] == frozen["records_hash"]
    assert manifest["kind"] == "fully_synthetic"
    assert manifest["dispatch_allowed"] is False
    assert manifest["provenance"]["contains_real_case_content"] is False
    assert validate_tree()["ok"] is True


def test_validate_tree_rejects_tampered_records(tmp_path):
    import shutil
    dest = tmp_path / "data"
    shutil.copytree(default_data_root(), dest)
    path = dest / "mock_labor_v1" / "records.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("合成人物", "篡改人物", 1), encoding="utf-8")
    report = validate_tree(dest)
    assert report["ok"] is False
    assert any("哈希" in problem for problem in report["problems"])


def test_dataset_cli_list_and_validate(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "list"])
    main()
    listed = json.loads(capsys.readouterr().out)
    assert any(item["id"] == "mock_labor" and item["freeze_hash"] for item in listed)
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "validate"])
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_semi_labor_writer_validates_and_refuses_overwrite(tmp_path):
    catalog_path = default_data_root() / "catalog.json"
    catalog_before = catalog_path.read_text(encoding="utf-8")
    dest = tmp_path / "semi_labor_v1"
    manifest = write_semi_labor_v1(dest)
    loaded = DatasetManifest.model_validate(json.loads((dest / "dataset.json").read_text(encoding="utf-8")))
    records = read_records_jsonl(dest / "records.jsonl")
    assert loaded == manifest
    assert manifest.kind == "structure_abstracted_semisynthetic"
    assert manifest.status == "draft"
    assert manifest.freeze_status == "unfrozen_pending_annotation"
    assert manifest.dispatch_allowed is False
    assert manifest.legal_annotation_status == "pending"
    assert manifest.provenance.contains_real_case_content is False
    assert manifest.provenance.structure_source == "abstract_only"
    assert len(records) == 100
    assert all(record["document"]["blocks"] for record in records)
    assert all(record["synthetic"] and record["labels"] == [] and record["adjudication"] is None for record in records)
    assert all(record["provenance"]["contains_real_case_content"] is False for record in records)
    assert all(record["structure_source"] == "abstract_only" for record in records)
    problems = validate_annotations(records)
    assert len(problems) == 200
    assert all("缺少" in item for item in problems)
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate({**manifest.model_dump(), "dispatch_allowed": True})
    with pytest.raises(FileExistsError):
        write_semi_labor_v1(dest)
    catalog_after = catalog_path.read_text(encoding="utf-8")
    assert catalog_after == catalog_before
    catalog = json.loads(catalog_after)
    assert [entry["id"] for entry in catalog["datasets"]] == ["mock_labor"]
    local = validate_local_scaffold(dest)
    assert local["ok"] is True
    assert local["present"] is True
    assert local["problems"] == []
    assert len(local["warnings"]) == 200


def test_dataset_validate_ok_when_local_scaffold_absent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "validate"])
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert "local_scaffold" not in report


def test_validate_local_scaffold_hashes_succeed_with_empty_labels(tmp_path):
    dest = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(dest)
    report = validate_local_scaffold(dest)
    assert report["ok"] is True
    assert report["dispatch_allowed"] is False
    assert report["problems"] == []
    assert len(report["warnings"]) == 200
    missing = validate_local_scaffold(tmp_path / "missing_scaffold")
    assert missing["ok"] is True and missing["present"] is False


def test_generate_semi_cli_defaults_to_ignored_dot_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "generate-semi"])
    main()
    dest = tmp_path / ".data" / "semi_labor_v1"
    assert (dest / "dataset.json").is_file()
    assert (dest / "records.jsonl").is_file()
    assert not (tmp_path / "data").exists()
    manifest = json.loads((dest / "dataset.json").read_text(encoding="utf-8"))
    assert manifest["dispatch_allowed"] is False
    assert manifest["kind"] == "structure_abstracted_semisynthetic"
    catalog = json.loads((default_data_root() / "catalog.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in catalog["datasets"]] == ["mock_labor"]


def _repo_catalog_ids() -> list[str]:
    return [entry["id"] for entry in json.loads((default_data_root() / "catalog.json").read_text(encoding="utf-8"))["datasets"]]


def _complete_scaffold_annotations(directory):
    records = read_records_jsonl(directory / "records.jsonl")
    for record in records:
        record["labels"] = [
            {"annotator": "annotator_a", "field": "event", "necessity": "uncertain"},
            {"annotator": "annotator_b", "field": "event", "necessity": "uncertain"},
        ]
        record["adjudication"] = {"status": "resolved"}
        record["content_hash"] = digest({key: value for key, value in record.items() if key != "content_hash"})
    records_path = directory / "records.jsonl"
    records_path.unlink()
    write_records_jsonl(records_path, records)
    ordered = sorted(records, key=lambda item: item["id"])
    manifest_path = directory / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["legal_annotation_status"] = "complete"
    manifest["records_hash"] = digest(ordered)
    manifest["record_hashes"] = {record["id"]: record["content_hash"] for record in ordered}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_promote_semi_refuses_pending_against_repo_data_root(tmp_path):
    catalog_before = (default_data_root() / "catalog.json").read_text(encoding="utf-8")
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    report = promote_semi_labor(src, default_data_root())
    assert report["ok"] is False
    assert report["promoted"] is False
    assert any("legal_annotation_status 必须为 complete" in item for item in report["problems"])
    assert not (default_data_root() / "semi_labor_v1").exists()
    assert (default_data_root() / "catalog.json").read_text(encoding="utf-8") == catalog_before
    assert _repo_catalog_ids() == ["mock_labor"]


def test_promote_semi_refuses_pending_annotation(tmp_path):
    catalog_before = (default_data_root() / "catalog.json").read_text(encoding="utf-8")
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    dest_root = tmp_path / "data"
    shutil.copytree(default_data_root(), dest_root)
    report = promote_semi_labor(src, dest_root)
    assert report["ok"] is False
    assert report["promoted"] is False
    assert any("legal_annotation_status 必须为 complete" in item for item in report["problems"])
    assert any("标注未完成，拒绝入库" in item for item in report["problems"])
    assert not (dest_root / "semi_labor_v1").exists()
    dest_catalog = json.loads((dest_root / "catalog.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in dest_catalog["datasets"]] == ["mock_labor"]
    assert (default_data_root() / "catalog.json").read_text(encoding="utf-8") == catalog_before
    assert _repo_catalog_ids() == ["mock_labor"]
    assert not (default_data_root() / "semi_labor_v1").exists()


def test_promote_semi_refuses_forged_dispatch_allowed(tmp_path):
    catalog_before = (default_data_root() / "catalog.json").read_text(encoding="utf-8")
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    payload = json.loads((src / "dataset.json").read_text(encoding="utf-8"))
    payload["dispatch_allowed"] = True
    (src / "dataset.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dest_root = tmp_path / "data"
    shutil.copytree(default_data_root(), dest_root)
    report = promote_semi_labor(src, dest_root)
    assert report["ok"] is False
    assert report["promoted"] is False
    assert any("dispatch_allowed 必须为 false" in item for item in report["problems"])
    assert not (dest_root / "semi_labor_v1").exists()
    dest_catalog = json.loads((dest_root / "catalog.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in dest_catalog["datasets"]] == ["mock_labor"]
    assert (default_data_root() / "catalog.json").read_text(encoding="utf-8") == catalog_before
    assert _repo_catalog_ids() == ["mock_labor"]
    assert not (default_data_root() / "semi_labor_v1").exists()


def test_promote_semi_refuses_forged_real_case_content(tmp_path):
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    payload = json.loads((src / "dataset.json").read_text(encoding="utf-8"))
    payload["provenance"]["contains_real_case_content"] = True
    (src / "dataset.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dest_root = tmp_path / "data"
    shutil.copytree(default_data_root(), dest_root)
    report = promote_semi_labor(src, dest_root)
    assert report["ok"] is False
    assert report["promoted"] is False
    assert any("不得声明含真实案件内容" in item for item in report["problems"])
    assert not (dest_root / "semi_labor_v1").exists()
    assert _repo_catalog_ids() == ["mock_labor"]


def test_promote_semi_copies_only_after_complete_annotation(tmp_path):
    catalog_before = (default_data_root() / "catalog.json").read_text(encoding="utf-8")
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    _complete_scaffold_annotations(src)
    dest_root = tmp_path / "data"
    shutil.copytree(default_data_root(), dest_root)
    report = promote_semi_labor(src, dest_root)
    assert report["ok"] is True
    assert report["promoted"] is True
    assert report["dispatch_allowed"] is False
    assert report["contains_real_case_content"] is False
    assert (dest_root / "semi_labor_v1" / "dataset.json").is_file()
    assert (dest_root / "semi_labor_v1" / "records.jsonl").is_file()
    dest_catalog = json.loads((dest_root / "catalog.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in dest_catalog["datasets"]] == ["mock_labor", "semi_labor"]
    assert validate_tree(dest_root)["ok"] is True
    assert (default_data_root() / "catalog.json").read_text(encoding="utf-8") == catalog_before
    assert _repo_catalog_ids() == ["mock_labor"]
    assert not (default_data_root() / "semi_labor_v1").exists()


def test_promote_semi_cli_refuses_pending(tmp_path, monkeypatch, capsys):
    src = tmp_path / "semi_labor_v1"
    write_semi_labor_v1(src)
    dest_root = tmp_path / "data"
    shutil.copytree(default_data_root(), dest_root)
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "promote-semi", str(src), str(dest_root)])
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["promoted"] is False
    assert any("legal_annotation_status" in item or "标注未完成" in item for item in report["problems"])
    assert not (dest_root / "semi_labor_v1").exists()
    assert _repo_catalog_ids() == ["mock_labor"]
