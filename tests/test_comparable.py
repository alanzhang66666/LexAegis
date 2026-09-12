import json
import sys

import pytest

from lexaegis.attacks import FORBIDDEN_KEYS, assert_isolated_payload
from lexaegis.cli import main
from lexaegis.data_registry import default_data_root, find_dataset
from lexaegis.dataset import (
    COMPARABLE_ARTIFACT_KEYS,
    METHOD_GROUPS,
    emit_comparable_artifact,
    frozen_auxiliary_directory,
    identity_label_for,
    load_eval_pack,
    read_records_jsonl,
    run_catalog_comparison,
    run_comparable_comparison,
)
from lexaegis.experiments import assert_honest_comparable_report, isolated_identity_probe, pending_labels_document


def _catalog():
    path, manifest = find_dataset("mock_labor")
    records = read_records_jsonl(path.parent / manifest.records_path)
    return records, manifest


def test_five_groups_emit_comparable_artifacts_on_frozen_mock():
    records, manifest = _catalog()
    assert manifest.dispatch_allowed is False
    record = next(item for item in records if item["id"] == "mock_labor_003")
    pack = load_eval_pack()
    artifacts = [emit_comparable_artifact(record, group, pack) for group in METHOD_GROUPS]
    assert [item["group"] for item in artifacts] == list(METHOD_GROUPS)
    assert all(set(item) == set(COMPARABLE_ARTIFACT_KEYS) for item in artifacts)
    assert all(item["experimental_only"] is True for item in artifacts)
    assert all(item["legal_necessity_determined"] is False for item in artifacts)
    assert all(item["production_dispatch"] is False for item in artifacts)
    assert all(item["attempt_count"] == 1 for item in artifacts)
    assert all(isinstance(item["payload"], str) for item in artifacts)
    assert all(isinstance(item["fact_outputs"], list) and item["fact_outputs"] for item in artifacts)
    payloads = {item["group"]: item["payload"] for item in artifacts}
    assert "某劳动者" in payloads["find_replace"]
    assert "合成人物003" not in payloads["find_replace"]
    assert "[[LEX:P0003]]" in payloads["consistent_pseudonym"]
    assert "[[LEX:P0003]]" in payloads["task_matrix"]
    assert "2026-03-12" in payloads["legal_constraint"]
    assert "[[LEX:P0003]]" in payloads["legal_constraint"]


def test_comparable_report_isolates_attacker_and_does_not_fabricate_scores():
    records, manifest = _catalog()
    report = run_comparable_comparison(records, manifest.model_dump(mode="json"))
    assert_honest_comparable_report(report)
    assert set(report["groups"]) == set(METHOD_GROUPS)
    assert report["dispatch_allowed"] is False
    assert report["production_dispatch"] is False
    assert report["legal_annotation_status"] == "pending"
    assert report["annotation_labels"]["record_label_count"] == 0
    assert report["annotation_labels"]["annotator_a"] is None
    catalog = json.loads((default_data_root() / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["datasets"][0]["id"] == "mock_labor"
    assert manifest.dispatch_allowed is False

    auxiliary = frozen_auxiliary_directory(records)
    assert_isolated_payload({"request": {"facts": [{"text": "x"}]}, "auxiliary": auxiliary})
    assert not (FORBIDDEN_KEYS & {str(key).lower() for item in auxiliary for key in item})

    record = records[0]
    probe = isolated_identity_probe(
        "empty",
        auxiliary,
        {"identity": identity_label_for(record, pending_labels_document())},
    )
    assert probe["isolation"]["attacker_received_labels"] is False
    assert probe["isolation"]["public_search"] is False

    for group, rows in report["groups"].items():
        top1 = rows["identity_top1"]
        assert "numerator" in top1 and "denominator" in top1
        assert top1["denominator"] == 8
        assert "failure_classes" in top1
        assert rows["engineering"]["attempt_count_total"] == 8
        assert rows["human_cost"]["outcome"] == "not_applicable"
        assert len(report["artifacts"][group]) == 8

    assert report["controls"]["positive_identity"]["top1"]["numerator"] == 1
    assert report["controls"]["negative_identity"]["protocol_outcome"] == "uncertain"
    assert report["splits"]["development"]["find_replace"]["case_count"] == 6
    assert report["splits"]["blind"]["find_replace"]["case_count"] == 2
    assert "winner" not in report
    ablation = report["ablations"]["drop_hard_constraints"]
    assert ablation["keep_hard_constraints"]["date_relation"]["denominator"] == 8
    assert ablation["drop_hard_constraints"]["date_relation"]["denominator"] == 8


def test_dataset_compare_and_labels_template_cli(tmp_path, monkeypatch):
    labels = tmp_path / "labels.json"
    report = tmp_path / "compare.json"
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "labels-template", "--output", str(labels)])
    main()
    payload = json.loads(labels.read_text(encoding="utf-8"))
    assert payload["status"] == "pending"
    assert payload["records"] == {}
    assert payload["annotator_a"] is None
    monkeypatch.setattr(sys, "argv", [
        "lexaegis", "dataset", "compare", "--dataset-id", "mock_labor",
        "--output", str(report), "--labels", str(labels),
    ])
    main()
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["status"] == "complete_technical_mock_smoke"
    assert written["production_dispatch"] is False
    assert written["legal_availability"]["outcome"] == "not_scored"
    assert written["annotation_labels"]["status"] == "pending"
    with pytest.raises(FileExistsError):
        main()


def test_catalog_comparison_wrapper_stays_eval_only():
    report = run_catalog_comparison("mock_labor")
    assert report["dataset_id"] == "mock_labor"
    assert report["dispatch_allowed"] is False
    assert report["privacy_reduction_rate"]["outcome"] == "not_scored"
    assert report["aura"]["outcome"] == "not_applicable"
