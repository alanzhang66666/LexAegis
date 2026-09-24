"""V2.2 package distribution bundle: export/import (cloud -> edge link)."""
import pytest

from lexaegis import domain_packages
from lexaegis.domain_packages import (
    DomainPackageError, export_bundle, import_bundle,
)
from lexaegis.storage import Store
from .conftest import login_admin

SIGNING_KEY = "bundle-test-signing-key-32chars"


def _labor_manifest(repo):
    return next(m for m in repo.list("domain_package_manifest")
                if m["cause_id"] == "labor" and "product" not in m["version"])


def test_export_bundle_carries_manifest_and_packages(env):
    with env["app"].state.store.read() as repo:
        manifest = _labor_manifest(repo)
        bundle = export_bundle(repo, manifest["id"])
    assert bundle["schema"] == domain_packages.BUNDLE_SCHEMA
    assert bundle["manifest"]["id"] == manifest["id"]
    assert bundle["bundle_hash"]
    refs = manifest["package_refs"]
    assert len(bundle["packages"]) == sum(len(v) for v in refs.values())
    # unsigned by default — no key configured in tests
    assert "signature" not in bundle


def test_import_bundle_downgrades_unsigned_status(env, tmp_path):
    with env["app"].state.store.read() as repo:
        bundle = export_bundle(repo, _labor_manifest(repo)["id"])
    edge = Store(tmp_path / "edge" / "app.sqlite")
    with edge.transaction() as repo2:
        result = import_bundle(repo2, bundle)
    assert result["packages"] == len(bundle["packages"])
    assert result["downgraded"]  # seeded packages are validated but unsigned
    with edge.read() as repo2:
        assert all(p["status"] == "draft" for p in repo2.list("domain_package"))
        manifest = repo2.get(bundle["manifest"]["id"], "domain_package_manifest")
        assert manifest["status"] == "draft"


def test_signed_bundle_preserves_status(env, tmp_path):
    with env["app"].state.store.transaction() as repo:
        manifest = _labor_manifest(repo)
        for refs in manifest["package_refs"].values():
            for ref in refs:
                domain_packages.transition(repo, domain_packages.PACKAGE_KIND,
                                           ref["id"], "signed",
                                           actor="test", signing_key=SIGNING_KEY)
        domain_packages.transition(repo, domain_packages.MANIFEST_KIND,
                                   manifest["id"], "signed",
                                   actor="test", signing_key=SIGNING_KEY)
        bundle = export_bundle(repo, manifest["id"], signing_key=SIGNING_KEY)
    assert bundle.get("signature")
    edge = Store(tmp_path / "edge2" / "app.sqlite")
    with edge.transaction() as repo2:
        result = import_bundle(repo2, bundle, signing_key=SIGNING_KEY)
    assert result["downgraded"] == []
    with edge.read() as repo2:
        assert all(p["status"] == "signed" for p in repo2.list("domain_package"))
        assert repo2.get(bundle["manifest"]["id"],
                         "domain_package_manifest")["status"] == "signed"


def test_tampered_bundle_rejected(env, tmp_path):
    with env["app"].state.store.read() as repo:
        bundle = export_bundle(repo, _labor_manifest(repo)["id"])
    edge = Store(tmp_path / "edge3" / "app.sqlite")
    bundle["packages"][0]["content"]["rules"] = [{"tampered": True}]
    with edge.transaction() as repo2, pytest.raises(DomainPackageError):
        import_bundle(repo2, bundle)
    with edge.read() as repo2:
        assert repo2.list("domain_package") == []


def test_wrong_platform_api_rejected(env, tmp_path):
    with env["app"].state.store.read() as repo:
        bundle = export_bundle(repo, _labor_manifest(repo)["id"])
    from lexaegis.domain_packages import _package_content_hash
    from lexaegis.util import digest
    for package in bundle["packages"]:
        package["platform_api"] = "v99"
        package["content_hash"] = _package_content_hash(package)
    bundle["bundle_hash"] = digest({
        "manifest_hash": bundle["manifest"]["content_hash"],
        "package_hashes": sorted(p["content_hash"] for p in bundle["packages"]),
    })
    edge = Store(tmp_path / "edge4" / "app.sqlite")
    with edge.transaction() as repo2, pytest.raises(DomainPackageError):
        import_bundle(repo2, bundle)


def test_bundle_endpoints_require_admin(env):
    client = env["client"]
    login_admin(env)
    with env["app"].state.store.read() as repo:
        manifest_id = _labor_manifest(repo)["id"]
    exported = client.get(f"/api/v1/domain-package-manifests/{manifest_id}/bundle")
    assert exported.status_code == 200
    imported = client.post("/api/v1/domain-packages/import-bundle",
                           json={"bundle": exported.json()})
    assert imported.status_code == 200, imported.text
    assert imported.json()["manifest"] == manifest_id
