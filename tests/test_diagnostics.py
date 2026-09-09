import subprocess
import sys

import pytest

from lexaegis import cli
from lexaegis.diagnostics import (
    compose_isolation_report,
    doctor_report,
    host_publish_capability,
    isolation_capability,
    legal_capability,
    parse_compose_host_bind,
    redteam_capability,
    resolve_redteam_url,
)
from lexaegis.parsing import register_ocr_provider
from lexaegis.storage import Store
from .test_redteam_workflow import frozen_protocol, KINDS


def test_resolve_redteam_url_native_default(monkeypatch):
    monkeypatch.delenv("LEX_REDTEAM_URL", raising=False)
    monkeypatch.delenv("LEX_ISOLATED", raising=False)
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    assert resolve_redteam_url() == "http://127.0.0.1:8767"


def test_resolve_redteam_url_isolated_compose_dns(monkeypatch):
    monkeypatch.delenv("LEX_REDTEAM_URL", raising=False)
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "isolated")
    monkeypatch.delenv("LEX_ISOLATED", raising=False)
    assert resolve_redteam_url() == "http://redteam:8767"
    monkeypatch.delenv("LEX_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("LEX_ISOLATED", "1")
    assert resolve_redteam_url() == "http://redteam:8767"


def test_resolve_redteam_url_explicit_wins(monkeypatch):
    monkeypatch.setenv("LEX_REDTEAM_URL", "http://example.invalid:9/")
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    assert resolve_redteam_url() == "http://example.invalid:9"


def test_compose_isolation_lists_unverified_gaps_without_docker(monkeypatch):
    monkeypatch.setattr(
        "lexaegis.diagnostics.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("docker not found")),
    )
    report = compose_isolation_report()
    assert report["ok"] is False
    assert report["gaps"] == [
        "未验收：未安装 Docker/Compose 或无法执行探测",
        "未验收：不是隔离拓扑",
        "未验收：出口仍开放",
        "未验收：卷或密钥隔离不正确",
    ]
    assert "未验收" in report["detail"]
    assert "isolation_verified" in report["detail"]


def test_native_check_isolation_does_not_record_verified(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEX_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    monkeypatch.delenv("LEX_ISOLATED", raising=False)
    monkeypatch.setattr(
        "lexaegis.diagnostics.compose_isolation_report",
        lambda: {
            "ok": False,
            "checks": {},
            "gaps": [
                "未验收：未安装 Docker/Compose 或无法执行探测",
                "未验收：不是隔离拓扑",
                "未验收：出口仍开放",
                "未验收：卷或密钥隔离不正确",
            ],
            "detail": "未验收。Docker Compose 不可用 未记录 isolation_verified。",
        },
    )
    record_calls = []

    def spy_run(cmd, *args, **kwargs):
        record_calls.append(cmd)
        raise AssertionError("check-isolation must not record when probes fail")

    monkeypatch.setattr(subprocess, "run", spy_run)
    store = Store(tmp_path / "app" / "app.sqlite")
    with store.transaction() as repo:
        repo.put("settings", {"id": "settings", "isolation_verified": False, "deployment_mode": "native"})
    monkeypatch.setattr(sys, "argv", ["lexaegis", "check-isolation"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "未验收" in out
    assert record_calls == []
    with store.read() as repo:
        assert repo.get("settings")["isolation_verified"] is False


def test_native_record_isolation_refuses_to_set_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    monkeypatch.delenv("LEX_ISOLATED", raising=False)
    store = Store(tmp_path / "app" / "app.sqlite")
    with store.transaction() as repo:
        repo.put("settings", {"id": "settings", "isolation_verified": False, "deployment_mode": "native"})
    monkeypatch.setattr(sys, "argv", ["lexaegis", "_record-isolation"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    with store.read() as repo:
        settings = repo.get("settings")
        assert settings["isolation_verified"] is False
        assert settings["deployment_mode"] == "native"


def test_check_isolation_records_only_when_probes_pass(monkeypatch, capsys):
    monkeypatch.setattr(
        "lexaegis.diagnostics.compose_isolation_report",
        lambda: {"ok": True, "checks": {"api_no_egress": True}, "gaps": []},
    )
    calls = []

    class Done:
        returncode = 0

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["lexaegis", "check-isolation"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert any("_record-isolation" in item for cmd in calls for item in cmd)


def test_doctor_native_isolation_does_not_fail_close(monkeypatch):
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    monkeypatch.delenv("LEX_ISOLATED", raising=False)
    report = doctor_report()
    note = report["checks"]["isolation"]
    assert note["ok"] is True
    assert note["status"] == "unconfigured"
    assert "未验收" in note["detail"]
    assert "native" in note["detail"]


def test_legal_capability_never_opens_product_dispatch():
    empty = legal_capability([])
    assert empty["status"] == "unconfigured"
    assert "formal_dispatch 保持阻断" in empty["detail"]
    published = legal_capability([
        {"schema_version": 2, "status": "published", "dispatch_allowed": True},
    ])
    assert published["status"] == "available"
    assert "dispatch_allowed=true" in published["detail"]
    assert "不等于法学验收" in published["detail"]
    assert "formal_dispatch 保持阻断" in published["detail"]


def test_isolation_capability_native_cannot_attest():
    available = isolation_capability({"isolation_verified": True, "deployment_mode": "isolated"})
    assert available["status"] == "available"
    native = isolation_capability({"isolation_verified": True, "deployment_mode": "native"})
    assert native["status"] == "unconfigured"
    assert "未验收" in native["detail"]


def test_redteam_capability_requires_reachable_host():
    protocols = [{"status": "frozen"}] * 4
    down = redteam_capability(protocols, probe={"ok": False, "detail": "红队服务不可达（http://127.0.0.1:8767）"})
    assert down["status"] == "unconfigured"
    assert "不可达" in down["detail"]
    assert "工程基线" in down["detail"]
    up = redteam_capability(protocols, probe={"ok": True})
    assert up["status"] == "available"
    assert "不确定" in up["detail"]
    assert "工程基线" in up["detail"]
    missing = redteam_capability([{"status": "draft"}], probe={"ok": True})
    assert missing["status"] == "unconfigured"


def test_parse_compose_host_bind_rejects_unpublished_and_non_loopback():
    assert parse_compose_host_bind("invalid IP:0") == ""
    assert parse_compose_host_bind("") == ""
    assert parse_compose_host_bind("0.0.0.0:38765") == ""
    assert parse_compose_host_bind("127.0.0.1:0") == ""
    assert parse_compose_host_bind("127.0.0.1:38765") == "127.0.0.1:38765"


def test_host_publish_isolated_api_cannot_attest_host_bind(monkeypatch):
    monkeypatch.setenv("LEX_RUNTIME_ROLE", "api")
    monkeypatch.setenv("LEX_ISOLATED", "1")

    def boom(*args, **kwargs):
        raise AssertionError("isolated api must not probe compose port")

    monkeypatch.setattr("lexaegis.diagnostics.compose_host_port_line", boom)
    report = host_publish_capability()
    assert report["ok"] is True
    assert report["status"] == "unconfigured"
    assert "不能证明宿主机发布" in report["detail"]


def test_host_publish_unpublished_does_not_fail_close():
    report = host_publish_capability(port_line="invalid IP:0")
    assert report["ok"] is True
    assert report["status"] == "unconfigured"
    assert report["bind"] == "invalid IP:0"
    assert "invalid IP:0" in report["detail"]
    assert "隔离探测通过不等于浏览器已通" in report["detail"]


def test_host_publish_available_when_loopback_health_ok(monkeypatch):
    class Resp:
        status_code = 200

    monkeypatch.setattr("lexaegis.diagnostics.httpx.get", lambda *args, **kwargs: Resp())
    report = host_publish_capability(port_line="127.0.0.1:38765")
    assert report["ok"] is True
    assert report["status"] == "available"
    assert report["bind"] == "127.0.0.1:38765"
    assert "健康检查 200" in report["detail"]
    assert "打开登录页" in report["detail"]


def test_doctor_host_publish_does_not_fail_close(monkeypatch):
    monkeypatch.setattr(
        "lexaegis.diagnostics.host_publish_capability",
        lambda **kwargs: {
            "ok": True,
            "status": "unconfigured",
            "bind": "invalid IP:0",
            "detail": "未验收：宿主机口未发布（invalid IP:0）；隔离探测通过不等于浏览器已通",
        },
    )
    report = doctor_report()
    assert report["ok"] is True
    check = report["checks"]["host_publish"]
    assert check["ok"] is True
    assert check["status"] == "unconfigured"


def test_capabilities_host_publish_separate_from_isolation(env, monkeypatch):
    monkeypatch.setattr(
        "lexaegis.api.host_publish_capability",
        lambda **kwargs: {
            "ok": True,
            "status": "unconfigured",
            "bind": "invalid IP:0",
            "detail": "未验收：宿主机口未发布（invalid IP:0）；隔离探测通过不等于浏览器已通",
        },
    )
    with env["app"].state.store.transaction() as repo:
        settings = repo.get("settings")
        settings["isolation_verified"] = True
        settings["deployment_mode"] = "isolated"
        repo.put("settings", settings)
    result = env["client"].get("/api/v1/capabilities").json()
    assert result["isolation"]["status"] == "available"
    assert result["host_publish"]["status"] == "unconfigured"
    assert result["host_publish"]["bind"] == "invalid IP:0"
    assert result["validation"]["formal_dispatch"] == "blocked"
    assert result["validation"]["status"] == "unconfigured"
    assert result["validation"]["host_publish"] == "unconfigured"
    detail = result["validation"]["detail"]
    assert "隔离部署已记录" in detail
    assert "宿主机发布仍未验收" in detail
    assert "浏览器已通" not in detail
    isolation_clause = next(part for part in detail.split("；") if "隔离部署" in part)
    assert "仍未验收" not in isolation_clause
    assert "formal_dispatch 保持阻断" in result["legal"]["detail"]


def test_capabilities_redteam_unconfigured_when_url_down(env, monkeypatch):
    monkeypatch.setenv("LEX_REDTEAM_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LEX_DEPLOYMENT_MODE", "native")
    with env["app"].state.store.transaction() as repo:
        for kind in KINDS:
            repo.put("risk_protocol", frozen_protocol(kind))
    result = env["client"].get("/api/v1/capabilities").json()
    assert result["redteam"]["status"] == "unconfigured"
    assert "不可达" in result["redteam"]["detail"]
    assert result["isolation"]["status"] == "unconfigured"
    assert "未验收" in result["isolation"]["detail"]


class _FakeOCR:
    provider_id = "fake"
    version = "1.2"

    def health(self):
        return {"status": "available", "detail": "test-only local provider"}

    def recognize(self, image):
        yield "模拟识别文本", 0.92, [10, 5, 90, 25]


def test_doctor_ocr_unconfigured_when_disabled(monkeypatch):
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    monkeypatch.delenv("LEX_OCR_MODELS_READY", raising=False)
    report = doctor_report()
    check = report["checks"]["ocr"]
    assert check["ok"] is True
    assert check["status"] == "unconfigured"
    assert "可选" in check["detail"]
    assert "人工" in check["detail"]
    assert report["ok"] is True


def test_doctor_ocr_unconfigured_when_models_not_attested(monkeypatch):
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "0")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "paddle")
    report = doctor_report()
    check = report["checks"]["ocr"]
    assert check["ok"] is True
    assert check["status"] == "unconfigured"
    assert "人工" in check["detail"]
    assert report["ok"] is True


def test_doctor_ocr_failed_when_ready_but_provider_missing(monkeypatch):
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "1")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "missing")
    report = doctor_report()
    check = report["checks"]["ocr"]
    assert check["ok"] is False
    assert check["status"] == "failed"
    assert report["ok"] is True


def test_doctor_ocr_available_with_registered_fake(monkeypatch):
    register_ocr_provider(_FakeOCR())
    monkeypatch.setenv("LEX_OCR_PROVIDER", "fake")
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.delenv("LEX_OCR_MODELS_READY", raising=False)
    report = doctor_report()
    check = report["checks"]["ocr"]
    assert check["ok"] is True
    assert check["status"] == "available"
    assert "精度" in check["detail"]
    assert report["ok"] is True


def test_doctor_ocr_failed_when_construct_raises(monkeypatch):
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "1")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "paddle")
    monkeypatch.setattr(
        "lexaegis.parsing.ocr_capability",
        lambda: {"status": "available", "provider": "paddle", "version": "3"},
    )
    monkeypatch.setattr(
        "lexaegis.diagnostics._ocr_construct_probe",
        lambda: (_ for _ in ()).throw(RuntimeError("construct")),
    )
    report = doctor_report()
    check = report["checks"]["ocr"]
    assert check["ok"] is False
    assert check["status"] == "failed"
    assert report["ok"] is True
