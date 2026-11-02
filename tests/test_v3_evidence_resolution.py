"""Synthetic controlled files; exact-scope reuse lives in one evaluation only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from lexaegis import formal_release, release_service
from lexaegis.util import digest
import tests.test_v3_auto_request_policy as auto
from tests.test_v3_auto_request_policy import ready


def policy(f,repo):
    task=repo.get(f['task']['id'],'task');case=repo.get(task['case_id'],'case')
    if not repo.list('formal_release_policy'):
        candidate=release_service.auto_request_policy_candidate(repo,task,case,f['context'])
        formal_release.install_policy(repo,candidate,actor='synthetic-admin',actor_role='admin')
    return task,case


def evaluate(f,repo):
    task,case=policy(f,repo)
    return release_service.evaluate(repo,task,case,f['context'])


@pytest.fixture
def standby_seed(monkeypatch):
    original=auto._seed_business_state
    def seed(repo,manifest):
        task,case,pack,primary=original(repo,manifest)
        standby={'id':'synthetic-standby','status':'reviewed','endpoint':'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions','model':'qwen-test'}
        repo.put('provider',standby)
        deps=task['request']['dependencies']
        deps.update(standby_provider_id=standby['id'],standby_provider_hash=digest(standby),standby_model=standby['model'])
        deps['dual_slot']['standby']={'target':standby['endpoint'],'model':standby['model'],'provider_id':standby['id'],'role':'standby'}
        task.update(request_hash=digest(task['request']),review_request_hash=digest(task['request']))
        repo.put('task',task,case['id'])
        return task,case,pack,primary
    monkeypatch.setattr(auto,'_seed_business_state',seed)


@pytest.fixture
def dual_ready(standby_seed,ready):
    f=ready
    with f['store'].read() as repo:
        task=repo.get(f['task']['id'],'task');case=repo.get(task['case_id'],'case')
        frozen=formal_release.freeze_request(repo,task=task,case=case,build_manifest=f['context']['build_manifest'],runtime_identities=f['context']['runtime_identities'])
    versions={'materials':digest(frozen.material_versions),'rules':digest(frozen.rule_versions),
              'task':str(frozen.task_version),'mapping':str(frozen.mapping_version),
              'ledger':str(frozen.ledger_version),'combination':frozen.combination_input_hash}
    scope={**f['scope'],'recipient':'synthetic-standby'}
    evidence=f['intake'].evidence_store
    rows=[];files=[]
    stamp=datetime.now(timezone.utc)
    for template in ('法03','法04'):
        raw=('unique synthetic standby '+template).encode()
        artifact=evidence.register_artifact(content=raw,media_type='application/pdf',source_path_hint='synthetic/standby.pdf',actor='synthetic-intake',template_kind=template)
        row=f['intake'].record_gate_receipt({'gate_id':'G3','tuple':scope,'template_kind':template,
            'template_version':'synthetic-v1','template_artifact_id':artifact.id,
            'bound_versions':versions,'conclusion':'pass','confirmed_by':'synthetic-legal',
            'confirmed_role':'legal_reviewer','confirmed_at':(stamp-timedelta(seconds=5)).isoformat(),
            'valid_from':(stamp-timedelta(minutes=1)).isoformat(),'valid_until':(stamp+timedelta(minutes=20)).isoformat(),
            'evidence_artifact_ids':[artifact.id]},actor='synthetic-intake')
        rows.append(row.id);files.append((evidence._path_for_ref(artifact.storage_ref),raw))
    f['standby_receipts']=rows;f['standby_files']=files
    return f


def test_one_resolve_per_exact_group_and_no_global_cache(ready,monkeypatch):
    f=ready;calls=[];reads=[]
    original=f['intake'].resolve_evidence
    read=f['intake'].evidence_store.read_artifact
    def resolve(*args,**kwargs):
        calls.append(deepcopy((args,kwargs)))
        return original(*args,**kwargs)
    def read_artifact(ident):
        reads.append(ident);return read(ident)
    monkeypatch.setattr(f['intake'],'resolve_evidence',resolve)
    monkeypatch.setattr(f['intake'].evidence_store,'read_artifact',read_artifact)
    with f['store'].transaction() as repo:
        _,first=evaluate(f,repo)
        assert first.approval_eligible
        print('RESOLUTION_METRICS='+json.dumps({'resolver_calls':len(calls),'artifact_reads':len(reads)}))
        assert len(calls)==2
        assert len(reads)==14
        _,second=evaluate(f,repo)
        assert second.approval_eligible and len(calls)==4 and len(reads)==28


@pytest.mark.parametrize('mutation',['tampered','missing'])
def test_standby_metadata_does_not_substitute_for_actual_bytes(dual_ready,mutation):
    f=dual_ready
    path,original=f['standby_files'][0]
    if mutation=='tampered': path.write_bytes(b'synthetic altered artifact')
    else: path.unlink()
    with f['store'].transaction() as repo:
        _,decision=evaluate(f,repo)
        assert not decision.approval_eligible
        assert any(hit.reason_code=='standby_legal_reviews_missing' for hit in decision.hits)
        assert repo.list('one_time_dispatch_grant')==[]


def test_standby_valid_scope_is_resolved_separately(dual_ready,monkeypatch):
    f=dual_ready;scopes=[]
    original=f['intake'].resolve_evidence
    def resolve(scope,**kwargs):
        scopes.append(deepcopy(scope));return original(scope,**kwargs)
    monkeypatch.setattr(f['intake'],'resolve_evidence',resolve)
    with f['store'].transaction() as repo:
        _,decision=evaluate(f,repo)
        assert decision.approval_eligible
        snapshot=next(row for row in repo.list('gate_snapshot') if row['snapshot_hash']==decision.snapshot_hash)
        assert set(f['standby_receipts'])<=set(snapshot['validated_receipt_ids'])
    assert [scope['recipient'] for scope in scopes].count('synthetic-standby')==1
    assert len(scopes)==3


def test_artifact_tampering_between_evaluations_never_reuses_old_result(dual_ready):
    f=dual_ready
    with f['store'].transaction() as repo:
        _,first=evaluate(f,repo);assert first.approval_eligible
    path,original=f['standby_files'][0];path.write_bytes(b'synthetic changed after previous evaluation')
    with f['store'].transaction() as repo:
        _,changed=evaluate(f,repo);assert not changed.approval_eligible
    path.write_bytes(original)
    with f['store'].transaction() as repo:
        _,restored=evaluate(f,repo);assert restored.approval_eligible


@pytest.mark.parametrize('mutation',['revoked','expired','wrong_scope','wrong_versions','action_removed','manifest_changed'])
def test_grant_rechecks_standby_legal_evidence_after_evaluation(dual_ready,mutation):
    f=dual_ready
    with f['store'].transaction() as repo:
        frozen,decision=evaluate(f,repo)
        assert decision.approval_eligible
        row=repo.get(f['standby_receipts'][1],'gate_evidence_receipt')
        if mutation=='revoked': row['revoked_at']=datetime.now(timezone.utc).isoformat()
        elif mutation=='expired': row['valid_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        elif mutation=='wrong_scope': row['tuple']['recipient']='unapproved-recipient'
        elif mutation=='wrong_versions': row['bound_versions']['task']='999'
        elif mutation=='manifest_changed': row['evidence_manifest_hash']='0'*64
        else:
            action=next(item for item in repo.list('evidence_role_action') if item['receipt_id']==row['id'])
            repo.delete(action['id'])
        repo.put('gate_evidence_receipt',row)
        approval={'actor':'审批人甲','actor_role':'approver','request_hash':frozen.request_hash,
                  'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        with pytest.raises(formal_release.FormalReleaseError,match='standby legal evidence'):
            formal_release.issue_grant(repo,frozen=frozen,decision=decision,actor='审批人甲',actor_role='approver',approval=approval)
        assert repo.list('one_time_dispatch_grant')==[]


def test_valid_standby_can_receive_a_request_scoped_grant(dual_ready):
    f=dual_ready
    with f['store'].transaction() as repo:
        frozen,decision=evaluate(f,repo)
        approval={'actor':'审批人甲','actor_role':'approver','request_hash':frozen.request_hash,
                  'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        grant=formal_release.issue_grant(repo,frozen=frozen,decision=decision,actor='审批人甲',actor_role='approver',approval=approval)
        assert grant.state=='issued' and grant.gate_snapshot_hash==decision.snapshot_hash


def test_failed_resolution_group_is_fail_closed_and_not_retried_in_same_evaluation(ready,monkeypatch):
    f=ready;calls=[]
    original=f['intake'].resolve_evidence
    def resolve(scope,**kwargs):
        calls.append(kwargs['request_hash'])
        if kwargs['request_hash'] is None: raise ValueError('synthetic intake failure')
        return original(scope,**kwargs)
    monkeypatch.setattr(f['intake'],'resolve_evidence',resolve)
    with f['store'].transaction() as repo:
        _,decision=evaluate(f,repo)
        assert not decision.approval_eligible and calls.count(None)==1
        assert len(calls)==2
        assert repo.list('one_time_dispatch_grant')==[]
