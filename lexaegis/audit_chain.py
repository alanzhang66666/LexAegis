"""Audit predecessor-hash chain verification and request-bound evidence manifest.

Each audit entry carries `prev_hash` (the entry_hash of the previous record in
the same scope) and `entry_hash` (digest of at/actor/event/metadata/prev_hash).
Verification replays the chain per scope; any edit, deletion or reorder breaks it.

The evidence manifest binds every artifact class to the exact request_hash so a
reviewer can export "what evidence backed this request" without touching case
material. Only identifiers, hashes and statuses are exported — never wire
payloads, fact text, mappings or document content.
"""
from __future__ import annotations

from .util import digest, now

_CHAIN_FIELDS = ("at", "actor", "event", "metadata", "prev_hash")


def verify_audit_chain(repo, scope) -> list[str]:
    """Return integrity problems for the audit chain in one scope ([] = intact)."""
    problems = []
    previous = ""
    for entry in repo.list("audit", scope):
        if entry.get("prev_hash", "") != previous:
            problems.append(f"{entry.get('id')}: prev_hash 断链")
        expected = digest({key: entry.get(key) for key in _CHAIN_FIELDS})
        if entry.get("entry_hash") != expected:
            problems.append(f"{entry.get('id')}: entry_hash 与内容不符")
        previous = entry.get("entry_hash") or ""
    return problems


def _receipt_summary(item: dict) -> dict:
    return {
        "id": item.get("id"), "gate_id": item.get("gate_id"),
        "template_kind": item.get("template_kind"), "conclusion": item.get("conclusion"),
        "confirmed_by": item.get("confirmed_by"), "confirmed_role": item.get("confirmed_role"),
        "evidence_manifest_hash": item.get("evidence_manifest_hash"),
        "valid_until": item.get("valid_until"), "revoked_at": item.get("revoked_at"),
    }


def _isolation_summary(item: dict) -> dict:
    return {
        "id": item.get("id"), "status": item.get("status"),
        "deployment_mode": item.get("deployment_mode"),
        "build_manifest_hash": item.get("build_manifest_hash"),
        "evidence_artifact_ids": item.get("evidence_artifact_ids"),
        "attested_by": item.get("attested_by"),
        "legal_confirmation_receipt_id": item.get("legal_confirmation_receipt_id"),
        "expires_at": item.get("expires_at"),
    }


def _attack_run_summary(item: dict) -> dict:
    return {
        "id": item.get("id"), "protocol_id": item.get("protocol_id"),
        "protocol_hash": item.get("protocol_hash"), "outcome": item.get("outcome"),
        "result_hash": item.get("result_hash"), "executor_version": item.get("executor_version"),
        "suite_id": item.get("suite_id"), "attack_input_hash": item.get("attack_input_hash"),
    }


def export_evidence_manifest(repo, task_id: str) -> dict:
    """Hash-only manifest of everything bound to this task's request_hash."""
    task = repo.get(task_id, "task")
    request_hash = task.get("request_hash")
    suites = [item for item in repo.list("attack_suite_run", task_id)]
    runs = [item for item in repo.list("attack_run", task_id)
            if not request_hash or item.get("request_hash") in (None, request_hash)]
    audit_entries = [
        item for item in repo.list("audit", task.get("case_id"))
        if item.get("metadata", {}).get("task_id") == task_id
        or item.get("metadata", {}).get("request_hash") == request_hash
    ]
    manifest = {
        "task_id": task_id,
        "case_id": task.get("case_id"),
        "request_hash": request_hash,
        "generated_at": now(),
        "gate_snapshot": [
            {"id": hit.get("id"), "message": hit.get("message"), "kind": hit.get("kind")}
            for hit in ((task.get("risk") or {}).get("gates") or [])
        ],
        "approval": bool(task.get("approval")),
        "gate_receipts": [
            _receipt_summary(item) for item in repo.list("gate_evidence_receipt")
            if item.get("request_hash") == request_hash
        ],
        "isolation_receipts": [
            _isolation_summary(item) for item in repo.list("isolation_receipt")
            if item.get("request_hash") == request_hash
        ],
        "attack_suites": [
            {"id": item.get("id"), "suite_hash": item.get("suite_hash"),
             "conclusion": item.get("conclusion"), "all_resisted": item.get("all_resisted"),
             "executor_version": item.get("executor_version"),
             "positive_control_detected": (item.get("positive_control") or {}).get("detected")}
            for item in suites
        ],
        "attack_runs": [_attack_run_summary(item) for item in runs],
        "cloud_result_envelopes": [
            {"id": item.get("id"), "status": item.get("pipeline_status"),
             "result_hash": item.get("result_hash"), "provenance": item.get("provenance")}
            for item in repo.list("cloud_result_envelope", task.get("case_id"))
            if item.get("task_id") == task_id
        ],
        "human_decisions": [
            {"id": item.get("id"), "decision": item.get("decision"),
             "actor": item.get("actor"), "artifact_hash": item.get("artifact_hash")}
            for item in repo.list("human_decision", task.get("case_id"))
            if item.get("task_id") == task_id
        ],
        "audit_chain": [
            {"id": item.get("id"), "event": item.get("event"),
             "at": item.get("at"), "entry_hash": item.get("entry_hash")}
            for item in audit_entries
        ],
        "audit_chain_problems": verify_audit_chain(repo, task.get("case_id")),
    }
    manifest["manifest_hash"] = digest(
        {key: value for key, value in manifest.items() if key != "manifest_hash"})
    return manifest
