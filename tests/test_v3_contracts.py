"""PR-01: versioned contracts are untrusted descriptions, not permissions."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lexaegis.contracts import DomainRuntimeSnapshot, FormalReleasePolicy
from lexaegis.contracts_v3 import (
    ChainDecisionV3, ContextSnapshotV3, ExecutionPlanV3, FactAssertionV3,
    OutboundCapabilityV3, PrivacyAssessmentV3, PrivacyReleaseReceiptV3,
    ReleaseScopeV3, TransferIntentV3, WireReceiptV3, freeze_execution_plan,
    create_v3_context_snapshot, legacy_policy_to_scope, snapshot_fingerprint, v2_snapshot_to_v3,
)
from lexaegis.util import canonical, digest

H = lambda ch: ch * 64


def snapshot():
    return ContextSnapshotV3(task_id='task_1', case_ref=H('a'), domain_pack_hash=H('b'),
        legal_rule_hash=H('c'), privacy_policy_hash=H('d'), classifier_hash=H('e'),
        minimization_profile_hash=H('5'), capability_binding_hash=H('6'), provider_policy_hash=H('f'), recipient_ref=H('1'), material_versions_hash=H('2'),
        mapping_version_hash=H('3'), disclosure_ledger_hash=H('4'), attack_input_hash=H('5'))


def assessment(ctx=None, **updates):
    base = dict(assessment_id='assessment_1', task_id='task_1',
        source_context_hash=snapshot_fingerprint(ctx or snapshot()), sensitivity_class='S1',
        disclosure_grade='L1', classifier_version_hash=H('e'), ruleset_hash=H('d'),
        uncertainty='review_required', signal_ids=('signal_1',))
    return PrivacyAssessmentV3(**(base | updates))


def intent(**updates):
    data = dict(transfer_id='transfer_1', task_id='task_1', chain='B',
        recipient_ref=H('1'), recipient_policy_hash=H('f'), purpose_ref=H('2'),
        legal_rule_hash=H('c'), request_hash=H('3'), approved_wire_bytes_hash=H('4'))
    return TransferIntentV3(**(data | updates))


def plan(**updates):
    data = dict(plan_id='plan_1', task_id='task_1', route='MINIMIZED_TEXT_B',
        assessment_hash=assessment().fingerprint(), minimization_profile_hash=H('5'),
        capability_binding_hash=H('6'), transfer_ids=('transfer_1',))
    return ExecutionPlanV3(**(data | updates))


@pytest.mark.parametrize('value', [snapshot(), assessment(), intent(), plan(),
    OutboundCapabilityV3(),
    ChainDecisionV3(decision_id='decision_1', transfer_id='transfer_1', chain='B',
        payload_hash=H('4'), context_hash=H('7'), status='pending'),
    PrivacyReleaseReceiptV3(release_id='release_1', payload_hash=H('8')),
    WireReceiptV3(transfer_id='transfer_1', chain='B', request_hash=H('3'),
        wire_bytes_hash=H('4'), state='unknown'),
    FactAssertionV3(assertion_id='assertion_1', fact_ref=H('1'), source_refs=(H('2'),), content_hash=H('3')),
])
def test_round_trip_and_reject_unknown_or_private_fields(value):
    cls = type(value)
    assert cls.model_validate_json(value.model_dump_json()) == value
    for key in ('raw_text', 'mapping', 'anchors', 'local_text', 'unexpected'):
        with pytest.raises(ValidationError):
            cls.model_validate(value.model_dump(mode='json') | {key: 'sensitive-marker'})
    assert 'sensitive-marker' not in value.model_dump_json()


def test_v2_canonical_fixture_is_unchanged():
    fixture = json.loads((Path(__file__).parent / 'fixtures/v2_request_golden.json').read_text(encoding='utf-8'))
    assert canonical(fixture['request']) == fixture['canonical']
    assert hashlib.sha256(fixture['canonical'].encode('utf-8')).hexdigest() == fixture['sha256']
    assert digest(fixture['request']) == fixture['sha256']


def test_snapshot_fingerprint_changes_for_every_binding():
    original = snapshot()
    for key in ('domain_pack_hash', 'legal_rule_hash', 'privacy_policy_hash', 'classifier_hash',
                'provider_policy_hash', 'recipient_ref', 'case_ref', 'minimization_profile_hash',
                'capability_binding_hash', 'material_versions_hash',
                'mapping_version_hash', 'disclosure_ledger_hash', 'attack_input_hash'):
        changed = original.model_copy(update={key: H('9')})
        assert snapshot_fingerprint(changed) != snapshot_fingerprint(original)
    assert snapshot_fingerprint(original) == snapshot_fingerprint(ContextSnapshotV3.model_validate_json(original.model_dump_json()))


def test_plan_is_bound_and_never_an_authorization():
    frozen = freeze_execution_plan(snapshot(), assessment(), plan(), (intent(),))
    assert frozen.plan.approval_granted is False
    assert len(frozen.fingerprint()) == 64
    assert frozen.fingerprint() != freeze_execution_plan(snapshot(), assessment(), plan(), (intent(request_hash=H('9')),)).fingerprint()
    with pytest.raises(ValueError):
        freeze_execution_plan(snapshot().model_copy(update={'recipient_ref': H('9')}), assessment(), plan(), (intent(),))
    with pytest.raises(ValueError):
        freeze_execution_plan(snapshot(), assessment(), plan(), (intent(chain='A'),))
    with pytest.raises(ValidationError):
        plan(approval_granted=True)


@pytest.mark.parametrize('grade', ['L4', 'UNKNOWN'])
def test_hard_risk_never_generates_cloud_candidate(grade):
    a = assessment(disclosure_grade=grade)
    p = plan(assessment_hash=a.fingerprint())
    with pytest.raises(ValueError):
        freeze_execution_plan(snapshot(), a, p, (intent(),))


def test_dp_route_is_experiment_only():
    with pytest.raises(ValidationError):
        plan(route='DP_VECTOR_EXPERIMENT', experiment_only=False, transfer_ids=())
    p = plan(route='DP_VECTOR_EXPERIMENT', experiment_only=True, transfer_ids=())
    assert freeze_execution_plan(snapshot(), assessment(), p, ()).plan.experiment_only


def test_legacy_request_scope_maps_but_does_not_grant():
    legacy = FormalReleasePolicy(id='policy_1', scope_kind='request', bound_request_hash=H('3'),
        tuple={'case_id':'case_1', 'purpose':'summary', 'recipient':'provider_1'},
        allowed_target='https://example.invalid/v1', allowed_model='fixture-model',
        allowed_provider_profile_hash=H('f'))
    scope = legacy_policy_to_scope(legacy, task_id='task_1', request_hash=H('3'))
    assert isinstance(scope, ReleaseScopeV3)
    assert scope.chain == 'B' and scope.request_hash == H('3')
    assert scope.authorization is False
    assert 'case_1' not in scope.model_dump_json()
    with pytest.raises(ValueError):
        legacy_policy_to_scope(legacy, task_id='task_1', request_hash=H('9'))


def test_reject_noncanonical_hash_and_unrecognized_version():
    with pytest.raises(ValidationError): snapshot().model_validate(snapshot().model_dump() | {'case_ref':'a' * 63})
    with pytest.raises(ValidationError): snapshot().model_validate(snapshot().model_dump() | {'contract_version':2})


def test_unverified_claims_are_not_accepted_as_complete():
    with pytest.raises(ValidationError):
        OutboundCapabilityV3(state='available')
    with pytest.raises(ValidationError):
        OutboundCapabilityV3(state='available', attestation_refs=(H('1'), H('1'), H('2')))
    candidate = OutboundCapabilityV3(state='available', attestation_refs=(H('1'), H('2'), H('3')))
    assert candidate.verified is False
    with pytest.raises(ValidationError):
        candidate.model_validate(candidate.model_dump() | {'verified': True})
    with pytest.raises(ValidationError):
        ChainDecisionV3(decision_id='d1', transfer_id='t1', chain='B', payload_hash=H('1'),
                        context_hash=H('2'), status='approved')
    with pytest.raises(ValidationError):
        WireReceiptV3(transfer_id='t1', chain='B', request_hash=H('1'),
                      wire_bytes_hash=H('2'), state='complete')
    with pytest.raises(ValidationError):
        FactAssertionV3(assertion_id='a1', fact_ref=H('1'), source_refs=(), content_hash=H('2'))


@pytest.mark.parametrize('risk_change', [
    {'sensitivity_class':'UNKNOWN'}, {'uncertainty':'unknown'}, {'hard_prohibitions':('prohibition_1',)}
])
def test_unknown_or_prohibited_risk_cannot_produce_cloud_candidate(risk_change):
    a = assessment(**risk_change)
    with pytest.raises(ValueError):
        freeze_execution_plan(snapshot(), a, plan(assessment_hash=a.fingerprint()), (intent(),))


def test_frozen_models_revalidate_tampered_nested_inputs():
    bad_plan = plan().model_copy(update={'approval_granted': True})
    with pytest.raises(ValidationError):
        freeze_execution_plan(snapshot(), assessment(), bad_plan, (intent(),))
    with pytest.raises(ValidationError):
        snapshot().task_id = 'different'  # type: ignore[misc]


def test_legacy_pilot_scope_remains_request_specific_and_does_not_modify_policy():
    policy = FormalReleasePolicy(id='pilot_1', tuple={'case_id':'LA-001','purpose':'R_fact_summary',
        'recipient':'D_DeepSeek_official_API'}, allowed_target='https://example.invalid/v1',
        allowed_model='fixture-model', allowed_provider_profile_hash=H('f'))
    before = policy.model_dump_json()
    a = legacy_policy_to_scope(policy, task_id='task_1', request_hash=H('1'))
    b = legacy_policy_to_scope(policy, task_id='task_1', request_hash=H('2'))
    assert a.fingerprint() != b.fingerprint()
    assert policy.model_dump_json() == before and a.authorization is False
    invalid = policy.model_copy(update={'tuple': {'case_id':'wrong','purpose':'R_fact_summary',
                                                  'recipient':'D_DeepSeek_official_API'}})
    with pytest.raises(ValidationError):
        legacy_policy_to_scope(invalid, task_id='task_1', request_hash=H('1'))


def test_formal_v2_request_golden_matches_real_existing_fixture(tmp_path):
    from lexaegis.storage import Store
    from tests.test_formal_release_flow import _task
    fixture = json.loads((Path(__file__).parent / 'fixtures/v2_formal_request_golden.json').read_text(encoding='utf-8'))
    store = Store(tmp_path / 'v2-golden.sqlite')
    try:
        with store.transaction() as repo:
            task, _case = _task(repo)
            assert task['request'] == fixture['request']
            assert canonical(task['request']) == fixture['canonical']
            assert task['request_hash'] == fixture['sha256']
    finally:
        store.engine.dispose()


def test_existing_v2_snapshot_adapter_preserves_full_legacy_identity():
    v2 = DomainRuntimeSnapshot(id='v2_1', cause_pack_hash=H('1'), legal_rule_pack_hash=H('2'),
        review_schema_hash=H('3'), artifact_schema_hash=H('4'), minimization_profile_hash=H('5'),
        gate_profile_hash=H('6'), platform_api_version='2', created_at='2026-11-01T00:00:00Z')
    original = v2.model_dump_json()
    options = dict(task_id='task_1', case_ref=H('a'), classifier_hash=H('b'),
                   privacy_policy_hash=H('c'), capability_binding_hash=H('8'), provider_policy_hash=H('d'), recipient_ref=H('e'),
                   material_versions_hash=H('1'), mapping_version_hash=H('2'),
                   disclosure_ledger_hash=H('3'), attack_input_hash=H('4'))
    derived = v2_snapshot_to_v3(v2, **options)
    assert derived.domain_pack_hash == H('1') and derived.legal_rule_hash == H('2')
    assert derived.domain_pack_kind == 'cause_pack'
    assert v2.model_dump_json() == original
    assert derived.fingerprint() != v2_snapshot_to_v3(v2.model_copy(update={'gate_profile_hash':H('9')}), **options).fingerprint()
    assert derived.fingerprint() != v2_snapshot_to_v3(v2, **(options | {'recipient_ref':H('9')})).fingerprint()
    assert derived.legacy_snapshot_hash is not None


def test_create_context_accepts_references_not_unstructured_case():
    values = snapshot().model_dump(exclude={'contract_version','legacy_snapshot_hash'})
    assert create_v3_context_snapshot(**values) == snapshot()
    with pytest.raises(TypeError):
        create_v3_context_snapshot(**values, case={'original_name':'private'})


def test_literal_safety_fields_reject_integer_booleans_and_float_version():
    for update in ({'verified': 0}, {'verified': 1}, {'contract_version': 3.0}, {'contract_version': True}):
        with pytest.raises(ValidationError):
            OutboundCapabilityV3.model_validate(OutboundCapabilityV3().model_dump() | update)
    with pytest.raises(ValidationError):
        plan(approval_granted=0)
    with pytest.raises(ValidationError):
        plan(experiment_only=0)
