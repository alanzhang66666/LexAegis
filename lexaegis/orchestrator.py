"""V2.2 Orchestrator (P4): single funnel for task status transitions.

Every status change should go through ``transition_task`` so the TaskStep
record and the task's status field can never drift apart. ``derive_status``
recomputes the expected status from the recorded steps — the authority flag
``LEX_ORCHESTRATOR_AUTHORITY=1`` turns consistency checks into hard failures
(dual-write remains the default until the migration is complete).
"""
import os

from . import domain_runtime


AUTHORITY_ENV = "LEX_ORCHESTRATOR_AUTHORITY"

# Step types whose ``to_status`` is a real task status. VALIDATION and CLOUD
# are observation channels instead: return-pipeline stage labels
# ("return:hash:ok") and the waiting-cloud connectivity marker are not task
# statuses, so they must never feed ``derive_status``.
_STATUS_STEPS = {"LOCAL", "CONTROL", "HUMAN", "STATE_TRANSITION"}


def authority_enabled():
    return os.getenv(AUTHORITY_ENV, "").strip() in {"1", "true", "yes"}


def transition_task(repo, task, to_status=None, step_type="STATE_TRANSITION",
                    actor=None, from_status=None, **updates):
    """Funnel: apply field updates, set status, record the TaskStep — always
    together. ``to_status=None`` re-records the already-updated status (for
    call sites that set fields in bulk before the transition)."""
    if from_status is None:
        from_status = task.get("status")
    if updates:
        task.update(updates)
    if to_status is not None:
        task["status"] = to_status
    domain_runtime.record_task_step(
        repo, task, step_type, task["status"], from_status=from_status, actor=actor)
    return task


def derive_status(repo, task_id, case_id):
    """Recompute expected status from recorded steps; None when no steps
    exist (legacy tasks — their status field stays authoritative)."""
    steps = [
        s for s in repo.list("task_step", case_id)
        if s.get("task_id") == task_id and s.get("step_type") in _STATUS_STEPS
    ]
    if not steps:
        return None
    return steps[-1].get("to_status")


def consistent(repo, task):
    """Whether the task's status matches the status derived from its steps.
    Tasks without steps are consistent by definition (legacy path)."""
    derived = derive_status(repo, task["id"], task["case_id"])
    return derived is None or derived == task.get("status")


def assert_consistent(repo, task):
    """Under the authority flag, drift between status and steps is fatal."""
    if not authority_enabled():
        return
    derived = derive_status(repo, task["id"], task["case_id"])
    if derived is not None and derived != task.get("status"):
        raise domain_runtime.DomainRuntimeError(
            f"orchestrator_inconsistent: task {task['id']} status "
            f"{task.get('status')} != derived {derived}")
