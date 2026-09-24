"""Layer 3 of the three-path check is a cloud send. The product latch stays blocked."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_three_layer_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = _load("verify_three_layers_live")
delivery = _load("verify_competition_delivery")
build_submission = _load("build_submission")


def _layer(name, model, human, final, **extra):
    item = {
        "layer": name,
        "model_decision": model,
        "edge_decision": model,
        "human_review": human,
        "final_state": final,
        "edge_source": "live_edge_model",
        "edge_response_hash": "sha256:" + "a" * 64,
        "safety_floor_applied": False,
    }
    item.update(extra)
    return item


def _evidence(third):
    return {
        "status": "passed",
        "formal_dispatch": "blocked",
        "three_layers": [
            _layer("1_edge_blocks", "block_external", "not_reached", "blocked", transport="cloud"),
            _layer("2_human_rejects", "allow_human_review", "reject_current_request", "rejected", transport="cloud"),
            third,
        ],
    }


def test_demo_profile_cannot_count_as_layer_three_send():
    with pytest.raises(RuntimeError, match="integration"):
        live.require_real_send_profile("demo")
    live.require_real_send_profile("integration")


def test_layer_three_simulation_is_rejected(tmp_path):
    root = tmp_path / "delivery"
    (root / "validation").mkdir(parents=True)
    third = _layer(
        "3_model_and_human_allow", "allow_human_review", "allow_processing", "complete",
        transport="mock", provenance="simulation",
    )
    (root / "validation" / "live-three-layers.json").write_text(
        json.dumps(_evidence(third)), encoding="utf-8"
    )
    findings = []
    delivery.verify_three_layers(root, findings)
    assert any("不是云端真实发送" in item for item in findings)


def test_layer_three_cloud_send_passes_execution_check(tmp_path):
    root = tmp_path / "delivery"
    (root / "validation").mkdir(parents=True)
    third = _layer(
        "3_model_and_human_allow", "allow_human_review", "allow_processing", "complete",
        transport="cloud", provenance="cloud",
    )
    (root / "validation" / "live-three-layers.json").write_text(
        json.dumps(_evidence(third)), encoding="utf-8"
    )
    findings = []
    delivery.verify_three_layers(root, findings)
    assert findings == []


def test_delivery_status_marks_complete_path_as_cloud_and_keeps_latch(tmp_path):
    build_submission._write_delivery_status(tmp_path, "interface-only", {}, "not_run")
    status = json.loads((tmp_path / "DELIVERY_STATUS.json").read_text(encoding="utf-8"))
    assert status["formal_dispatch"] == "blocked"
    complete = next(item for item in status["demo_boundaries"] if item["id"] == "complete_disclosure")
    assert complete["execution"] == "cloud"
    assert complete["human_review"] == "allow_processing"
