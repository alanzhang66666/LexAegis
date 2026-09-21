import json

from training.lexaegis_grpo import load_projected_records, score_completion


def test_projection_uses_only_bundled_synthetic_records():
    rows = load_projected_records()
    assert len(rows) == 8
    assert all(row["data_origin"] == "bundled_fully_synthetic" for row in rows)
    assert all(row["training_scope"] == "output_contract_and_evidence_grounding_only" for row in rows)


def test_reference_completions_receive_full_contract_reward():
    for row in load_projected_records():
        assert score_completion(row["reference_completion"], row["facts"]) == 1.0


def test_reward_rejects_unknown_fact_reference_and_identity_token():
    row = load_projected_records()[0]
    output = {
        "claims": [{"text": "[[LEX:P9999]]", "source_ids": ["unknown"]}],
        "unused_fact_ids": [],
        "gaps": [],
    }
    assert score_completion(json.dumps(output), row["facts"]) < 0.5


def test_reward_rejects_non_json():
    row = load_projected_records()[0]
    assert score_completion("not-json", row["facts"]) == 0.0
