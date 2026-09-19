import json
from pathlib import Path

from lexaegis.registry import validate_pack
from lexaegis.runtime_pack import create_runtime_pack_from_bytes
from lexaegis.storage import Store

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "packs" / "labor_product_draft.json"
REPORT_PATH = ROOT / "docs" / "legal" / "reports" / "labor_product_import_report.json"
OFFICIAL_URL = "https://www.miit.gov.cn/jgsj/zfs/fl/art/2022/art_515a4b20c12f430eab54bb4f56d89f56.html"


def test_product_pack_schema_sources_and_review_gates_are_complete():
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    validated = validate_pack(pack)
    assert validated.id == "labor"
    assert validated.status == "draft"
    assert validated.legal_status == "pending_legal_review"
    assert validated.dispatch_allowed is False
    assert not validated.published_scope
    assert pack["rules"] == json.loads((ROOT / "packs/labor_v2_draft.json").read_text(encoding="utf-8"))["rules"]
    assert OFFICIAL_URL in "\n".join(pack["references"])

    sources = {source.id: source for source in validated.legal_sources}
    assert sources["ls_072_d63d0ad7d7"].articles == ["第56条"]
    assert sources["ls_072_d63d0ad7d7"].review_required
    assert sources["ls_073_097aeda387"].articles == ["第59条"]
    assert sources["ls_073_097aeda387"].review_required
    assert "至少保存三年" in sources["ls_072_d63d0ad7d7"].provision_text
    assert "采取必要措施" in sources["ls_073_097aeda387"].provision_text
    assert "lawyer_law_2026_09_01" not in sources
    conditions = {condition.id: condition for condition in validated.manual_review_conditions}
    assert {"pipia_trigger_content_unverified", "entrusted_processor_role_unverified", "legacy_lawyer_citation_unverified"} <= set(conditions)
    assert conditions["pipia_trigger_content_unverified"].legal_source_ids == ["ls_072_d63d0ad7d7"]
    assert conditions["entrusted_processor_role_unverified"].legal_source_ids == ["ls_073_097aeda387"]
    assert all(conditions[name].blocking for name in (
        "pipia_trigger_content_unverified", "entrusted_processor_role_unverified", "legacy_lawyer_citation_unverified"))
    assert report["status"] == "pending_review"
    assert report["dispatch_allowed"] is False
    assert report["sources_checked"][0]["official_source_url"] == OFFICIAL_URL


def test_product_pack_imports_as_blocked_request_runtime_draft(tmp_path):
    store = Store(tmp_path / "store.sqlite")
    with store.transaction() as repo:
        draft = create_runtime_pack_from_bytes(
            repo, PACK_PATH.read_bytes(), REPORT_PATH.read_bytes(), scope_kind="request")
    assert draft["source_pack_id"] == "pack:labor:3.0.0-product-draft.1"
    assert draft["scope_kind"] == "request"
    assert draft["status"] == "draft"
    assert draft["dispatch_allowed"] is False
    assert draft["pack"]["dispatch_allowed"] is False


def test_product_report_does_not_break_real_app_initialization(tmp_path, monkeypatch):
    from lexaegis.api import create_app

    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.delenv("LEX_DATA_DIR", raising=False)
    app = create_app(tmp_path / "app", password="unit-test-password")
    assert app.state.runtime_profile == "production"
    with app.state.store.read() as repo:
        packs = repo.list("pack")
    assert any(item.get("domain_id") == "labor" for item in packs)
    assert all(item.get("domain_id") != "labor_product_import_report" for item in packs)
