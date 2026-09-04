import json
import math
import sys

import pytest

from lexaegis.cli import main
from lexaegis.experiments import (
    distance_preservation,
    membership_metrics,
    pca_projection,
    run_ianvs_profile,
)


def experiment_payload():
    return {
        "vectors": [[1.0, 1.0, 0.0], [2.0, 2.0, 0.5], [3.0, 3.0, 1.0], [4.0, 4.0, 1.5]],
        "input_model_hash": "sha256:synthetic-vector-generator-v1",
        "saliency": {
            "source": "experimental_model",
            "model_hash": "sha256:saliency-model-v1",
            "tokens": ["劳动者", "工资", "12000", "元"],
            "scores": [0.1, 0.2, 0.9, 0.3],
        },
        "target_outputs": {
            "source": "real_target_model",
            "model_hash": "sha256:target-model-v1",
            "members": [
                {"loss": 0.1, "neighbour_losses": [0.8, 0.9], "lira_score": 0.9, "inversion_similarity": 0.8},
                {"loss": 0.2, "neighbour_losses": [0.7, 0.8], "lira_score": 0.8, "inversion_similarity": 0.7},
            ],
            "nonmembers": [
                {"loss": 1.0, "neighbour_losses": [1.1, 1.0], "lira_score": 0.2, "inversion_similarity": 0.1},
                {"loss": 1.2, "neighbour_losses": [1.2, 1.3], "lira_score": 0.1, "inversion_similarity": 0.2},
            ],
        },
    }


def test_profile_runs_all_transforms_with_frozen_reproducible_hashes():
    first = run_ianvs_profile(experiment_payload(), seed=31, target_dim=2, epsilon_budget=0.01)
    second = run_ianvs_profile(experiment_payload(), seed=31, target_dim=2, epsilon_budget=0.01)
    assert first["report_hash"] == second["report_hash"]
    assert first["production_dispatch"] is False
    assert {item["algorithm"] for item in first["transforms"]} == {
        "gaussian_dp", "jl", "random_projection", "pca", "saliency_mask",
    }
    assert [item["id"] for item in first["transforms"]] == [item["id"] for item in second["transforms"]]
    assert all(item["input_model_hash"] for item in first["transforms"] if item["algorithm"] != "saliency_mask")
    assert all(item["matrix_hash"] for item in first["transforms"] if item["algorithm"] in {"jl", "pca", "random_projection"})
    dp = next(item for item in first["transforms"] if item["algorithm"] == "gaussian_dp")
    assert dp["budget"]["status"] == "exceeded" and dp["budget"]["epsilon"] > 0
    assert first["membership_metrics"]["loss"]["auc"] == 1.0


def test_pca_and_distance_metrics_use_real_numeric_vectors():
    vectors = [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
    result = pca_projection(vectors, 1, seed=7)
    assert len(result["vectors"]) == 3 and len(result["vectors"][0]) == 1
    metric = distance_preservation(vectors, result["vectors"])
    assert metric["outcome"] == "measured"
    assert math.isclose(metric["max_relative_distortion"], 0.0, abs_tol=1e-7)


def test_membership_metrics_refuse_missing_and_constant_outputs():
    missing = membership_metrics(None)
    assert {item["outcome"] for item in missing.values()} == {"not_applicable"}
    constant = {
        "source": "real_target_model", "model_hash": "sha256:model",
        "members": [{"loss": 1.0}], "nonmembers": [{"loss": 1.0}],
    }
    assert membership_metrics(constant)["loss"]["outcome"] == "uncertain"


def test_profile_rejects_edge_only_data_and_missing_generator_hash():
    with pytest.raises(ValueError, match="边侧专属"):
        run_ianvs_profile({"vectors": [[1.0]], "input_model_hash": "x", "mapping": {"a": "b"}})
    with pytest.raises(ValueError, match="生成器哈希"):
        run_ianvs_profile({"vectors": [[1.0]]})


def test_bench_cli_writes_once_and_never_overwrites(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(experiment_payload(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["lexaegis", "bench", "--profile", "ianvs-pipl",
                                     "--input", str(source), "--output", str(output)])
    main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "complete" and report["report_hash"]
    with pytest.raises(FileExistsError):
        main()
