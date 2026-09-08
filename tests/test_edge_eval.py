import json
import sys

import pytest

from lexaegis.cli import main
from lexaegis.edge_eval import probe_edge, score_extract, write_probe_report
from lexaegis.edge_runtime import default_gguf, edge_status, start_edge, start_hint
from lexaegis import edge_runtime


def _blocks():
    return [{"id": "block_001", "text": "合成人物001主张工资12500元，亦称甲。"}]


def test_score_extract_records_engineering_checks_only():
    facts = [{
        "field": "amount", "value": "12500元", "source_ids": ["block_001"],
        "quote": "12500元", "aliases": ["甲"], "normalized": "12500",
    }]
    score = score_extract(_blocks(), facts)
    assert score["json_valid"] is True
    assert score["source_ids_in_blocks"] is True
    assert score["quote_is_substring"] is True
    assert score["numbers_from_source"] is True
    assert score["aliases_no_conflict"] is True
    assert score["field_in_enum"] is True
    assert "legal" not in json.dumps(score)


def test_score_extract_flags_source_quote_number_and_alias_errors():
    facts = [
        {"field": "entity", "value": "甲", "source_ids": ["missing"], "quote": "不存在", "aliases": ["乙"]},
        {"field": "entity", "value": "丙", "source_ids": ["block_001"], "quote": None, "aliases": ["乙"]},
        {"field": "amount", "value": "99999元", "source_ids": ["block_001"], "quote": None, "normalized": "99999"},
    ]
    score = score_extract(_blocks(), facts)
    assert score["source_ids_in_blocks"] is False
    assert score["quote_is_substring"] is False
    assert score["numbers_from_source"] is False
    assert score["aliases_no_conflict"] is False
    assert score["field_in_enum"] is True


def test_score_extract_flags_invalid_field_enum():
    facts = [{"field": "entity|relation|event|date|amount|evidence", "value": "甲", "source_ids": ["block_001"]}]
    score = score_extract(_blocks(), facts)
    assert score["json_valid"] is True
    assert score["field_in_enum"] is False
    assert "field" in "".join(score["issues"])


def test_probe_edge_unconfigured_does_not_score_legal(monkeypatch, tmp_path):
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    report = probe_edge("mock_labor")
    assert report["status"] == "unconfigured"
    assert report["legal_availability"] == "not_scored"
    assert report["scoring"]["kind"] == "engineering_only"
    path = write_probe_report(report, tmp_path / "probe.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "unconfigured"
    assert "legal_score" not in saved


def test_probe_edge_scores_injected_extract(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_MODEL", "edge-small")

    def extract(blocks):
        return [{
            "field": "entity", "value": "合成人物001", "source_ids": [blocks[0]["id"]],
            "quote": "合成人物001", "aliases": [],
        }]

    report = probe_edge("mock_labor", extract=extract)
    assert report["status"] == "complete"
    assert report["record_count"] == 8
    assert report["totals"]["json_valid"] == 8
    assert report["legal_availability"] == "not_scored"
    assert all(row["legal_availability"] == "not_scored" for row in report["records"])


def test_probe_edge_exception_is_not_json_valid(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_MODEL", "edge-small")

    def extract(blocks):
        raise ValueError("source_ids 未落在输入块内")

    report = probe_edge("mock_labor", extract=extract)
    assert report["status"] == "complete"
    assert report["legal_availability"] == "not_scored"
    assert report["totals"]["json_valid"] == 0
    assert all(row["json_valid"] is False for row in report["records"])
    assert all(row["legal_availability"] == "not_scored" for row in report["records"])


def test_probe_edge_cli_unconfigured_exits_zero(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    output = tmp_path / "cli-probe.json"
    monkeypatch.setattr(sys, "argv", ["lexaegis", "dataset", "probe-edge", "--output", str(output)])
    try:
        main()
    except SystemExit as exited:
        assert exited.code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "unconfigured"
    assert output.is_file()


def test_edge_status_is_unconfigured_when_port_closed(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_URL", "http://127.0.0.1:59999/v1")
    status = edge_status()
    assert status["status"] == "unconfigured"
    assert status["listening"] is False
    assert "lexaegis edge --start" in start_hint()


class _FakeEdgeProcess:
    def __init__(self, returncode=None, stderr=None, stderr_text=""):
        self.pid = 4242
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        if stderr is not None and stderr_text:
            stderr.write(stderr_text.encode("utf-8"))
            stderr.flush()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def kill(self):
        self.killed = True
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


def _ready_edge_status(**overrides):
    status = {
        "status": "unconfigured",
        "listening": False,
        "host": "127.0.0.1",
        "port": 8080,
        "binary": "llama-server",
        "binary_present": True,
        "weights": "MiniCPM5-2B-Q4_K_M.gguf",
        "weights_present": True,
        "hint": "x",
    }
    status.update(overrides)
    return status


def test_start_edge_terminates_orphan_on_timeout(monkeypatch):
    fake = _FakeEdgeProcess()
    monkeypatch.setattr(edge_runtime, "edge_status", lambda: _ready_edge_status())
    monkeypatch.setattr(edge_runtime, "edge_port_open", lambda timeout=0.4: False)
    monkeypatch.setattr(edge_runtime, "start_command", lambda: ["llama-server"])
    monkeypatch.setattr(edge_runtime.subprocess, "Popen", lambda *args, **kwargs: fake)
    with pytest.raises(TimeoutError, match="端口尚未就绪"):
        start_edge(wait=0)
    assert fake.terminated is True


def test_start_edge_surfaces_stderr_when_child_exits(monkeypatch):
    def popen(command, stdout=None, stderr=None, **kwargs):
        return _FakeEdgeProcess(returncode=1, stderr=stderr, stderr_text="CUDA error: no device")

    monkeypatch.setattr(edge_runtime, "edge_status", lambda: _ready_edge_status())
    monkeypatch.setattr(edge_runtime, "edge_port_open", lambda timeout=0.4: False)
    monkeypatch.setattr(edge_runtime, "start_command", lambda: ["llama-server"])
    monkeypatch.setattr(edge_runtime.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError, match="CUDA error: no device"):
        start_edge(wait=5)


def test_start_edge_success_leaves_process(monkeypatch):
    fake = _FakeEdgeProcess()
    monkeypatch.setattr(edge_runtime, "edge_status", lambda: _ready_edge_status())
    monkeypatch.setattr(edge_runtime, "edge_port_open", lambda timeout=0.4: True)
    monkeypatch.setattr(edge_runtime, "start_command", lambda: ["llama-server"])
    monkeypatch.setattr(edge_runtime.subprocess, "Popen", lambda *args, **kwargs: fake)
    result = start_edge(wait=5)
    assert result["started"] is True
    assert result["pid"] == 4242
    assert fake.terminated is False


def test_default_gguf_uses_minicpm_or_env(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    models = root / "models"
    models.mkdir(parents=True)
    minicpm = models / "MiniCPM5-2B-Q4_K_M.gguf"
    minicpm.write_bytes(b"x")
    monkeypatch.delenv("LEX_EDGE_GGUF", raising=False)
    monkeypatch.setattr(edge_runtime, "repo_root", lambda: root)
    assert default_gguf() == minicpm
    configured = tmp_path / "custom.gguf"
    configured.write_bytes(b"z")
    monkeypatch.setenv("LEX_EDGE_GGUF", str(configured))
    assert default_gguf() == configured
