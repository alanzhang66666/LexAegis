"""Invalidate unstarted approvals when the installed application changes."""
import hashlib
from pathlib import Path
from .storage import CURRENT_REVISION
from .util import audit, digest, now


def application_fingerprint(identity):
    package = Path(__file__).resolve().parent
    sources = {path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(package.rglob("*.py"))}
    return digest({"runtime": identity.public(), "migration": CURRENT_REVISION, "sources": sources})


def prepare_upgrade(store, identity):
    """Called before the API accepts traffic; never rewinds a migrated DB."""
    fingerprint = application_fingerprint(identity)
    with store.transaction() as repo:
        try:
            previous = repo.get("installed-application", "installed_application")
        except KeyError:
            previous = None
        if previous and previous.get("fingerprint") == fingerprint:
            return
        tasks = repo.list("task")
        if any(t.get("status") in {"sending", "unknown"} for t in tasks):
            raise ValueError("存在进行中或结果不明的调用；请使用原构建核对状态后升级")
        from . import orchestrator
        from .release_service import revoke
        for task in tasks:
            if task.get("status") in {"complete", "failed", "stopped", "rejected"}:
                continue
            revoke(repo, task, "应用构建升级，原批准失效")
            orchestrator.transition_task(repo, task, "stale", "STATE_TRANSITION",
                                         approval=None, stale=True, actor="system:upgrade")
            repo.put("task", task, task["case_id"])
            for job in repo.list("job", task["case_id"]):
                if job.get("payload", {}).get("task_id") == task["id"] and job.get("status") in {"pending", "running"}:
                    job.update(status="cancelled", error="应用升级，须创建新任务并重新复核")
                    repo.put("job", job, task["case_id"])
            audit(repo, task["case_id"], "approval.invalidated_by_upgrade", task_id=task["id"])
        repo.put("installed_application", {"id": "installed-application", "fingerprint": fingerprint,
                                           "runtime_identity": identity.public(), "installed_at": now()})


_RESTORE_TERMINAL_TASK_STATES = frozenset({"complete", "failed", "stopped", "rejected"})
_UNCONSUMED_GRANT_STATES = frozenset({"pending", "issued", "reserved"})


def prepare_restore(store, *, role="app"):
    """Invalidate send authority in a restored snapshot without changing build identity.

    Restores intentionally require a fresh human review even when the runtime
    fingerprint is unchanged. Gateway-side claims and terminal records remain
    untouched; only grants that had not crossed the durable claim boundary are
    revoked. A restored ``sending`` task is made explicitly uncertain.
    """
    if role not in {"app", "gateway"}:
        raise ValueError("restore role must be app or gateway")
    reason = "从备份恢复；必须重新复核，不得恢复旧发送授权"
    with store.transaction() as repo:
        grants = repo.list("one_time_dispatch_grant")
        revoked_grant_ids = set()
        for grant in grants:
            if grant.get("state") not in _UNCONSUMED_GRANT_STATES:
                continue
            grant["state"] = "revoked"
            grant["revoked_at"] = now()
            grant["revoked_reason"] = reason
            repo.put("one_time_dispatch_grant", grant)
            revoked_grant_ids.add(grant.get("id"))
        revoked_policy_ids = set()
        for policy in repo.list("formal_release_policy"):
            if (policy.get("status") == "armed_once"
                    and int(policy.get("consumed_dispatches") or 0) == 0):
                policy.update(status="blocked", valid_from=None, valid_until=None,
                              revoked_reason=reason)
                repo.put("formal_release_policy", policy)
                revoked_policy_ids.add(policy.get("id"))

        stale_task_ids = set()
        uncertain_task_ids = set()
        uncertain_previous_status = {}
        if role == "app":
            from . import orchestrator
            for task in repo.list("task"):
                state = task.get("status")
                if state in _RESTORE_TERMINAL_TASK_STATES:
                    continue
                task["approval"] = None
                task["stale"] = True
                if state in {"sending", "unknown"}:
                    uncertain_previous_status[task["id"]] = state
                    orchestrator.transition_task(
                        repo, task, "unknown", "STATE_TRANSITION",
                        actor="system:restore")
                    task["restore_reconciliation_required"] = True
                    task["error"] = "恢复的备份含发送中或结果不明请求；需核对网关与服务商记录，禁止自动重发。"
                    uncertain_task_ids.add(task["id"])
                else:
                    orchestrator.transition_task(
                        repo, task, "stale", "STATE_TRANSITION",
                        actor="system:restore")
                    stale_task_ids.add(task["id"])

                formal = task.get("formal_release") or {}
                grant_data = formal.get("grant") or {}
                grant_id = grant_data.get("id")
                if grant_id in revoked_grant_ids:
                    grant = next(item for item in grants if item.get("id") == grant_id)
                    formal["grant"] = grant
                    policy_id = grant.get("release_policy_id")
                    if policy_id in revoked_policy_ids:
                        formal["policy"] = next(
                            item for item in repo.list("formal_release_policy") if item.get("id") == policy_id)
                    task["formal_release"] = formal
                repo.put("task", task, task.get("case_id", ""))

            invalidated_task_ids = stale_task_ids | uncertain_task_ids
            for job in repo.list("job"):
                task_id = job.get("task_id") or (job.get("payload") or {}).get("task_id")
                if task_id in invalidated_task_ids and job.get("status") in {"pending", "running"}:
                    job.update(status="cancelled", error=reason, cancelled_at=now())
                    repo.put("job", job, job.get("case_id", ""))
            for task_id in sorted(stale_task_ids):
                task = repo.get(task_id, "task")
                audit(repo, task.get("case_id", ""), "approval.invalidated_by_restore",
                      task_id=task_id, reason=reason)
            for task_id in sorted(uncertain_task_ids):
                task = repo.get(task_id, "task")
                audit(repo, task.get("case_id", ""), "dispatch.reconciliation_required_after_restore",
                      task_id=task_id, previous_status=uncertain_previous_status[task_id])

        record_id = f"restore-review:{role}"
        try:
            previous = repo.get(record_id, "runtime_restore_state")
            generation = int(previous.get("generation", 0)) + 1
        except KeyError:
            generation = 1
        marker = {"id": record_id, "role": role, "status": "review_required",
                  "reason": reason, "generation": generation, "restored_at": now(),
                  "revoked_grant_count": len(revoked_grant_ids),
                  "revoked_policy_count": len(revoked_policy_ids),
                  "stale_task_count": len(stale_task_ids),
                  "uncertain_task_count": len(uncertain_task_ids)}
        repo.put("runtime_restore_state", marker)
        audit(repo, "", "runtime.restore_review_required", role=role,
              revoked_grant_count=len(revoked_grant_ids),
              revoked_policy_count=len(revoked_policy_ids),
              stale_task_count=len(stale_task_ids),
              uncertain_task_count=len(uncertain_task_ids))
        return marker
