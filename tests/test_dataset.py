import json
import sys

import pytest

from lexaegis.cli import main
from lexaegis.dataset import (
    GROUPS,
    build_mock_corpus,
    freeze_mock_corpus,
    run_mock_comparison,
    transform_mock_record,
)


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
