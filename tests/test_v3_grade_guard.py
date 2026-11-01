"""Real service guard tests; evidence and accounts below are synthetic fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from lexaegis import domain_packages, service, v3_grade_guard
from lexaegis.util import sign
from lexaegis.worker import process_one
from tests.conftest import login_as
from tests.test_v3_auto_request_policy import ready, approve


KEY = 'synthetic-package-signing-key-for-test-only'


@pytest.fixture
def graded(ready, monkeypatch):
    monkeypatch.setenv('LEX_PACKAGE_SIGNING_KEY', KEY)
    f = ready
    stamp = datetime.now(timezone.utc)
    with f['store'].transaction() as repo:
        task = repo.get(f['task']['id'], 'task')
        case = repo.get(task['case_id'], 'case')
        task['risk']['disposition'] = 'allowed'
        profile = {'id':'synthetic-profile','package_type':'gate_profile','package_id':'synthetic_gate',
            'cause_id':'labor','version':'1','platform_api':None,'compatibility':{},'jurisdiction':'CN',
            'effective_from':(stamp-timedelta(days=1)).isoformat(),
            'effective_to':(stamp+timedelta(days=1)).isoformat(),
            'content':{'v3_grade_policy':{'version':1,'permitted_grades':['L0','L1','L2','L3','L4','UNKNOWN']}},
            'status':'published'}
        profile['content_hash'] = domain_packages._package_content_hash(profile)
        profile['signature'] = sign(domain_packages._signable_payload(profile), KEY)
        repo.put('domain_package', profile)
        snapshot = {'id':'synthetic-snapshot','gate_profile_hash':profile['content_hash'], 'pack_id':task['pack_id']}
        repo.put('domain_runtime_snapshot', snapshot)
        task['domain_runtime_snapshot_id'] = snapshot['id']
        repo.put('task', task, case['id'])
        repo.put('user', {'id':'user:legal','role':'legal_reviewer','status':'active'})
        legal = {'id':'synthetic-review','task_id':task['id'],'case_id':case['id'],
            'request_hash':task['request_hash'],'material_version':case['revision'],
            'conclusion':'allow_processing','reviewer_role':'legal_reviewer','reviewer_user_id':'user:legal',
            'legal_source_ids':['synthetic-law'],'reviewed_condition_ids':['synthetic-condition'],
            'evidence_ids':['synthetic-evidence']}
        repo.put('legal_review_record', legal, case['id'])
    f['profile_id'] = profile['id']; f['legal_review_id'] = legal['id']
    f['actor'] = {'user_id':'user:legal','actor_role':'legal_reviewer'}
    return f


def record(f, repo, grade='L1', actor=None):
    task=repo.get(f['task']['id'],'task'); case=repo.get(task['case_id'],'case')
    return v3_grade_guard.record(repo,task,case,grade=grade,profile_id=f['profile_id'],
        legal_review_id=f['legal_review_id'],actor=actor or f['actor'])


def test_flag_requires_grade_and_rolls_back_provisional_policy(graded, monkeypatch):
    monkeypatch.setenv('LEX_V3_GRADE_GUARD','1')
    with graded['store'].transaction() as repo:
        with pytest.raises(ValueError,match='等级评估缺失'):
            approve(graded,repo)
        assert repo.list('formal_release_policy') == []
        assert repo.list('one_time_dispatch_grant') == []
        assert repo.get(graded['task']['id'],'task')['status'] == 'review'


def test_l1_record_then_full_legacy_gate_grant_and_local_gateway(graded):
    f=graded
    with f['store'].transaction() as repo:
        item=record(f,repo)
        assert item['grade']=='L1' and record(f,repo)['id']==item['id']
        task=approve(f,repo)
        assert task['status']=='approved' and task['formal_release']['grant']['state']=='issued'
        service.reserve_send(repo,task['id'],release_context=f['context'])
    with TestClient(f['gateway']) as gateway:
        assert process_one(f['store'],f['root'],gateway)
    assert f['provider'].calls==1


@pytest.mark.parametrize('grade',['L0','L3','L4','UNKNOWN'])
def test_unsupported_and_prohibited_levels_fail_closed(graded, grade):
    with graded['store'].transaction() as repo:
        record(graded,repo,grade)
        with pytest.raises(ValueError):
            approve(graded,repo)
        assert repo.list('formal_release_policy') == []
        assert repo.list('one_time_dispatch_grant') == []


@pytest.mark.parametrize('mutation',['profile_revoked','profile_tampered','profile_expired','snapshot_changed','review_changed','account_disabled','account_reset','assessment_expired','assessment_tampered','request_changed','risk_worsened'])
def test_changes_after_approval_block_enqueue(graded, mutation):
    f=graded
    with f['store'].transaction() as repo:
        record(f,repo,'L2'); task=approve(f,repo)
        if mutation.startswith('profile_'):
            p=repo.get(f['profile_id'],'domain_package')
            if mutation=='profile_revoked': p['status']='revoked'
            elif mutation=='profile_tampered': p['content']['v3_grade_policy']['version']=2
            else: p['effective_to']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            repo.put('domain_package',p)
        elif mutation=='snapshot_changed':
            s=repo.get('synthetic-snapshot','domain_runtime_snapshot');s['pack_id']='other';repo.put('domain_runtime_snapshot',s)
        elif mutation=='review_changed':
            r=repo.get(f['legal_review_id'],'legal_review_record');r['legal_source_ids']=['other'];repo.put('legal_review_record',r)
        elif mutation in {'account_disabled','account_reset'}:
            u=repo.get('user:legal','user')
            if mutation=='account_disabled': u['status']='disabled'
            else: u['auth_version']=2
            repo.put('user',u)
        elif mutation in {'assessment_expired','assessment_tampered'}:
            a=repo.get(task['v3_grade_assessment_id'],'v3_grade_assessment')
            if mutation=='assessment_expired':
                a['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
                content={k:v for k,v in a.items() if k!='signature'}
                a['signature']=sign({'domain':'lexaegis.v3.grade.v1','content':content},KEY)
            else: a['grade']='L1'
            repo.put('v3_grade_assessment',a)
        else:
            task=repo.get(task['id'],'task')
            if mutation=='request_changed': task['request']['body']['model']='changed'
            else: task['risk']['disposition']='prohibited'
            repo.put('task',task,task['case_id'])
        with pytest.raises(ValueError):
            service.reserve_send(repo,task['id'],release_context=f['context'])
        assert not repo.list('disclosure',task['case_id'])
        assert f['provider'].calls==0


def test_cannot_downgrade_deterministic_risk_or_replace_frozen_grade(graded):
    f=graded
    with f['store'].transaction() as repo:
        task=repo.get(f['task']['id'],'task'); task['risk']['disposition']='needs_verification'; repo.put('task',task,task['case_id'])
        with pytest.raises(ValueError,match='不允许降低'): record(f,repo,'L1')
        task['risk']['disposition']='allowed'; repo.put('task',task,task['case_id'])
        record(f,repo,'L2')
        with pytest.raises(ValueError,match='已冻结'): record(f,repo,'L1')


def test_only_current_named_legal_reviewer_may_record(graded):
    f=graded
    with f['store'].transaction() as repo:
        for actor in ({'user_id':'user:legal','actor_role':'admin'}, {'user_id':'user:other','actor_role':'legal_reviewer'}):
            with pytest.raises(ValueError): record(f,repo,actor=actor)
        assert repo.list('v3_grade_assessment')==[]


def test_grade_endpoint_requires_exact_legal_role(env):
    client=env['client']
    payload={'request_hash':'a'*64,'grade':'L1','profile_id':'synthetic','legal_review_id':'synthetic'}
    assert client.post('/api/v1/tasks/missing/v3-grade-assessment',json=payload).status_code==403
    login_as(env,'case_operator')
    assert client.post('/api/v1/tasks/missing/v3-grade-assessment',json=payload).status_code==403
    login_as(env,'legal_reviewer')
    assert client.post('/api/v1/tasks/missing/v3-grade-assessment',json=payload).status_code==404


def test_revocation_after_queue_stops_worker_without_provider_call(graded):
    f=graded
    with f['store'].transaction() as repo:
        record(f,repo,'L1'); task=approve(f,repo)
        service.reserve_send(repo,task['id'],release_context=f['context'])
        p=repo.get(f['profile_id'],'domain_package'); p['status']='revoked'; repo.put('domain_package',p)
    with TestClient(f['gateway']) as gateway:
        assert process_one(f['store'],f['root'],gateway)
    assert f['provider'].calls==0
    with f['store'].read() as repo:
        task=repo.get(f['task']['id'],'task')
        grant=repo.get(task['formal_release']['grant']['id'],'one_time_dispatch_grant')
        assert grant['state']=='revoked'


def test_new_request_requires_new_review_and_keeps_old_assessment(graded):
    from lexaegis.util import digest
    f=graded
    with f['store'].transaction() as repo:
        first=record(f,repo,'L1')
        task=repo.get(f['task']['id'],'task')
        task['request']['body']['model']='new-model'
        task['request_hash']=digest(task['request'])
        repo.put('task',task,task['case_id'])
        with pytest.raises(ValueError):
            record(f,repo,'L2')
        review=repo.get(f['legal_review_id'],'legal_review_record')
        review.update(id='synthetic-new-review',request_hash=task['request_hash'])
        repo.put('legal_review_record',review,task['case_id'])
        f['legal_review_id']=review['id']
        second=record(f,repo,'L2')
        assert second['id']!=first['id'] and second['request_hash']!=first['request_hash']
        assert repo.get(first['id'],'v3_grade_assessment')==first


def test_malformed_signed_grade_policy_fails_closed(graded):
    f=graded
    with f['store'].transaction() as repo:
        p=repo.get(f['profile_id'],'domain_package')
        p['content']['v3_grade_policy']['permitted_grades']=[['L1']]
        p['content_hash']=domain_packages._package_content_hash(p)
        p['signature']=sign(domain_packages._signable_payload(p),KEY)
        repo.put('domain_package',p)
        s=repo.get('synthetic-snapshot','domain_runtime_snapshot');s['gate_profile_hash']=p['content_hash'];repo.put('domain_runtime_snapshot',s)
        with pytest.raises(ValueError,match='配置缺失或无效'): record(f,repo)
        assert repo.list('v3_grade_assessment')==[]


def test_authenticated_legal_api_records_once_and_rejects_spoofed_role(env, monkeypatch):
    from lexaegis.util import digest
    monkeypatch.setenv('LEX_PACKAGE_SIGNING_KEY',KEY)
    client=env['client']; login_as(env,'legal_reviewer')
    stamp=datetime.now(timezone.utc)
    request={'task_id':'api-task','case_id':'api-case','mode':'formal','transport':'cloud','body':{'model':'synthetic'}}
    request_hash=digest(request)
    with env['app'].state.store.transaction() as repo:
        settings=repo.get('settings')
        case={'id':'api-case','revision':1}
        repo.put('case',case)
        profile={'id':'api-profile','package_type':'gate_profile','package_id':'api_gate','cause_id':'labor',
            'version':'1','platform_api':None,'compatibility':{},'jurisdiction':'CN','status':'published',
            'effective_from':(stamp-timedelta(days=1)).isoformat(),'effective_to':(stamp+timedelta(days=1)).isoformat(),
            'content':{'v3_grade_policy':{'version':1,'permitted_grades':['L1','L2']}}}
        profile['content_hash']=domain_packages._package_content_hash(profile)
        profile['signature']=sign(domain_packages._signable_payload(profile),KEY)
        repo.put('domain_package',profile)
        repo.put('domain_runtime_snapshot',{'id':'api-snapshot','gate_profile_hash':profile['content_hash'],'pack_id':'api-pack'})
        task={'id':'api-task','case_id':'api-case','case_revision':1,'settings_version':settings['version'],
            'stale':False,'status':'review','pack_id':'api-pack','domain_runtime_snapshot_id':'api-snapshot',
            'transport':'cloud','request':request,'request_hash':request_hash,'review_status':'cleared',
            'risk':{'disposition':'allowed'},'legal_review':{'id':'api-review'}}
        repo.put('task',task,case['id'])
        repo.put('legal_review_record',{'id':'api-review','case_id':'api-case','task_id':'api-task',
            'request_hash':request_hash,'material_version':1,'conclusion':'allow_processing',
            'reviewer_role':'legal_reviewer','reviewer_user_id':'user:legal.reviewer',
            'legal_source_ids':['synthetic-law'],'reviewed_condition_ids':['synthetic-condition'],
            'evidence_ids':['synthetic-evidence']},case['id'])
    payload={'request_hash':request_hash,'grade':'L1','profile_id':'api-profile','legal_review_id':'api-review'}
    path='/api/v1/tasks/api-task/v3-grade-assessment'
    response=client.post(path,json={'request_hash':request_hash,'grade':'L1'})
    assert response.status_code==200, response.text
    assert response.json()['reviewer_user_id']=='user:legal.reviewer'
    assert 'signature' not in response.json()
    assert client.post(path,json=payload).json()['id']==response.json()['id']
    assert client.post(path,json={**payload,'grade':'L2'}).status_code==409
    assert client.post(path,json={**payload,'actor':'another-user'}).status_code==422
    with env['app'].state.store.read() as repo:
        assert len(repo.list('v3_grade_assessment','api-case'))==1


def test_status_blocks_auto_approval_when_v3_grade_missing(graded, monkeypatch):
    from lexaegis import release_service
    monkeypatch.setenv('LEX_V3_GRADE_GUARD','1')
    with graded['store'].transaction() as repo:
        task=repo.get(graded['task']['id'],'task');case=repo.get(task['case_id'],'case')
        result=release_service.status(repo,task,case,graded['context'])
        assert result['state']=='blocked'
        assert result['auto_policy_candidate'] is False
        assert result['v3_grade_guard']['state']=='blocked'
        assert '等级评估缺失' in result['reason']
        record(graded,repo,'L1')
        task=repo.get(task['id'],'task')
        result=release_service.status(repo,task,case,graded['context'])
        assert result['v3_grade_guard']['state']=='satisfied'
        assert result['v3_grade_guard']['grade']=='L1'
        assert result['state']=='blocked'  # original gates still decide approval


def test_status_blocks_stale_grade_even_when_legacy_gate_was_ready(graded):
    from lexaegis import release_service
    with graded['store'].transaction() as repo:
        record(graded,repo,'L1');task=approve(graded,repo);case=repo.get(task['case_id'],'case')
        p=repo.get(graded['profile_id'],'domain_package');p['status']='revoked';repo.put('domain_package',p)
        result=release_service.status(repo,task,case,graded['context'])
        assert result['state']=='blocked' and result['auto_policy_candidate'] is False
        assert result['v3_grade_guard']['state']=='blocked'


@pytest.mark.parametrize('flag',['true','yes','2'])
def test_invalid_feature_flag_fails_closed(graded, monkeypatch, flag):
    from lexaegis import release_service
    monkeypatch.setenv('LEX_V3_GRADE_GUARD',flag)
    with graded['store'].transaction() as repo:
        task=repo.get(graded['task']['id'],'task');case=repo.get(task['case_id'],'case')
        status=release_service.status(repo,task,case,graded['context'])
        assert status['state']=='blocked' and status['auto_policy_candidate'] is False
        with pytest.raises(ValueError,match='只能为 0 或 1'): approve(graded,repo)
        assert repo.list('formal_release_policy')==[]


def test_concurrent_identical_assessments_are_idempotent(graded):
    from concurrent.futures import ThreadPoolExecutor
    def run(_):
        with graded['store'].transaction() as repo:
            return record(graded,repo,'L1')['id']
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids=list(executor.map(run,range(4)))
    assert len(set(ids))==1
    with graded['store'].read() as repo:
        assert len(repo.list('v3_grade_assessment'))==1


def test_task_view_rechecks_grade_and_hides_stale_armed_state(graded):
    f=graded
    with f['store'].transaction() as repo:
        record(f,repo,'L1');task=approve(f,repo)
        p=repo.get(f['profile_id'],'domain_package');p['status']='revoked';repo.put('domain_package',p)
        view=service.task_view(repo,repo.get(task['id'],'task'))
        assert view['product_release']['state']=='blocked'
        assert view['product_release']['v3_grade_guard']['state']=='blocked'
        assert view['product_release']['auto_policy_candidate'] is False


@pytest.mark.parametrize('key',['','short'])
def test_missing_or_short_signing_key_fails_closed(graded, monkeypatch, key):
    monkeypatch.setenv('LEX_PACKAGE_SIGNING_KEY',key)
    with graded['store'].transaction() as repo:
        with pytest.raises(ValueError): record(graded,repo,'L1')
        assert repo.list('v3_grade_assessment')==[]


def test_key_rotation_invalidates_existing_assessment(graded, monkeypatch):
    with graded['store'].transaction() as repo:
        record(graded,repo,'L1')
        monkeypatch.setenv('LEX_PACKAGE_SIGNING_KEY','new-synthetic-key-at-least-thirty-two-bytes')
        with pytest.raises(ValueError,match='签名无效'): approve(graded,repo)
        assert repo.list('formal_release_policy')==[]
