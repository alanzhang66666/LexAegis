"""Synthetic reapproval recovery; no real identity, credentials, or network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lexaegis import service
from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
from lexaegis.worker import process_one
from tests.conftest import login_as, login_admin
from tests.test_v3_grant_snapshot_binding import approved  # pytest fixture


def reset(repo, task, *, actor="审批人甲", role="approver", reason="证据变更，重新审批"):
    return service.prepare_formal_reapproval(
        repo, task["id"], task["request_hash"], reason=reason,
        actor=actor, actor_role=role, actor_user_id="synthetic-user")


def test_issued_stale_grant_reset_requires_fresh_human_approval_then_sends_once(approved):
    f = approved
    f["register"]("G3", "法03")
    with f["store"].transaction() as repo:
        old = repo.get(f["task"]["id"], "task")
        grant_id = old["formal_release"]["grant"]["id"]
        with pytest.raises(ValueError, match="证据快照已变化"):
            service.reserve_send(repo, old["id"], release_context=f["context"])
        result = reset(repo, old)
        assert result["status"] == "review" and result["approval"] is None
        assert result["request_hash"] == old["request_hash"]
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "blocked"
        assert len(repo.list("one_time_dispatch_grant")) == 1
        assert any(a["event"] == "formal_release.reapproval_prepared" for a in repo.list("audit", old["case_id"]))
    with f["store"].transaction() as repo:
        fresh = service.approve_task(repo, old["id"], old["request_hash"], actor="审批人甲",
                                     actor_role="approver", actor_user_id="synthetic-user",
                                     release_context=f["context"])
        new_id = fresh["formal_release"]["grant"]["id"]
        assert new_id != grant_id
        service.reserve_send(repo, fresh["id"], release_context=f["context"])
    with TestClient(f["gateway"]) as client:
        assert process_one(f["store"], f["root"], gateway_client=client)
        assert process_one(f["store"], f["root"], gateway_client=client) is False
    assert f["provider"].calls == 1
    with f["store"].read() as repo:
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get(new_id, "one_time_dispatch_grant")["state"] == "consumed"


def test_already_revoked_receipt_grant_disarms_unconsumed_policy(approved):
    f = approved
    with f["store"].read() as repo:
        receipt = next(x for x in repo.list("gate_evidence_receipt") if x["gate_id"] == "G3" and x["template_kind"] == "法03")
    intake = EvidenceIntakeService(EvidenceStore(f["store"], f["root"] / "release-evidence"))
    intake.revoke_evidence(receipt["id"], "synthetic revoke", actor="法学甲", actor_role="legal_reviewer")
    with f["store"].transaction() as repo:
        old = repo.get(f["task"]["id"], "task")
        grant_id = old["formal_release"]["grant"]["id"]
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"
        result = reset(repo, old)
        assert result["approval"] is None and result["status"] == "review"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "blocked"
        assert repo.get("v3-policy", "formal_release_policy")["consumed_dispatches"] == 0
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError, match="正式放行未满足"):
            service.approve_task(repo, old["id"], old["request_hash"], actor="审批人甲", actor_role="approver",
                                 actor_user_id="synthetic-user", release_context=f["context"])
    f["register"]("G3", "法03")
    with f["store"].transaction() as repo:
        fresh = service.approve_task(repo, old["id"], old["request_hash"], actor="审批人甲", actor_role="approver",
                                     actor_user_id="synthetic-user", release_context=f["context"])
        assert fresh["formal_release"]["grant"]["id"] != grant_id


@pytest.mark.parametrize("state", ["queued", "sending", "complete", "unknown", "rejected"])
def test_nonapproved_task_never_reopens(approved, state):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        task["status"] = state
        repo.put("task", task, task["case_id"])
        before = deepcopy(repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant"))
        with pytest.raises(ValueError): reset(repo, task)
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant") == before
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


@pytest.mark.parametrize("state", ["reserved", "claimed", "consumed"])
def test_used_or_reserved_grant_never_reopens(approved, state):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        grant_id = task["formal_release"]["grant"]["id"]
        grant = repo.get(grant_id, "one_time_dispatch_grant")
        grant["state"] = state
        repo.put("one_time_dispatch_grant", grant)
        with pytest.raises(ValueError): reset(repo, task)
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == state
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


def test_durable_claim_blocks_reset_even_if_task_and_grant_look_unclaimed(approved):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        repo.conn.execute(text("INSERT INTO formal_release_claims(id, request_hash, policy_id, policy_slot) VALUES(:i,:h,:p,1)"),
                          {"i": "synthetic-claim", "h": task["request_hash"], "p": "v3-policy"})
        with pytest.raises(ValueError): reset(repo, task)
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "issued"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


def test_other_active_grant_for_same_policy_blocks_reset(approved):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        duplicate = deepcopy(repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant"))
        duplicate.update(id="synthetic-other-grant", nonce="synthetic-other-nonce")
        repo.put("one_time_dispatch_grant", duplicate)
        with pytest.raises(ValueError): reset(repo, task)
        assert repo.get(duplicate["id"], "one_time_dispatch_grant")["state"] == "issued"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


def test_expired_grant_can_be_retired_without_consuming_policy(approved):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        grant_id = task["formal_release"]["grant"]["id"]
        grant = repo.get(grant_id, "one_time_dispatch_grant")
        grant["state"] = "expired"
        repo.put("one_time_dispatch_grant", grant)
        result = reset(repo, task)
        assert result["status"] == "review" and result["approval"] is None
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "expired"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "blocked"


@pytest.mark.parametrize("record_kind", ["job", "disclosure", "other_policy_claim"])
def test_dispatch_history_even_with_misleading_task_state_blocks_reset(approved, record_kind):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        if record_kind == "job":
            repo.put("job", {"id": "synthetic-job", "kind": "send", "status": "failed",
                             "payload": {"task_id": task["id"]}}, task["case_id"])
        elif record_kind == "disclosure":
            repo.put("disclosure", {"id": task["request"]["request_id"], "status": "reserved"}, task["case_id"])
        else:
            repo.conn.execute(text("INSERT INTO formal_release_claims(id, request_hash, policy_id, policy_slot) VALUES(:i,:h,:p,1)"),
                              {"i": "other-request-claim", "h": "another-request", "p": "v3-policy"})
        with pytest.raises(ValueError): reset(repo, task)
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "issued"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


@pytest.mark.parametrize("role,reason", [("legal_reviewer", "x"), ("admin", "x"), ("approver", "  ")])
def test_invalid_actor_or_reason_is_rejected(approved, role, reason):
    f = approved
    with f["store"].transaction() as repo:
        task = repo.get(f["task"]["id"], "task")
        with pytest.raises(ValueError): reset(repo, task, role=role, reason=reason)
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "issued"


def test_atomic_reset_rolls_back_grant_policy_and_task_on_error(approved, monkeypatch):
    from lexaegis import orchestrator
    f = approved
    with f["store"].read() as repo:
        original = repo.get(f["task"]["id"], "task")
        grant_id = original["formal_release"]["grant"]["id"]
    def fail(*args, **kwargs): raise RuntimeError("synthetic transition failure")
    monkeypatch.setattr(orchestrator, "transition_task", fail)
    with pytest.raises(RuntimeError, match="synthetic transition failure"):
        with f["store"].transaction() as repo: reset(repo, original)
    with f["store"].read() as repo:
        assert repo.get(original["id"], "task") == original
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "issued"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "armed_once"


def test_concurrent_resets_have_one_success(approved):
    f = approved
    def attempt(_):
        try:
            with f["store"].transaction() as repo:
                return reset(repo, repo.get(f["task"]["id"], "task"))["status"]
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["rejected", "review"]


def test_endpoint_requires_exact_approver_role(env):
    client = env["client"]
    path = "/api/v1/tasks/no-such-task/formal-release/reapproval"
    body = {"request_hash": "a" * 64, "reason": "synthetic"}
    assert client.post(path, json=body).status_code == 403
    login_as(env, "legal_reviewer")
    assert client.post(path, json=body).status_code == 403
    login_as(env, "approver")
    assert client.post(path, json=body).status_code == 404
    login_admin(env)


def test_actual_http_approver_reset_clears_approval_without_authorizing_send(env, approved):
    f = approved
    with f["store"].read() as source:
        task = source.get(f["task"]["id"], "task")
        case = source.get(task["case_id"], "case")
        records = [(kind, source.list(kind)) for kind in ("pack", "provider", "formal_release_policy", "one_time_dispatch_grant")]
    with env["app"].state.store.transaction() as target:
        target.put("case", case)
        target.put("task", task, case["id"])
        for kind, rows in records:
            for row in rows:
                target.put(kind, row)
    login_as(env, "approver")
    path = f"/api/v1/tasks/{task['id']}/formal-release/reapproval"
    bad = env["client"].post(path, json={"request_hash": "f" * 64, "reason": "synthetic"})
    assert bad.status_code == 409
    response = env["client"].post(path, json={"request_hash": task["request_hash"], "reason": "synthetic change"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "review" and response.json()["approval"] is None
    with env["app"].state.store.read() as repo:
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "blocked"
        events = [r for r in repo.list("audit", case["id"]) if r["event"] == "formal_release.reapproval_prepared"]
        assert len(events) == 1 and events[0]["metadata"]["actor_role"] == "approver"
    assert f["provider"].calls == 0
