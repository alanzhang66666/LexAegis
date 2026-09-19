"""Restoring an old snapshot never reactivates send authority."""
import pytest

from lexaegis.cli import backup, restore
from lexaegis.runtime_identity import RuntimeIdentity
from lexaegis.runtime_profile import bind_runtime
from lexaegis.storage import Store
from lexaegis.upgrade import prepare_upgrade


def test_restore_same_build_invalidates_approvals_jobs_and_unconsumed_grants(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    source_app = tmp_path / "source-app"
    source_gateway = tmp_path / "source-gateway"
    bind_runtime(source_app, "app", "production")
    bind_runtime(source_gateway, "gateway", "production")
    identity = RuntimeIdentity("api", "verified", "same-build")

    app_store = Store(source_app / "app.sqlite")
    gateway_store = Store(source_gateway / "gateway.sqlite")
    prepare_upgrade(app_store, identity)
    with app_store.transaction() as repo:
        repo.put("formal_release_policy", {"id": "policy-issued", "status": "armed_once",
                  "consumed_dispatches": 0, "valid_from": "2026-09-01", "valid_until": "2026-10-01"})
        repo.put("formal_release_policy", {"id": "policy-reserved", "status": "armed_once",
                  "consumed_dispatches": 0, "valid_from": "2026-09-01", "valid_until": "2026-10-01"})
        repo.put("one_time_dispatch_grant", {"id": "grant-issued", "state": "issued",
                  "request_hash": "request-issued", "release_policy_id": "policy-issued"})
        repo.put("one_time_dispatch_grant", {"id": "grant-reserved", "state": "reserved",
                  "request_hash": "request-reserved", "release_policy_id": "policy-reserved"})
        repo.put("task", {"id": "approved", "case_id": "case-1", "status": "approved",
                  "approval": {"request_hash": "request-issued"}, "request_hash": "request-issued",
                  "formal_release": {"grant": {"id": "grant-issued"}}}, "case-1")
        repo.put("task", {"id": "queued", "case_id": "case-1", "status": "queued",
                  "approval": {"request_hash": "request-reserved"}, "request_hash": "request-reserved",
                  "formal_release": {"grant": {"id": "grant-reserved"}}}, "case-1")
        repo.put("task", {"id": "sending", "case_id": "case-1", "status": "sending",
                  "approval": {"request_hash": "request-sending"}}, "case-1")
        repo.put("task", {"id": "rejected", "case_id": "case-1", "status": "rejected",
                  "approval": {"historical": True}}, "case-1")
        repo.put("job", {"id": "send-queued", "case_id": "case-1", "status": "pending",
                  "kind": "send", "payload": {"task_id": "queued"}}, "case-1")
        repo.put("job", {"id": "send-sending", "case_id": "case-1", "status": "running",
                  "kind": "send", "payload": {"task_id": "sending"}}, "case-1")
        repo.put("review_history", {"id": "history-1", "task_id": "approved", "decision": "allowed"}, "case-1")

    with gateway_store.transaction() as repo:
        repo.put("formal_release_policy", {"id": "gateway-policy", "status": "armed_once",
                  "consumed_dispatches": 0, "valid_from": "2026-09-01", "valid_until": "2026-10-01"})
        repo.put("one_time_dispatch_grant", {"id": "gateway-grant", "state": "reserved",
                  "request_hash": "request-reserved", "release_policy_id": "gateway-policy"})
        repo.put("formal_release_claim", {"id": "gateway-claim-history", "state": "complete",
                  "request_hash": "old-completed-request"})

    archive = tmp_path / "before-send.lexbackup"
    backup(source_app, source_gateway, archive, "production")
    restored_app = tmp_path / "restored-app"
    restored_gateway = tmp_path / "restored-gateway"
    restore_state = restore(archive, restored_app, restored_gateway, "production")
    assert restore_state["review_required"] is True
    assert restore_state["app"]["status"] == "review_required"
    assert restore_state["gateway"]["status"] == "review_required"

    restored_store = Store(restored_app / "app.sqlite")
    with restored_store.read() as repo:
        assert repo.get("approved", "task")["status"] == "stale"
        assert repo.get("approved", "task")["approval"] is None
        assert repo.get("queued", "task")["status"] == "stale"
        assert repo.get("queued", "task")["approval"] is None
        assert repo.get("send-queued", "job")["status"] == "cancelled"
        assert repo.get("send-sending", "job")["status"] == "cancelled"
        sending = repo.get("sending", "task")
        assert sending["status"] == "unknown"
        assert sending["restore_reconciliation_required"] is True
        assert "禁止自动重发" in sending["error"]
        assert repo.get("rejected", "task")["status"] == "rejected"
        assert repo.get("rejected", "task")["approval"] == {"historical": True}
        assert repo.get("history-1", "review_history")["decision"] == "allowed"
        assert repo.get("grant-issued", "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("grant-reserved", "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("policy-issued", "formal_release_policy")["status"] == "blocked"
        assert repo.get("policy-reserved", "formal_release_policy")["status"] == "blocked"
        marker = repo.get("restore-review:app", "runtime_restore_state")
        assert marker["status"] == "review_required"
        assert marker["stale_task_count"] == 2
        assert marker["uncertain_task_count"] == 1
        original_fingerprint = repo.get("installed-application", "installed_application")["fingerprint"]

    # Same-build startup fast-path cannot reactivate the old snapshot: restore
    # state was committed independently and the task/grant transitions persist.
    prepare_upgrade(restored_store, identity)
    with restored_store.read() as repo:
        assert repo.get("installed-application", "installed_application")["fingerprint"] == original_fingerprint
        assert repo.get("approved", "task")["status"] == "stale"
        assert repo.get("grant-reserved", "one_time_dispatch_grant")["state"] == "revoked"

    with Store(restored_gateway / "gateway.sqlite").read() as repo:
        assert repo.get("gateway-grant", "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("gateway-policy", "formal_release_policy")["status"] == "blocked"
        assert repo.get("gateway-claim-history", "formal_release_claim")["state"] == "complete"
        assert repo.get("restore-review:gateway", "runtime_restore_state")["status"] == "review_required"


def _small_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    app = tmp_path / "snapshot-app"
    gateway = tmp_path / "snapshot-gateway"
    bind_runtime(app, "app", "production")
    bind_runtime(gateway, "gateway", "production")
    with Store(app / "app.sqlite").transaction() as repo:
        repo.put("task", {"id": "approved", "case_id": "case", "status": "approved",
                  "approval": {"request_hash": "r"}}, "case")
    with Store(gateway / "gateway.sqlite").transaction():
        pass
    archive = tmp_path / "snapshot.lexbackup"
    backup(app, gateway, archive, "production")
    return archive, tmp_path / "target-app", tmp_path / "target-gateway"


def _assert_restore_start_blocked(app, gateway):
    import pytest

    with pytest.raises(RuntimeError, match="restore is incomplete"):
        bind_runtime(app, "app", "production")
    with pytest.raises(RuntimeError, match="restore is incomplete"):
        bind_runtime(gateway, "gateway", "production")


def test_copy_failure_leaves_both_roots_blocked(tmp_path, monkeypatch):
    from pathlib import Path
    import pytest
    from lexaegis.cli import restore
    from lexaegis.runtime_profile import RESTORE_IN_PROGRESS

    archive, app, gateway = _small_snapshot(tmp_path, monkeypatch)
    original_open = Path.open

    def fail_gateway_database(self, mode="r", *args, **kwargs):
        if self == gateway / "gateway.sqlite" and mode == "xb":
            raise OSError("injected copy interruption")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_gateway_database)
    with pytest.raises(OSError, match="injected copy interruption"):
        restore(archive, app, gateway, "production")
    assert (app / RESTORE_IN_PROGRESS).is_file()
    assert (gateway / RESTORE_IN_PROGRESS).is_file()
    _assert_restore_start_blocked(app, gateway)


@pytest.mark.parametrize("failing_role", ["gateway", "app"])
def test_invalidation_failure_leaves_both_roots_blocked(tmp_path, monkeypatch, failing_role):
    import pytest
    from lexaegis import upgrade
    from lexaegis.cli import restore
    from lexaegis.runtime_profile import RESTORE_IN_PROGRESS

    archive, app, gateway = _small_snapshot(tmp_path, monkeypatch)
    original_prepare = upgrade.prepare_restore

    def fail_selected_store(store, *, role="app"):
        if role == failing_role:
            raise RuntimeError(f"injected {role} revocation failure")
        return original_prepare(store, role=role)

    monkeypatch.setattr(upgrade, "prepare_restore", fail_selected_store)
    with pytest.raises(RuntimeError, match=f"injected {failing_role} revocation failure"):
        restore(archive, app, gateway, "production")
    assert (app / RESTORE_IN_PROGRESS).is_file()
    assert (gateway / RESTORE_IN_PROGRESS).is_file()
    _assert_restore_start_blocked(app, gateway)
