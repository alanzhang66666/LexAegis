import pytest
from pydantic import ValidationError

from lexaegis.contracts import (
    CitationMapping,
    EvidenceArtifact,
    FormalReleasePolicy,
    FormalReleaseState,
    FrozenFormalRequest,
    GateDecision,
    GateEvidenceReceipt,
    GateHit,
    IsolationReceipt,
    LegalSourceRecord,
    OneTimeDispatchGrant,
    ReleaseBuildManifest,
)


RELEASE_TUPLE = {
    "case_id": "LA-001",
    "purpose": "R_fact_summary",
    "recipient": "D_DeepSeek_official_API",
}


def test_legal_source_and_citation_contracts_default_to_unresolved_states():
    source = LegalSourceRecord(
        id="source-1",
        canonical_title="测试法源",
        provision_hash="sha256:provision",
        provision_text_ref="content:provision",
        source_assets=[{"asset_id": "asset-1", "content_hash": "sha256:asset"}],
    )
    mapping = CitationMapping(
        id="mapping-1",
        instrument="律师法",
        from_article="38",
        to_article="41",
        effective_from="2026-09-01",
        basis_artifact_hash="sha256:basis",
    )

    assert source.citation_status == "unknown"
    assert source.rule_nature == "unknown"
    assert source.granularity == "unknown"
    assert mapping.mapping_basis == "unknown"
    assert mapping.status == "pending"
    assert source.source_assets[0].asset_id == "asset-1"


def test_evidence_and_build_contracts_do_not_imply_review_or_verification():
    artifact = EvidenceArtifact(
        id="artifact-1",
        content_hash="sha256:artifact",
        media_type="application/pdf",
        created_at="2026-09-14T00:00:00Z",
        registered_by="actor-1",
        storage_ref="content:artifact",
    )
    receipt = GateEvidenceReceipt(id="receipt-1", gate_id="G1", tuple=RELEASE_TUPLE)
    manifest = ReleaseBuildManifest(
        id="build-1",
        created_at="2026-09-14T00:00:00Z",
    )

    assert artifact.content_hash == "sha256:artifact"
    assert receipt.conclusion == "unknown"
    assert receipt.evidence_artifact_ids == []
    assert manifest.status == "pending"
    assert manifest.worktree_clean is False


@pytest.mark.parametrize(
    "gate_id",
    ["G0", "G1", "G2", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G-product"],
)
def test_gate_ids_are_limited_to_the_existing_outbound_gate_table(gate_id):
    receipt = GateEvidenceReceipt(id=f"receipt-{gate_id}", gate_id=gate_id, tuple=RELEASE_TUPLE)
    assert receipt.gate_id == gate_id


@pytest.mark.parametrize("gate_id", ["G4", "G11", "product", ""])
def test_unknown_gate_ids_are_rejected(gate_id):
    with pytest.raises(ValidationError):
        GateEvidenceReceipt(id="receipt-invalid", gate_id=gate_id, tuple=RELEASE_TUPLE)
    with pytest.raises(ValidationError):
        GateHit(gate_id=gate_id)


@pytest.mark.parametrize(
    "wildcard_scope",
    [
        {**RELEASE_TUPLE, "case_id": "*"},
        {**RELEASE_TUPLE, "purpose": "*"},
        {**RELEASE_TUPLE, "recipient": "*"},
    ],
)
def test_first_release_policy_rejects_wildcard_scope(wildcard_scope):
    with pytest.raises(ValidationError):
        FormalReleasePolicy(id="policy-wildcard", tuple=wildcard_scope)


def test_policy_and_gate_decision_default_to_blocked_without_implicit_pass():
    policy = FormalReleasePolicy(id="policy-1", tuple=RELEASE_TUPLE)
    decision = GateDecision(hits=[GateHit(gate_id="G-product")])

    assert policy.status == "blocked"
    assert policy.consumed_dispatches == 0
    assert decision.phase == "unknown"
    assert decision.disposition == "unknown"
    assert decision.system_readiness == "blocked"
    assert decision.approval_eligible is False
    assert decision.dispatch_allowed is False
    assert decision.hits[0].status == "unknown"
    assert decision.hits[0].kind == "unknown"


def test_frozen_request_contract_captures_required_hash_dependencies():
    request = FrozenFormalRequest(
        request_id="request-1",
        tuple=RELEASE_TUPLE,
        wire_payload={"contract_version": 2, "facts": []},
        prompt="summarize",
        target="https://provider.invalid/v1/chat/completions",
        model="model-1",
        provider_profile_hash="sha256:provider",
        runtime_pack_hash="sha256:pack",
        material_versions={"material-1": 1},
        rule_versions={"rule-1": "sha256:rule"},
        task_version=1,
        mapping_version=1,
        ledger_version=0,
        combination_input_hash="sha256:combination",
        attack_protocol_hashes={"identity": "sha256:attack"},
        build_manifest_hash="sha256:build",
        request_hash="sha256:request",
        created_at="2026-09-14T00:00:00Z",
    )

    assert request.request_hash == "sha256:request"
    assert request.ledger_version == 0


def test_isolation_receipt_defaults_to_pending_and_cannot_claim_global_verification():
    receipt = IsolationReceipt(id="isolation-1")

    assert receipt.deployment_mode == "unknown"
    assert receipt.status == "pending_legal_confirmation"
    assert receipt.api_no_egress is False
    assert receipt.worker_no_egress is False
    assert receipt.gateway_no_case_volume is False
    assert receipt.redteam_no_secrets is False
    assert receipt.benchmark_no_secrets is False


def test_one_time_grant_defaults_to_pending_and_unnamed_role():
    grant = OneTimeDispatchGrant(
        id="grant-1",
        nonce="nonce-1",
        request_hash="sha256:request",
        gate_snapshot_hash="sha256:snapshot",
        evidence_manifest_hash="sha256:evidence",
        build_manifest_hash="sha256:build",
        release_policy_id="policy-1",
        tuple=RELEASE_TUPLE,
    )

    assert grant.actor_role == "unknown"
    assert grant.state == "pending"
    assert grant.issued_at is None
    assert grant.expires_at is None


def test_formal_release_state_has_fail_closed_initial_states_and_no_pass_member():
    assert FormalReleaseState.BLOCKED.value == "blocked"
    assert FormalReleaseState.EVIDENCE_PENDING.value == "evidence_pending"
    assert "pass" not in {state.value for state in FormalReleaseState}
