from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "kubeedge_local_drill.py"
spec = importlib.util.spec_from_file_location("kubeedge_local_drill", SCRIPT)
assert spec and spec.loader
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def test_password_is_required_and_never_default(monkeypatch):
    monkeypatch.delenv("LEX_KUBEEDGE_DRILL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="LEX_KUBEEDGE_DRILL_PASSWORD"):
        drill.require_password()
    monkeypatch.setenv("LEX_KUBEEDGE_DRILL_PASSWORD", "synthetic-secret")
    assert drill.require_password() == "synthetic-secret"
    assert "cloud-drill-password" not in SCRIPT.read_text()


def test_safe_text_redacts_secret_request_and_absolute_path():
    value = "password=secret token=abc request_body=case /Users/alice/private.txt"
    redacted = drill.safe_text(value)
    assert "secret" not in redacted
    assert "abc" not in redacted
    assert "/Users/alice" not in redacted
    assert "<redacted>" in redacted
    assert "<path>" in redacted


def test_report_has_strict_kubeedge_result_keys(monkeypatch):
    args = type("Args", (), {"source_commit": SHA, "image": [f"edge={DIGEST}"], "json_report": None})()
    results = {key: True for key in ("registration", "delivery", "disconnect", "bundle_absent_while_disconnected", "reconnect", "bundle_synced", "revocation", "reconcile")}
    report = drill.build_report(args, "pass", results)
    assert report["check_id"] == "k8s_conformance"
    assert set(report["results"]) == set(results)
    assert report["source_commit"] == SHA
    assert report["image_digests"] == {"edge": DIGEST}
    assert report["redaction_profile"] == "synthetic-v1"


def test_missing_password_fails_closed_and_writes_safe_failure_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LEX_KUBEEDGE_DRILL_PASSWORD", raising=False)
    out = tmp_path / "drill.json"
    md = tmp_path / "drill.md"
    code = drill.main(["--json-report", str(out), "--report", str(md), "--source-commit", SHA, "--image", f"edge={DIGEST}"])
    assert code == 1
    payload = json.loads(out.read_text())
    assert payload["status"] == "fail"
    assert not any(payload["results"].values())
    assert "password" not in out.read_text().lower()
    assert "synthetic-secret" not in capsys.readouterr().out


def test_invalid_image_digest_is_rejected():
    args = type("Args", (), {"source_commit": SHA, "image": ["edge=latest"], "json_report": None})()
    with pytest.raises(RuntimeError, match="image digest"):
        drill.build_report(args, "fail", {})
