from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from lexaegis.auth import create_user_record
from lexaegis.contracts import GateEvidenceReceipt, GateReceiptInput
from lexaegis.evidence import (
    EvidenceIntakeService,
    EvidenceReceiptError,
    EvidenceStore,
)
from lexaegis.storage import Store
from lexaegis.util import now


TUPLE = {
    "case_id": "LA-001",
    "purpose": "R_fact_summary",
    "recipient": "D_DeepSeek_official_API",
}
NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
VALID_FROM = (NOW - timedelta(minutes=5)).isoformat()
VALID_UNTIL = (NOW + timedelta(minutes=30)).isoformat()
CONFIRMED_AT = (NOW - timedelta(minutes=1)).isoformat()


def make_intake(tmp_path):
    store = Store(tmp_path / "business.sqlite")
    evidence_store = EvidenceStore(store, tmp_path / "controlled-evidence")
    return store, evidence_store, EvidenceIntakeService(evidence_store)


def register(evidence_store, template_kind, label):
    return evidence_store.register_artifact(
        content=f"completed synthetic {label}".encode(),
        media_type="application/pdf",
        source_path_hint=f"intake/{label}.pdf",
        actor="intake-operator",
        template_kind=template_kind,
    )


def signed_input(gate_id, template_kind, template_artifact, **overrides):
    values = {
        "gate_id": gate_id,
        "tuple": TUPLE,
        "template_kind": template_kind,
        "template_version": "2026-09-15",
        "template_artifact_id": template_artifact.id,
        "bound_versions": {"material": "v1"},
        "request_hash": "request-hash-1" if gate_id in {"G6", "G7", "G8", "G9", "G10"} else None,
        "conclusion": "pass",
        "evidence_artifact_ids": [template_artifact.id],
        "confirmed_by": "reviewer-001",
        "confirmed_role": "legal_reviewer",
        "confirmed_at": CONFIRMED_AT,
        "valid_from": VALID_FROM,
        "valid_until": VALID_UNTIL,
    }
    values.update(overrides)
    return GateReceiptInput(**values)


def test_maps_completed_fa01_to_named_version_bound_g1_receipt(tmp_path):
    store, evidence_store, intake = make_intake(tmp_path)
    signed_form = register(evidence_store, "法01_门1_来源核验与人工审查", "fa01-signed")

    receipt = intake.record_gate_receipt(
        signed_input("G1", "法01", signed_form, adopted_fact_ids=["fact-1", "fact-3"]),
        actor="intake-operator",
        at=NOW,
    )

    assert receipt.gate_id == "G1"
    assert receipt.tuple == TUPLE
    assert receipt.template_kind == "法01"
    assert receipt.template_version == "2026-09-15"
    assert receipt.bound_versions == {"material": "v1"}
    assert receipt.adopted_fact_ids == ["fact-1", "fact-3"]
    assert receipt.request_hash is None
    assert receipt.evidence_manifest_hash
    assert intake.receipt_passes(receipt, at=NOW)
    with store.read() as repo:
        stored = repo.get(receipt.id, "gate_evidence_receipt")
        audit_record = next(
            item for item in repo.list("audit")
            if item["event"] == "gate_evidence.receipt_recorded"
        )
    assert stored == receipt.model_dump(mode="json")
    assert "completed synthetic" not in str(audit_record)


def test_g2_requires_exact_statement_and_matching_organization_authorization(tmp_path):
    _, evidence_store, intake = make_intake(tmp_path)
    signed_form = register(evidence_store, "法02", "fa02-signed")
    organization_authorization = register(evidence_store, None, "organization-authorization")
    statement = "本次 LA-001、R_fact_summary 子目的、D_DeepSeek_official_API 接收方可用。"
    evidence_ids = [signed_form.id, organization_authorization.id]

    receipt = intake.record_gate_receipt(
        signed_input(
            "G2",
            "法02",
            signed_form,
            evidence_artifact_ids=evidence_ids,
            authorization_statement=statement,
            organization_authorization_artifact_id=organization_authorization.id,
        ),
        actor="intake-operator",
        at=NOW,
    )
    assert receipt.authorization_statement == statement
    assert receipt.organization_authorization_artifact_id == organization_authorization.id

    with pytest.raises(EvidenceReceiptError, match="exact 本次可用"):
        intake.record_gate_receipt(
            signed_input(
                "G2",
                "法02",
                signed_form,
                evidence_artifact_ids=evidence_ids,
                authorization_statement="门禁全过后允许",
                organization_authorization_artifact_id=organization_authorization.id,
            ),
            actor="intake-operator",
            at=NOW,
        )


@pytest.mark.parametrize(
    ("gate_id", "legal_template", "technical_template"),
    [("G7", "法08", "技04"), ("G8", "法09", "技05"), ("G9", "法10", "技06")],
)
def test_legal_confirmations_bind_same_request_and_technical_evidence_hash(
    tmp_path, gate_id, legal_template, technical_template
):
    _, evidence_store, intake = make_intake(tmp_path)
    signed_form = register(evidence_store, legal_template, f"{legal_template}-signed")
    technical_report = register(evidence_store, technical_template, f"{technical_template}-report")

    receipt = intake.record_gate_receipt(
        signed_input(
            gate_id,
            legal_template,
            signed_form,
            evidence_artifact_ids=[signed_form.id, technical_report.id],
            technical_evidence_artifact_id=technical_report.id,
            technical_evidence_hash=technical_report.content_hash,
            technical_evidence_request_hash="request-hash-1",
        ),
        actor="intake-operator",
        at=NOW,
    )
    assert receipt.request_hash == "request-hash-1"
    assert receipt.technical_evidence_hash == technical_report.content_hash

    with pytest.raises(EvidenceReceiptError, match="same request_hash"):
        intake.record_gate_receipt(
            signed_input(
                gate_id,
                legal_template,
                signed_form,
                evidence_artifact_ids=[signed_form.id, technical_report.id],
                technical_evidence_artifact_id=technical_report.id,
                technical_evidence_hash=technical_report.content_hash,
                technical_evidence_request_hash="changed-request-hash",
            ),
            actor="intake-operator",
            at=NOW,
        )


def test_version_and_request_bound_gate_families_fail_closed(tmp_path):
    _, evidence_store, intake = make_intake(tmp_path)
    fa03 = register(evidence_store, "法03", "fa03-signed")
    fa07 = register(evidence_store, "法07", "fa07-signed")

    with pytest.raises(EvidenceReceiptError, match="template version"):
        intake.record_gate_receipt(
            signed_input("G3", "法03", fa03, template_version=None, bound_versions={}),
            actor="intake-operator",
            at=NOW,
        )
    with pytest.raises(EvidenceReceiptError, match="request_hash"):
        intake.record_gate_receipt(
            signed_input("G6", "法07", fa07, request_hash=None),
            actor="intake-operator",
            at=NOW,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"evidence_artifact_ids": [], "template_artifact_id": None}, "nonempty evidence"),
        ({"confirmed_by": ""}, "named signer"),
        ({"confirmed_role": ""}, "named signer"),
        ({"confirmed_at": None}, "named signer"),
        ({"valid_until": (NOW - timedelta(seconds=1)).isoformat()}, "expired"),
        ({"revoked_at": CONFIRMED_AT}, "revoked"),
    ],
)
def test_empty_signature_empty_evidence_expired_or_revoked_cannot_pass(
    tmp_path, overrides, message
):
    _, evidence_store, intake = make_intake(tmp_path)
    signed_form = register(evidence_store, "法01", "fa01-signed")
    receipt_input = signed_input(
        "G1", "法01", signed_form, adopted_fact_ids=["fact-1"], **overrides
    )

    with pytest.raises(EvidenceReceiptError, match=message):
        intake.record_gate_receipt(receipt_input, actor="intake-operator", at=NOW)


def test_unknown_and_pending_receipts_are_recorded_but_never_resolve_as_pass(tmp_path):
    _, evidence_store, intake = make_intake(tmp_path)
    blank_form = register(evidence_store, "法01", "fa01-incomplete")

    for conclusion in ("unknown", "pending"):
        receipt = intake.record_gate_receipt(
            signed_input(
                "G1",
                "法01",
                blank_form,
                conclusion=conclusion,
                evidence_artifact_ids=[],
                template_artifact_id=None,
                confirmed_by=None,
                confirmed_role=None,
                confirmed_at=None,
                adopted_fact_ids=[],
            ),
            actor="intake-operator",
            at=NOW,
        )
        assert not intake.receipt_passes(receipt, at=NOW)

    assert intake.resolve_evidence(TUPLE, bound_versions={"material": "v1"}, at=NOW) == []


def test_resolution_requires_current_versions_and_request_hash(tmp_path):
    _, evidence_store, intake = make_intake(tmp_path)
    fa01 = register(evidence_store, "法01", "fa01-signed")
    fa07 = register(evidence_store, "法07", "fa07-signed")
    g1 = intake.record_gate_receipt(
        signed_input("G1", "法01", fa01, adopted_fact_ids=["fact-1"]),
        actor="intake-operator",
        at=NOW,
    )
    g6 = intake.record_gate_receipt(
        signed_input("G6", "法07", fa07), actor="intake-operator", at=NOW
    )

    current = intake.resolve_evidence(
        TUPLE,
        request_hash="request-hash-1",
        bound_versions={"material": "v1"},
        at=NOW,
    )
    assert {receipt.id for receipt in current} == {g1.id, g6.id}

    changed = intake.resolve_evidence(
        TUPLE,
        request_hash="request-hash-2",
        bound_versions={"material": "v2"},
        at=NOW,
    )
    assert changed == []


def test_receipt_pass_state_expires_without_mutating_historical_receipt():
    receipt = GateEvidenceReceipt(
        id="receipt-1",
        gate_id="G1",
        tuple=TUPLE,
        template_kind="法01",
        template_version="v1",
        template_artifact_id="artifact-1",
        bound_versions={"material": "v1"},
        conclusion="pass",
        evidence_artifact_ids=["artifact-1"],
        evidence_manifest_hash="manifest-hash",
        confirmed_by="reviewer-001",
        confirmed_role="legal_reviewer",
        confirmed_at=CONFIRMED_AT,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        adopted_fact_ids=["fact-1"],
    )

    assert EvidenceIntakeService.receipt_passes(receipt, at=NOW)
    assert not EvidenceIntakeService.receipt_passes(
        receipt, at=NOW + timedelta(minutes=31)
    )
    assert receipt.conclusion == "pass"


def legal_confirmation(intake, evidence_store, gate_id, legal_template, technical_template,
                       *, actor, request_hash="request-hash-1"):
    signed_form = register(evidence_store, legal_template, f"{legal_template}-{actor}")
    technical_report = register(evidence_store, technical_template, f"{technical_template}-{actor}")
    return intake.record_gate_receipt(
        signed_input(
            gate_id,
            legal_template,
            signed_form,
            request_hash=request_hash,
            confirmed_by=actor,
            confirmed_role="legal_reviewer",
            evidence_artifact_ids=[signed_form.id, technical_report.id],
            technical_evidence_artifact_id=technical_report.id,
            technical_evidence_hash=technical_report.content_hash,
            technical_evidence_request_hash=request_hash,
        ),
        actor="intake-operator",
        at=NOW,
    )


def engineering_record(intake, evidence_store, *, actor, request_hash="request-hash-1"):
    signed_form = register(evidence_store, "技03", f"ji03-{actor}")
    return intake.record_gate_receipt(
        signed_input(
            "G6",
            "技03",
            signed_form,
            request_hash=request_hash,
            confirmed_by=actor,
            confirmed_role="case_operator",
        ),
        actor="intake-operator",
        at=NOW,
    )


def approver_record(intake, evidence_store, *, actor, request_hash="request-hash-1"):
    signed_form = register(evidence_store, "技08", f"ji08-{actor}")
    return intake.record_gate_receipt(
        signed_input(
            "G10",
            "技08",
            signed_form,
            request_hash=request_hash,
            confirmed_by=actor,
            confirmed_role="approver",
        ),
        actor="intake-operator",
        at=NOW,
    )


def test_legal_engineering_and_approver_actions_keep_separate_role_trails(tmp_path):
    """Validates: Requirements 6.6."""
    store, evidence_store, intake = make_intake(tmp_path)

    legal = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04", actor="counsel-zhang"
    )
    engineering = engineering_record(intake, evidence_store, actor="operator-li")
    approval = approver_record(intake, evidence_store, actor="partner-wang")

    actions = intake.role_actions(request_hash="request-hash-1")
    assert [(action.receipt_id, action.role, action.action) for action in actions] == [
        (legal.id, "legal_reviewer", "legal_confirmation"),
        (engineering.id, "case_operator", "engineering_record"),
        (approval.id, "approver", "g10_approval"),
    ]
    assert {action.actor for action in actions} == {
        "counsel-zhang",
        "operator-li",
        "partner-wang",
    }
    assert all(action.acted_at == CONFIRMED_AT for action in actions)
    assert all(action.recorded_by == "intake-operator" for action in actions)
    assert intake.distinct_actor_count(actions) == 3
    assert intake.role_actions(gate_id="G10") == [
        action for action in actions if action.receipt_id == approval.id
    ]
    assert (legal.confirmed_role, engineering.confirmed_role, approval.confirmed_role) == (
        "legal_reviewer",
        "case_operator",
        "approver",
    )
    with store.read() as repo:
        recorded = [
            item["metadata"]
            for item in repo.list("audit")
            if item["event"] == "gate_evidence.role_action_recorded"
        ]
    assert [item["role"] for item in recorded] == [
        "legal_reviewer",
        "case_operator",
        "approver",
    ]
    assert {item["acted_at"] for item in recorded} == {CONFIRMED_AT}


def test_one_person_in_two_roles_is_one_actor_with_two_role_actions(tmp_path):
    """Validates: Requirements 6.7."""
    _, evidence_store, intake = make_intake(tmp_path)

    legal = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04", actor="counsel-zhang"
    )
    approval = approver_record(intake, evidence_store, actor="counsel-zhang")

    actions = intake.role_actions(request_hash="request-hash-1")
    assert len(actions) == 2
    assert {action.receipt_id for action in actions} == {legal.id, approval.id}
    assert {action.role for action in actions} == {"legal_reviewer", "approver"}
    assert len({action.id for action in actions}) == 2
    assert intake.role_action_summary(actions) == {
        "counsel-zhang": ["approver", "legal_reviewer"]
    }
    assert intake.distinct_actor_count(actions) == 1
    assert intake.role_actions(actor="counsel-zhang", role="approver") == [
        action for action in actions if action.role == "approver"
    ]


@pytest.mark.parametrize(
    ("gate_id", "template_kind", "confirmed_role", "required_role"),
    [
        ("G10", "技08", "legal_reviewer", "approver"),
        ("G7", "法08", "approver", "legal_reviewer"),
        ("G6", "技03", "legal_reviewer", "case_operator"),
    ],
)
def test_named_role_must_match_the_template_family(
    tmp_path, gate_id, template_kind, confirmed_role, required_role
):
    """Validates: Requirements 6.6."""
    _, evidence_store, intake = make_intake(tmp_path)
    signed_form = register(evidence_store, template_kind, f"{template_kind}-signed")

    with pytest.raises(EvidenceReceiptError, match=f"must be confirmed by {required_role}"):
        intake.record_gate_receipt(
            signed_input(
                gate_id,
                template_kind,
                signed_form,
                request_hash="request-hash-1",
                confirmed_role=confirmed_role,
            ),
            actor="intake-operator",
            at=NOW,
        )
    with pytest.raises(EvidenceReceiptError, match="not a named confirmation role"):
        intake.record_gate_receipt(
            signed_input(
                gate_id,
                template_kind,
                signed_form,
                request_hash="request-hash-1",
                confirmed_role="case_owner_says_so",
            ),
            actor="intake-operator",
            at=NOW,
        )


def test_revoked_receipt_cannot_pass_while_history_and_audit_chain_remain(tmp_path):
    """Validates: Requirements 6.6, 13.2."""
    store, evidence_store, intake = make_intake(tmp_path)
    receipt = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04", actor="counsel-zhang"
    )
    assert intake.receipt_passes(receipt, at=NOW)

    with pytest.raises(EvidenceReceiptError, match="must be revoked by legal_reviewer"):
        intake.revoke_evidence(
            receipt.id,
            "engineering cannot retract a legal confirmation",
            actor="operator-li",
            actor_role="case_operator",
            at=NOW,
        )

    revoked = intake.revoke_evidence(
        receipt.id,
        "法08 条款级依据需重新核验",
        actor="counsel-zhang",
        actor_role="legal_reviewer",
        at=NOW,
    )

    assert not intake.receipt_passes(revoked, at=NOW)
    assert intake.resolve_evidence(TUPLE, request_hash="request-hash-1", at=NOW) == []
    assert revoked.conclusion == "pass"
    assert revoked.confirmed_by == receipt.confirmed_by
    assert revoked.confirmed_role == receipt.confirmed_role
    assert revoked.confirmed_at == receipt.confirmed_at
    assert revoked.evidence_manifest_hash == receipt.evidence_manifest_hash
    assert revoked.revoked_at == NOW.isoformat()
    assert revoked.revocation_reason == "法08 条款级依据需重新核验"
    assert intake.get_receipt(receipt.id) == revoked

    with pytest.raises(EvidenceReceiptError, match="already revoked"):
        intake.revoke_evidence(
            receipt.id,
            "duplicate revocation",
            actor="counsel-zhang",
            actor_role="legal_reviewer",
            at=NOW,
        )

    actions = intake.role_actions(receipt_id=receipt.id)
    assert [action.action for action in actions] == [
        "legal_confirmation",
        "evidence_revocation",
    ]
    assert intake.distinct_actor_count(actions) == 1
    with store.read() as repo:
        events = [item["event"] for item in repo.list("audit")]
        revocation = next(
            item["metadata"]
            for item in repo.list("audit")
            if item["event"] == "gate_evidence.receipt_revoked"
        )
    assert events.count("gate_evidence.receipt_recorded") == 1
    assert events.count("gate_evidence.receipt_revoked") == 1
    assert revocation["confirmed_by"] == "counsel-zhang"
    assert revocation["actor_role"] == "legal_reviewer"
    assert "completed synthetic" not in str(revocation)


def test_revocation_invalidates_unclaimed_dependents_without_rewriting_claimed_history(tmp_path):
    """Validates: Requirements 13.2."""
    store, evidence_store, intake = make_intake(tmp_path)
    open_receipt = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04",
        actor="counsel-zhang", request_hash="request-hash-open",
    )
    claimed_receipt = legal_confirmation(
        intake, evidence_store, "G8", "法09", "技05",
        actor="counsel-zhang", request_hash="request-hash-claimed",
    )
    claimed_request = {
        "id": "frozen-claimed",
        "request_id": "request-claimed",
        "request_hash": "request-hash-claimed",
        "state": "claimed",
    }
    claimed_grant = {
        "id": "grant-claimed",
        "request_hash": "request-hash-claimed",
        "state": "claimed",
        "gateway_attempt_id": "attempt-claimed",
    }
    claimed_gateway = {
        "id": "gateway-claimed",
        "request_id": "request-claimed",
        "request_hash": "request-hash-claimed",
        "status": "unknown",
        "disclosure_state": "possible",
    }
    with store.transaction() as repo:
        repo.put("frozen_formal_request", {
            "id": "frozen-open",
            "request_id": "request-open",
            "request_hash": "request-hash-open",
            "state": "frozen",
        })
        repo.put("frozen_formal_request", claimed_request)
        repo.put("gate_snapshot", {
            "id": "snapshot-open",
            "request_hash": "request-hash-open",
            "status": "pass",
            "approval_eligible": True,
            "dispatch_allowed": True,
        })
        repo.put("dispatch_intent", {
            "id": "intent-open",
            "request_hash": "request-hash-open",
            "status": "pending",
        })
        repo.put("one_time_dispatch_grant", {
            "id": "grant-open",
            "request_hash": "request-hash-open",
            "state": "issued",
        })
        repo.put("one_time_dispatch_grant", claimed_grant)
        repo.put("gateway_record", claimed_gateway)

    intake.revoke_evidence(
        open_receipt.id, "证据被撤销", actor="counsel-zhang", actor_role="legal_reviewer", at=NOW
    )
    intake.revoke_evidence(
        claimed_receipt.id, "证据被撤销", actor="counsel-zhang", actor_role="legal_reviewer", at=NOW
    )

    with store.read() as repo:
        frozen_open = repo.get("frozen-open", "frozen_formal_request")
        snapshot_open = repo.get("snapshot-open", "gate_snapshot")
        intent_open = repo.get("intent-open", "dispatch_intent")
        grant_open = repo.get("grant-open", "one_time_dispatch_grant")
        reports = [
            item["metadata"]["dependent_invalidation"]
            for item in repo.list("audit")
            if item["event"] == "gate_evidence.receipt_revoked"
        ]
        assert repo.get("frozen-claimed", "frozen_formal_request") == claimed_request
        assert repo.get("grant-claimed", "one_time_dispatch_grant") == claimed_grant
        assert repo.get("gateway-claimed", "gateway_record") == claimed_gateway
        assert len(repo.list("one_time_dispatch_grant")) == 2

    assert frozen_open["invalidation_status"] == "invalidated"
    assert frozen_open["invalidated_evidence_receipt_id"] == open_receipt.id
    assert snapshot_open["status"] == "invalidated"
    assert snapshot_open["approval_eligible"] is False
    assert snapshot_open["dispatch_allowed"] is False
    assert intent_open["status"] == "cancelled"
    assert grant_open["state"] == "revoked"
    assert grant_open["revoked_at"] == NOW.isoformat()
    assert reports[0]["request_ids"] == ["request-open"]
    assert reports[0]["grant_ids"] == ["grant-open"]
    assert reports[0]["intent_ids"] == ["intent-open"]
    assert reports[0]["snapshot_ids"] == ["snapshot-open"]
    assert reports[1] == {
        "request_ids": [],
        "snapshot_ids": [],
        "intent_ids": [],
        "grant_ids": [],
        "preserved_claimed_request_hashes": ["request-hash-claimed"],
    }
    assert not intake.receipt_passes(intake.get_receipt(claimed_receipt.id), at=NOW)


def test_deactivated_user_keeps_a_stable_historical_audit_identity(tmp_path):
    """Validates: Requirements 14.5."""
    store, evidence_store, intake = make_intake(tmp_path)
    user = create_user_record(
        "counsel.zhang",
        "张律师",
        "legal_reviewer",
        "unit-test-password",
        created_by="admin",
    )
    with store.transaction() as repo:
        repo.put("user", user)
    receipt = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04", actor=user["username"]
    )

    with store.transaction() as repo:
        repo.put("user", {**user, "status": "disabled", "updated_at": now()})

    persisted = intake.get_receipt(receipt.id)
    actions = intake.role_actions(receipt_id=receipt.id)
    with store.read() as repo:
        assert repo.get(user["id"], "user")["status"] == "disabled"
        audit_actors = {
            item["actor"]
            for item in repo.list("audit")
            if item["event"] == "gate_evidence.role_action_recorded"
        }

    assert persisted.confirmed_by == user["username"]
    assert persisted.confirmed_role == "legal_reviewer"
    assert persisted.confirmed_at == CONFIRMED_AT
    assert [action.actor for action in actions] == [user["username"]]
    assert audit_actors == {user["username"]}


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    actor_names=st.lists(
        st.sampled_from(["counsel-zhang", "operator-li", "partner-wang"]),
        min_size=3,
        max_size=3,
    )
)
def test_role_actions_stay_separate_per_role_and_per_natural_person(tmp_path, actor_names):
    """Property 13: 角色与具名确认保持分离.

    **Validates: Requirements 6.6, 6.7**
    """
    _, evidence_store, intake = make_intake(tmp_path / uuid4().hex)
    legal_actor, engineering_actor, approval_actor = actor_names

    legal = legal_confirmation(
        intake, evidence_store, "G7", "法08", "技04", actor=legal_actor
    )
    engineering = engineering_record(intake, evidence_store, actor=engineering_actor)
    approval = approver_record(intake, evidence_store, actor=approval_actor)

    actions = intake.role_actions(request_hash="request-hash-1")
    assert len(actions) == 3
    assert {(action.receipt_id, action.role) for action in actions} == {
        (legal.id, "legal_reviewer"),
        (engineering.id, "case_operator"),
        (approval.id, "approver"),
    }
    summary = intake.role_action_summary(actions)
    assert set(summary) == set(actor_names)
    assert intake.distinct_actor_count(actions) == len(set(actor_names))
    for actor, roles in summary.items():
        expected = {
            role
            for role, name in (
                ("legal_reviewer", legal_actor),
                ("case_operator", engineering_actor),
                ("approver", approval_actor),
            )
            if name == actor
        }
        assert set(roles) == expected
