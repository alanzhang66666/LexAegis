import pytest

from lexaegis.review import (
    assert_review_allows, initialize_task_review, list_open_issues,
    record_review, review_state, submit_issue,
)
from lexaegis.storage import Store


def _fixture(tmp_path):
    store = Store(tmp_path / "review.sqlite3")
    with store.transaction() as repo:
        repo.put("case", {"id": "case-1", "revision": 2, "mode": "formal"})
        repo.put("pack", {"id": "pack-1", "legal_sources": [{"id": "law-1"}],
                           "manual_review_conditions": [{"id": "condition-1"}]})
        repo.put("document", {"id": "doc-1", "case_id": "case-1", "version": 2,
                               "ir": {"blocks": [{"id": "block-1"}] }}, "case-1")
        repo.put("fact", {"id": "fact-1", "case_id": "case-1", "source_ids": ["block-1"]}, "case-1")
        task = {"id": "task-1", "case_id": "case-1", "pack_id": "pack-1", "transport": "cloud",
                "status": "ready", "request": {"sent": True}, "request_hash": "sha256:current",
                "case_revision": 2, "approval": {"id": "approval-1"}, "risk": {"approval_allowed": True}}
        initialize_task_review(repo, task)
        repo.put("task", task, "case-1")
    return store


def _legal_body(**overrides):
    body = {
        "request_hash": "sha256:current", "material_version": 2,
        "conclusion": "reject_current_request", "reason": "授权范围不覆盖本次外发",
        "evidence_ids": ["fact-1"], "reviewed_condition_ids": ["condition-1"], "legal_source_ids": ["law-1"],
        "acknowledged_risk_notices": True, "fact_premise": "当前为合成材料",
        "authority_judgment": "本次处理超出授权范围", "external_processing_note": "拟发送至外部服务商",
        "minimization_note": "仍需调整披露内容", "final_basis": "授权材料不含外发权限",
        "scope_note": "仅对当前请求作出结论", "idempotency_key": "legal-1",
    }
    body.update(overrides)
    return body


def test_technical_issue_blocks_and_is_idempotent(tmp_path):
    store = _fixture(tmp_path)
    body = {"request_hash": "sha256:current", "idempotency_key": "tech-1",
            "reason": "岗位和日期组合可能识别主体", "evidence_ids": ["fact-1", "block-1"]}
    actor = {"user_id": "tech-7", "actor_role": "technical_reviewer", "display_name": "技术复核员"}
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        submit_issue(repo, task, body, actor)
        assert task["review_status"] == "blocked"
        assert task["approval"] is None
        assert len(list_open_issues(repo, "case-1")) == 1
        submit_issue(repo, task, body, actor)
        assert len([e for e in repo.list("review_event", "case-1") if e["event_type"] == "technical_issue_submitted"]) == 1
        with pytest.raises(ValueError, match="人工复核"):
            assert_review_allows(repo, task)


def test_legal_rejection_blocks_and_requires_current_pack_references(tmp_path):
    store = _fixture(tmp_path)
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        submit_issue(repo, task, {"request_hash": "sha256:current", "idempotency_key": "tech-1",
                                  "reason": "复核问题", "evidence_ids": ["fact-1"]},
                     {"user_id": "tech-7", "actor_role": "technical_reviewer"})
        with pytest.raises(ValueError, match="当前规则包"):
            record_review(repo, task, _legal_body(legal_source_ids=["unknown-law"]),
                          {"user_id": "law-8", "actor_role": "legal_reviewer"})
        record_review(repo, task, _legal_body(), {"user_id": "law-8", "actor_role": "legal_reviewer", "display_name": "法学复核员"})
        assert task["review_status"] == "rejected"
        assert task["status"] == "rejected"
        assert task["approval"] is None
        assert task["risk"]["approval_allowed"] is True
        state = review_state(repo, task)
        assert state["latest_legal_review"]["reviewer_user_id"] == "law-8"
        assert len(state["events"]) == 2
        record_review(repo, task, _legal_body(), {"user_id": "law-8", "actor_role": "legal_reviewer", "display_name": "法学复核员"})
        assert len([r for r in repo.list("legal_review_record", "case-1") if r["task_id"] == task["id"]]) == 1
        with pytest.raises(ValueError):
            assert_review_allows(repo, task)


def test_unknown_evidence_and_replaying_key_with_changed_body_rejected(tmp_path):
    store = _fixture(tmp_path)
    actor = {"user_id": "tech-7", "actor_role": "technical_reviewer"}
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        with pytest.raises(ValueError, match="证据引用"):
            submit_issue(repo, task, {"request_hash": "sha256:current", "idempotency_key": "tech-1",
                                      "reason": "问题", "evidence_ids": ["not-a-ref"]}, actor)
        first = {"request_hash": "sha256:current", "idempotency_key": "tech-1", "reason": "问题",
                 "evidence_ids": ["fact-1"]}
        submit_issue(repo, task, first, actor)
        changed = {**first, "reason": "不同的问题"}
        with pytest.raises(ValueError, match="幂等键"):
            submit_issue(repo, task, changed, actor)


def test_allowing_followup_requires_and_resolves_open_issue(tmp_path):
    store = _fixture(tmp_path)
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        submit_issue(repo, task, {"request_hash": "sha256:current", "idempotency_key": "tech-1",
                                  "reason": "需要修改披露", "evidence_ids": ["fact-1"]},
                     {"user_id": "tech-7", "actor_role": "technical_reviewer"})
        issue = list_open_issues(repo, "case-1")[0]
        body = _legal_body(conclusion="allow_processing", idempotency_key="legal-1")
        with pytest.raises(ValueError, match="resolved_issue_ids"):
            record_review(repo, task, body, {"user_id": "law-8", "actor_role": "legal_reviewer"})
        body["resolved_issue_ids"] = [issue["id"]]
        body["resolution_reason"] = "补充证据已核对"
        record_review(repo, task, body, {"user_id": "law-8", "actor_role": "legal_reviewer"})
        assert not list_open_issues(repo, "case-1")
        assert task["review_status"] == "cleared"
        assert_review_allows(repo, task)


def test_new_cloud_task_inherits_case_issues(tmp_path):
    store = _fixture(tmp_path)
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        submit_issue(repo, task, {"request_hash": "sha256:current", "idempotency_key": "tech-1",
                                  "reason": "需要审查", "evidence_ids": ["fact-1"]},
                     {"user_id": "tech-7", "actor_role": "technical_reviewer"})
        followup = {"id": "task-2", "case_id": "case-1", "pack_id": "pack-1", "transport": "cloud"}
        initialize_task_review(repo, followup, parent_task_id="task-1")
        assert followup["review_status"] == "blocked"
        assert followup["inherited_review_issue_ids"] == [list_open_issues(repo, "case-1")[0]["id"]]


def test_case_issue_permanently_revokes_existing_sibling_approval(tmp_path):
    store = _fixture(tmp_path)
    with store.transaction() as repo:
        task = repo.get("task-1", "task")
        sibling = {**task, "id": "task-sibling", "status": "queued", "review_status": "cleared",
                   "review_request_hash": task["request_hash"]}
        repo.put("task", sibling, "case-1")
        repo.put("job", {"id": "sibling-job", "kind": "send", "status": "running",
                          "payload": {"task_id": sibling["id"]}}, "case-1")
        submit_issue(repo, task, {"request_hash": task["request_hash"], "idempotency_key": "technical",
                                  "reason": "本案补充线索需要复核", "evidence_ids": ["fact-1"]},
                     {"user_id": "tech", "actor_role": "technical_reviewer"})
        issue = list_open_issues(repo, "case-1")[0]
        record_review(repo, task, _legal_body(conclusion="allow_processing", resolved_issue_ids=[issue["id"]],
                                             resolution_reason="已核验补充线索"),
                      {"user_id": "law", "actor_role": "legal_reviewer"})
        assert not list_open_issues(repo, "case-1")
        sibling = repo.get("task-sibling", "task")
        assert sibling["approval"] is None
        assert repo.get("sibling-job")["status"] == "cancelled"
        with pytest.raises(ValueError, match="人工复核"):
            assert_review_allows(repo, sibling)
