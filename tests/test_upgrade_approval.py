import pytest
from lexaegis.storage import Store
from lexaegis.runtime_identity import RuntimeIdentity
from lexaegis.upgrade import prepare_upgrade


def test_upgrade_invalidates_unstarted_tasks_but_preserves_rejection(tmp_path):
    store = Store(tmp_path / "upgrade.sqlite")
    old = RuntimeIdentity("api", "verified", "old")
    new = RuntimeIdentity("api", "verified", "new")
    prepare_upgrade(store, old)
    with store.transaction() as repo:
        for state in ("approved", "queued", "rejected"):
            repo.put("task", {"id": state, "case_id": "c", "status": state, "approval": {"id": "a"}}, "c")
        repo.put("job", {"id": "send", "case_id": "c", "status": "pending", "payload": {"task_id": "queued"}}, "c")
    prepare_upgrade(store, new)
    with store.read() as repo:
        assert repo.get("approved")["approval"] is None
        assert repo.get("queued")["stale"] is True
        assert repo.get("send")["status"] == "cancelled"
        assert repo.get("rejected")["status"] == "rejected"


@pytest.mark.parametrize("status", ["sending", "unknown"])
def test_upgrade_waits_for_inflight_reconciliation(tmp_path, status):
    store = Store(tmp_path / "upgrade.sqlite")
    old = RuntimeIdentity("api", "verified", "old")
    prepare_upgrade(store, old)
    with store.transaction() as repo:
        repo.put("task", {"id": "task", "case_id": "c", "status": status}, "c")
    # A restart of the same build can reconcile, but an upgrade is refused.
    prepare_upgrade(store, old)
    with pytest.raises(ValueError, match="原构建"):
        prepare_upgrade(store, RuntimeIdentity("api", "verified", "new"))
