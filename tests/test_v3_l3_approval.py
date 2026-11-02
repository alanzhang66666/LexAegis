"""Synthetic accounts and requests: L3 role records never authorize dispatch."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from lexaegis import domain_packages, release_service, service, v3_l3_approval
from lexaegis.util import sign
from tests.conftest import login_as
from tests.test_v3_auto_request_policy import ready, approve
from tests.test_v3_grade_guard import KEY, graded, record

PARTNER = {'user_id': 'user:legal', 'actor_role': 'legal_reviewer'}
DPO = {'user_id': 'user:dpo', 'actor_role': 'approver'}


def setup_l3(f, overlap=False):
    with f['store'].transaction() as repo:
        p = repo.get(f['profile_id'], 'domain_package')
        p['content']['v3_grade_policy']['l3_role_holders'] = {
            'legal_partner': [{'user_id': 'user:legal', 'authority_hash': 'a'*64}],
            'data_protection_officer': [{'user_id': 'user:legal' if overlap else 'user:dpo', 'authority_hash': 'b'*64}],
        }
        p['content_hash'] = domain_packages._package_content_hash(p)
        p['signature'] = sign(domain_packages._signable_payload(p), KEY)
        repo.put('domain_package', p)
        snapshot = repo.get('synthetic-snapshot', 'domain_runtime_snapshot')
        snapshot['gate_profile_hash'] = p['content_hash']
        repo.put('domain_runtime_snapshot', snapshot)
        repo.put('user', {'id': 'user:dpo', 'role': 'approver', 'status': 'active'})
        record(f, repo, 'L3')


def objects(f, repo):
    task = repo.get(f['task']['id'], 'task')
    return task, repo.get(task['case_id'], 'case')


def action(f, repo, role, actor):
    task, case = objects(f, repo)
    return v3_l3_approval.record(repo, task, case, organization_role=role, actor=actor)


def test_two_distinct_role_actions_do_not_authorize_send(graded):
    f = graded
    setup_l3(f)
    with f['store'].transaction() as repo:
        task, case = objects(f, repo)
        assert v3_l3_approval.status(repo, task, case)['state'] == 'pending_roles'
        first = action(f, repo, 'legal_partner', PARTNER)
        assert action(f, repo, 'legal_partner', PARTNER)['id'] == first['id']
        assert v3_l3_approval.status(repo, *objects(f, repo))['legal_partner']
        action(f, repo, 'data_protection_officer', DPO)
        result = v3_l3_approval.status(repo, *objects(f, repo))
        assert result['state'] == 'roles_recorded' and result['distinct_accounts']
        assert result['authorized_to_send'] is False
        display = release_service._with_v3_grade_status(repo, *objects(f, repo), {'state': 'ready'})
        assert display['state'] == 'blocked'
        assert display['v3_grade_guard']['l3_roles']['state'] == 'roles_recorded'
        assert '双人角色动作已登记' in display['reason']
        assert 'PIA/CTIA' in display['reason'] and '禁止外发' in display['reason']
        user = repo.get('user:dpo', 'user')
        user['status'] = 'disabled'; repo.put('user', user)
        stale = release_service._with_v3_grade_status(repo, *objects(f, repo), {'state': 'ready'})
        assert stale['state'] == 'blocked'
        assert stale['v3_grade_guard']['l3_roles']['state'] == 'pending_roles'
        assert '双人角色动作已登记' not in stale['reason']
        assert stale['auto_policy_candidate'] is False
        with pytest.raises(ValueError):
            approve(f, repo)
        assert repo.list('formal_release_policy') == []
        assert repo.list('one_time_dispatch_grant') == []
        assert f['provider'].calls == 0


@pytest.mark.parametrize('actor,role', [
    (DPO, 'legal_partner'), (PARTNER, 'data_protection_officer'),
    ({'user_id':'user:other','actor_role':'legal_reviewer'}, 'legal_partner'),
    ({'user_id':'user:legal','actor_role':'admin'}, 'legal_partner'),
])
def test_wrong_or_unassigned_actor_fails(graded, actor, role):
    setup_l3(graded)
    with graded['store'].transaction() as repo:
        with pytest.raises(ValueError): action(graded, repo, role, actor)
        assert repo.list(v3_l3_approval.KIND) == []


def test_overlapping_signed_assignments_rejected(graded):
    setup_l3(graded, overlap=True)
    with graded['store'].transaction() as repo:
        with pytest.raises(ValueError, match='账户须分离'):
            action(graded, repo, 'legal_partner', PARTNER)


@pytest.mark.parametrize('mutation', ['action_tampered', 'account_disabled', 'account_reset', 'account_role_changed'])
def test_role_record_becomes_invalid_after_change(graded, mutation):
    f = graded
    setup_l3(f)
    with f['store'].transaction() as repo:
        row = action(f, repo, 'legal_partner', PARTNER)
        action(f, repo, 'data_protection_officer', DPO)
        if mutation == 'action_tampered':
            row['authority_hash'] = 'c'*64
            repo.put(v3_l3_approval.KIND, row, f['task']['case_id'])
        else:
            user = repo.get('user:legal', 'user')
            if mutation == 'account_disabled': user['status'] = 'disabled'
            elif mutation == 'account_reset': user['auth_version'] = 2
            else: user['role'] = 'approver'
            repo.put('user', user)
        # The grade assessment itself depends on the legal reviewer's account.
        try:
            state = v3_l3_approval.status(repo, *objects(f, repo))
            assert not state['legal_partner'] and not state['authorized_to_send']
        except ValueError:
            pass
        with pytest.raises(ValueError): approve(f, repo)


@pytest.mark.parametrize('mutation', ['profile_revoked', 'profile_tampered', 'request_changed', 'assessment_tampered'])
def test_stale_assessment_or_profile_cannot_record(graded, mutation):
    f = graded
    setup_l3(f)
    with f['store'].transaction() as repo:
        task, case = objects(f, repo)
        if mutation.startswith('profile'):
            p = repo.get(f['profile_id'], 'domain_package')
            if mutation == 'profile_revoked': p['status'] = 'revoked'
            else: p['content']['v3_grade_policy']['version'] = 2
            repo.put('domain_package', p)
        elif mutation == 'request_changed':
            task['request']['body']['model'] = 'changed'
            repo.put('task', task, case['id'])
        else:
            row = repo.get(task['v3_grade_assessment_id'], 'v3_grade_assessment')
            row['grade'] = 'L2'; repo.put('v3_grade_assessment', row)
        with pytest.raises(ValueError): action(f, repo, 'legal_partner', PARTNER)


def test_unconfigured_and_not_review_are_rejected(graded):
    f = graded
    with f['store'].transaction() as repo:
        record(f, repo, 'L3')
        with pytest.raises(ValueError, match='配置缺失'):
            action(f, repo, 'legal_partner', PARTNER)
    # A fresh assessment is needed after profile change.


def test_endpoint_exact_roles_and_no_client_actor(env):
    c = env['client']
    url = '/api/v1/tasks/missing/v3-l3-role-action'
    body = {'request_hash': 'a'*64, 'organization_role': 'legal_partner'}
    assert c.post(url, json=body).status_code == 403
    login_as(env, 'legal_reviewer')
    assert c.post(url, json=body).status_code == 404
    assert c.post(url, json={**body, 'actor_user_id': 'user:legal'}).status_code == 422
    body['organization_role'] = 'data_protection_officer'
    assert c.post(url, json=body).status_code == 403
    login_as(env, 'approver')
    assert c.post(url, json=body).status_code == 404


def test_concurrent_identical_actions_remain_idempotent(graded):
    f = graded
    setup_l3(f)
    def do(_):
        with f['store'].transaction() as repo:
            return action(f, repo, 'legal_partner', PARTNER)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(do, range(2)))
    assert ids[0] == ids[1]
    with f['store'].read() as repo:
        assert len(repo.list(v3_l3_approval.KIND)) == 1


def test_authenticated_api_records_both_without_release(env, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from lexaegis.util import digest
    monkeypatch.setenv('LEX_PACKAGE_SIGNING_KEY', KEY)
    client = env['client']
    login_as(env, 'approver'); login_as(env, 'legal_reviewer')
    stamp = datetime.now(timezone.utc)
    request = {'task_id':'l3-api-task','case_id':'l3-api-case','mode':'formal','transport':'cloud','body':{'model':'synthetic'}}
    request_hash = digest(request)
    with env['app'].state.store.transaction() as repo:
        settings = repo.get('settings'); case = {'id':'l3-api-case','revision':1}; repo.put('case', case)
        p = {'id':'l3-api-profile','package_type':'gate_profile','package_id':'api_gate','cause_id':'labor',
             'version':'1','platform_api':None,'compatibility':{},'jurisdiction':'CN','status':'published',
             'effective_from':(stamp-timedelta(days=1)).isoformat(),'effective_to':(stamp+timedelta(days=1)).isoformat(),
             'content':{'v3_grade_policy':{'version':1,'permitted_grades':['L3'], 'l3_role_holders':{
                 'legal_partner':[{'user_id':'user:legal.reviewer','authority_hash':'a'*64}],
                 'data_protection_officer':[{'user_id':'user:approver.test','authority_hash':'b'*64}]}}}}
        p['content_hash'] = domain_packages._package_content_hash(p); p['signature'] = sign(domain_packages._signable_payload(p),KEY)
        repo.put('domain_package',p)
        repo.put('domain_runtime_snapshot',{'id':'l3-api-snapshot','gate_profile_hash':p['content_hash'],'pack_id':'api-pack'})
        task={'id':'l3-api-task','case_id':case['id'],'case_revision':1,'settings_version':settings['version'],
              'stale':False,'status':'review','pack_id':'api-pack','domain_runtime_snapshot_id':'l3-api-snapshot',
              'transport':'cloud','request':request,'request_hash':request_hash,'review_status':'cleared',
              'risk':{'disposition':'allowed'},'legal_review':{'id':'l3-api-review'}}
        repo.put('task',task,case['id'])
        repo.put('legal_review_record',{'id':'l3-api-review','case_id':case['id'],'task_id':task['id'],
              'request_hash':request_hash,'material_version':1,'conclusion':'allow_processing',
              'reviewer_role':'legal_reviewer','reviewer_user_id':'user:legal.reviewer',
              'legal_source_ids':['synthetic-law'],'reviewed_condition_ids':['synthetic-condition'],
              'evidence_ids':['synthetic-evidence']},case['id'])
    path='/api/v1/tasks/l3-api-task'
    response=client.post(path+'/v3-grade-assessment',json={'request_hash':request_hash,'grade':'L3'})
    assert response.status_code == 200, response.text
    body={'request_hash':request_hash,'organization_role':'legal_partner'}
    response=client.post(path+'/v3-l3-role-action',json=body)
    assert response.status_code == 200, response.text
    assert response.json()['actor_user_id']=='user:legal.reviewer' and 'signature' not in response.json()
    assert client.post(path+'/v3-l3-role-action',json={**body,'organization_role':'data_protection_officer'}).status_code==403
    login_as(env,'approver')
    response=client.post(path+'/v3-l3-role-action',json={**body,'organization_role':'data_protection_officer'})
    assert response.status_code==200, response.text
    assert response.json()['actor_user_id']=='user:approver.test'
    with env['app'].state.store.read() as repo:
        t=repo.get(task['id'],'task'); c=repo.get(case['id'],'case')
        result=v3_l3_approval.status(repo,t,c)
        assert result['state']=='roles_recorded' and result['authorized_to_send'] is False
        assert repo.list('formal_release_policy')==[] and repo.list('one_time_dispatch_grant')==[]
