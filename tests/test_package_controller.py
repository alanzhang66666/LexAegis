"""V2.2 package distribution control plane: assignments, receipts, reconcile."""
import pytest

from lexaegis import package_controller
from lexaegis.package_controller import ControllerError
from lexaegis.storage import Store
from .conftest import login_admin
from .test_package_bundle import _labor_manifest


def _register(env, node="edge-node-1"):
    with env["app"].state.store.transaction() as repo:
        return package_controller.register_node(repo, node, "test-admin")


def _assign(env, node="edge-node-1"):
    with env["app"].state.store.read() as repo:
        manifest_id = _labor_manifest(repo)["id"]
    with env["app"].state.store.transaction() as repo:
        return package_controller.assign(repo, manifest_id, node, "test-admin")


def test_assign_deliver_activate_happy_path(env):
    _register(env)
    assignment = _assign(env)
    assert assignment["status"] == "assigned"
    with env["app"].state.store.transaction() as repo:
        bundle = package_controller.deliver(repo, assignment["id"], "test-admin")
        assert bundle["schema"]
        stored = repo.get(assignment["id"], "package_assignment")
        assert stored["status"] == "delivered"
        assert stored["bundle_hash"] == bundle["bundle_hash"]
        receipt = package_controller.record_receipt(
            repo, assignment["id"], "verified", "edge-node-1",
            manifest_hash=stored["manifest_hash"])
        assert receipt["status"] == "verified"
        receipt = package_controller.record_receipt(
            repo, assignment["id"], "activated", "edge-node-1")
        assert receipt["status"] == "active"


def test_assign_requires_registered_node(env):
    with env["app"].state.store.read() as repo:
        manifest_id = _labor_manifest(repo)["id"]
    with env["app"].state.store.transaction() as repo:
        with pytest.raises(ControllerError, match="未注册"):
            package_controller.assign(repo, manifest_id, "ghost-node", "test")


def test_assign_rejects_draft_manifest(env):
    _register(env)
    with env["app"].state.store.transaction() as repo:
        manifest = dict(_labor_manifest(repo))
        manifest["id"] = "manifest_draft_test"
        manifest["status"] = "draft"
        repo.put("domain_package_manifest", manifest)
        with pytest.raises(ControllerError, match="不可下发"):
            package_controller.assign(repo, manifest["id"], "edge-node-1", "test")


def test_receipt_from_wrong_node_rejected(env):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        package_controller.deliver(repo, assignment["id"], "test-admin")
        with pytest.raises(ControllerError, match="节点不符"):
            package_controller.record_receipt(
                repo, assignment["id"], "verified", "edge-node-2")


def test_receipt_hash_mismatch_fails_assignment(env):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        package_controller.deliver(repo, assignment["id"], "test-admin")
        with pytest.raises(ControllerError, match="manifest_hash"):
            package_controller.record_receipt(
                repo, assignment["id"], "verified", "edge-node-1",
                manifest_hash="bogus")
        stored = repo.get(assignment["id"], "package_assignment")
        assert stored["status"] == "failed"


def test_out_of_order_receipt_rejected(env):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        package_controller.deliver(repo, assignment["id"], "test-admin")
        with pytest.raises(ControllerError, match="不适用"):
            package_controller.record_receipt(
                repo, assignment["id"], "activated", "edge-node-1")


def test_revocation_waits_for_edge_receipt(env):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        package_controller.deliver(repo, assignment["id"], "test-admin")
        stored = package_controller.request_revocation(
            repo, assignment["id"], "test-admin", "license pulled")
        assert stored["status"] == "revoking"
        stored = package_controller.record_receipt(
            repo, assignment["id"], "revoked", "edge-node-1")
        assert stored["status"] == "revoked"


def test_failed_receipt_retries_then_terminal(env):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        for attempt in range(package_controller.MAX_ATTEMPTS):
            package_controller.deliver(repo, assignment["id"], "test-admin")
            stored = package_controller.record_receipt(
                repo, assignment["id"], "failed", "edge-node-1",
                detail={"error": "edge storage full"})
        assert stored["status"] == "failed"
        with pytest.raises(ControllerError, match="不可投递"):
            package_controller.deliver(repo, assignment["id"], "test-admin")


def test_reconcile_buckets(env):
    _register(env)
    pending = _assign(env)
    delivered = _assign.__wrapped__ if False else None
    with env["app"].state.store.read() as repo:
        report = package_controller.reconcile(repo)
        assert report["retry"][0]["id"] == pending["id"]
        assert report["ok"] == []
        report_node = package_controller.reconcile(repo, "edge-node-1")
        assert len(report_node["retry"]) == 1
        report_other = package_controller.reconcile(repo, "edge-node-2")
        assert report_other["retry"] == []


def test_edge_apply_and_revoke_roundtrip(env, tmp_path):
    _register(env)
    assignment = _assign(env)
    with env["app"].state.store.transaction() as repo:
        bundle = package_controller.deliver(repo, assignment["id"], "test-admin")
    edge = Store(tmp_path / "edge" / "app.sqlite")
    with edge.transaction() as edge_repo:
        receipt = package_controller.edge_apply(edge_repo, bundle, "edge-node-1")
        assert receipt["kind"] == "verified"
        assert receipt["manifest_hash"] == bundle["manifest"]["content_hash"]
        revoke_receipt = package_controller.edge_revoke(
            edge_repo, bundle["manifest"]["id"], "edge-node-1")
        assert revoke_receipt["kind"] == "revoked"
        manifest = edge_repo.get(bundle["manifest"]["id"], "domain_package_manifest")
        assert manifest["status"] == "revoked"


def test_controller_endpoints_require_admin(env):
    client = env["client"]
    login_admin(env)
    node = client.post("/api/v1/edge-nodes",
                       json={"edge_node_id": "edge-ep-1"})
    assert node.status_code == 200, node.text
    with env["app"].state.store.read() as repo:
        manifest_id = _labor_manifest(repo)["id"]
    created = client.post("/api/v1/package-assignments",
                          json={"manifest_id": manifest_id,
                                "edge_node_id": "edge-ep-1"})
    assert created.status_code == 200, created.text
    assignment_id = created.json()["id"]
    delivered = client.post(f"/api/v1/package-assignments/{assignment_id}/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["bundle_hash"]
    receipt = client.post(
        f"/api/v1/package-assignments/{assignment_id}/receipts",
        json={"kind": "verified", "edge_node_id": "edge-ep-1",
              "manifest_hash": delivered.json()["manifest"]["content_hash"]})
    assert receipt.status_code == 200, receipt.text
    report = client.get("/api/v1/package-distribution/reconcile")
    assert report.status_code == 200
    assert report.json()["awaiting_receipt"][0]["id"] == assignment_id
