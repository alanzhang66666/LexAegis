"""Optional local case bundle: never commit supplied case materials."""
import json
from pathlib import Path
import pytest
from tests.conftest import login_as, login_admin
from lexaegis.demo import SCENARIOS
from lexaegis import service
from lexaegis.worker import process_one
from lexaegis.runtime_profile import validate_case_creation, dispatch_scope, synthetic_manifest_hash

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'recording_adapted'


@pytest.mark.parametrize('local_admin', [False, True])
def test_three_adapted_workflows(demo_env, local_admin):
    e=demo_env; c=e['client']
    for item in json.loads((ROOT/'manifest.json').read_text()):
        login_admin(e)
        f=ROOT / item['path']
        r=c.post('/api/v1/demos/import', files={'file':(f.name,f.read_bytes())})
        assert r.status_code==200,r.text
        case=r.json(); assert case['scenario']==item['scenario']
        assert 'recording_content_unlocked' not in case
        assert 'recording_stage_content' not in case
        assert 'recording_document_id' not in case
        detail=c.get('/api/v1/cases/'+case['id']).json()
        assert set(detail['stage_content']) == {'facts', 'disclosure', 'risk', 'result'}
        assert all(stage['items'] for stage in detail['stage_content'].values())
        assert not detail['tasks'] and not detail['ledger']
        original=detail['documents'][0]
        assert original['source_role']=='recording_original'
        assert len(original['ir']['blocks']) > 50
        downloaded=c.get(f"/api/v1/cases/{case['id']}/documents/{original['id']}/file")
        assert downloaded.status_code==200
        assert downloaded.content==f.read_bytes()
        original_ids={b['id'] for b in original['ir']['blocks']}
        assert all(original_ids.intersection(fact['source_ids']) for fact in detail['facts'][:-1])
        assert all(fact['origin']=='recording_annotation' for fact in detail['facts'])
        task=c.post(f"/api/v1/cases/{case['id']}/tasks",json={'transport':'mock'}).json()
        r=c.post(f"/api/v1/tasks/{task['id']}/evaluate")
        assert r.status_code==200,r.text
        task=r.json(); url=f"/api/v1/tasks/{task['id']}"
        if item['code']=='LA-001':
            assert task['risk']['approval_allowed'] is False
            login_as(e,'approver')
            assert c.post(url+'/approve',json={'request_hash':task['request_hash']}).status_code==409
            login_as(e,'case_operator')
            assert c.post(url+'/send').status_code==409
            continue
        assert task['risk']['approval_allowed'], task['risk']
        pack=next(x for x in c.get('/api/v1/domains').json() if x['id']==task['pack_id'])
        reject=item['code']=='LA-002'
        body={
            'request_hash':task['request_hash'],'material_version':case['revision'],
            'idempotency_key':'adapted-'+task['id'],
            'conclusion':'reject_current_request' if reject else 'allow_processing',
            'reason':'精确补贴与参保组合非必要且起算日期冲突未解决。' if reject else '本次摘要只保留角色、管理行为、证据及给付类别。',
            'evidence_ids':['la002_date_conflict'] if reject else [task['fact_snapshot'][0]['id']],
            'reviewed_condition_ids':[pack['manual_review_conditions'][0]['id']],
            'legal_source_ids':[pack['legal_sources'][0]['id']],
            'acknowledged_risk_notices':True,'scope_note':'仅当前请求，本地模拟。',
            'fact_premise':'依据所提供案例登记的摘要申请事实。','authority_judgment':'不授权真实外发。',
            'external_processing_note':'仅离线mock。','minimization_note':'原文保留本地，只审查候选摘要。',
            'final_basis':'结合当前事实与处理目的逐请求审阅。'}
        review_url = url
        if local_admin:
            login_admin(e)
            assert c.post(url+'/legal-review',json=body).status_code == 403
            assert c.post(url+'/approve',json={'request_hash':task['request_hash']}).status_code == 403
            review_url = '/api/v1/demos/tasks/' + task['id']
        else:
            login_as(e,'legal_reviewer')
        r=c.post(review_url+'/legal-review',json=body)
        assert r.status_code==200,r.text
        if not local_admin:
            login_as(e,'approver')
        r=c.post(review_url+'/approve',json={'request_hash':task['request_hash']})
        assert r.status_code==(409 if reject else 200),r.text
        login_as(e,'case_operator');r=c.post(url+'/send')
        assert r.status_code==(409 if reject else 200),r.text
        if not reject:
            assert process_one(e['app'].state.store,e['root'],e['gate'])
            detail=c.get('/api/v1/cases/'+case['id']).json()
            assert detail['tasks'][0]['status']=='complete',detail['tasks'][0]


@pytest.mark.parametrize('fixture_name', ['env', 'integration_env'])
def test_local_review_cannot_be_used_in_other_profiles(request, fixture_name):
    fixture = request.getfixturevalue(fixture_name)
    response = fixture['client'].post('/api/v1/demos/tasks/any-task/approve',
                                       json={'request_hash': 'not-a-request'})
    assert response.status_code == 403


def test_stage_content_requires_a_matching_upload(demo_env):
    items = json.loads((ROOT / 'manifest.json').read_text())
    selected = items[0]
    with demo_env['app'].state.store.transaction() as repo:
        case = service.create_case(repo, SCENARIOS[selected['scenario']]['name'],
                                   scenario=selected['scenario'])
    assert 'recording_content_unlocked' not in case
    assert 'recording_stage_content' not in case
    assert demo_env['client'].get('/api/v1/cases/' + case['id']).json()['stage_content'] == {}

    before = len(demo_env['client'].get('/api/v1/bootstrap').json()['cases'])
    path = ROOT / selected['path']
    response = demo_env['client'].post(
        '/api/v1/demos/import',
        data={'expected_scenario': items[1]['scenario']},
        files={'file': (path.name, path.read_bytes())},
    )
    assert response.status_code == 409
    assert '不匹配' in response.text
    after = len(demo_env['client'].get('/api/v1/bootstrap').json()['cases'])
    assert after == before

    response = demo_env['client'].post(
        '/api/v1/demos/import',
        data={'expected_scenario': selected['scenario']},
        files={'file': (path.name, path.read_bytes())},
    )
    assert response.status_code == 200, response.text
    imported = response.json()
    assert 'recording_content_unlocked' not in imported
    detail = demo_env['client'].get('/api/v1/cases/' + imported['id']).json()
    assert set(detail['stage_content']) == {'facts', 'disclosure', 'risk', 'result'}
    for public in [detail['case'], *demo_env['client'].get('/api/v1/bootstrap').json()['cases']]:
        assert not {'recording_content_unlocked', 'recording_document_id', 'recording_stage_content'} & public.keys()
    # The server checks the bound original, independently of the frontend.
    with demo_env['app'].state.store.transaction() as repo:
        stored = repo.get(imported['id'], 'case')
        original = repo.get(stored['recording_document_id'], 'document')
        original['status'] = 'failed'
        repo.put('document', original, imported['id'])
    assert demo_env['client'].get('/api/v1/cases/' + imported['id']).json()['stage_content'] == {}


def test_every_local_material_tool_uses_each_case_original(demo_env):
    client = demo_env['client']
    expected = {
        'LA-001': {'timeline': '2021年6月8日', 'evidence_inventory': '柜台分摊费', 'issue_extraction': '用工主体与期间'},
        'LA-002': {'timeline': '2015年9月25日', 'evidence_inventory': '社会保险补贴', 'issue_extraction': '关系起算日差异'},
        'LA-003': {'timeline': '2024年7月14日', 'evidence_inventory': '平台收入账单', 'issue_extraction': '站点经营主体'},
    }
    artifact_keys = {'timeline': 'events', 'evidence_inventory': 'items', 'issue_extraction': 'issues'}
    for item in json.loads((ROOT / 'manifest.json').read_text()):
        login_admin(demo_env)
        path = ROOT / item['path']
        case = client.post('/api/v1/demos/import', files={'file': (path.name, path.read_bytes())}).json()
        detail = client.get('/api/v1/cases/' + case['id']).json()
        original = detail['documents'][0]
        original_ids = {block['id'] for block in original['ir']['blocks']}
        for task_type, artifact_key in artifact_keys.items():
            response = client.post(f"/api/v1/cases/{case['id']}/tasks",
                                   json={'transport': 'local', 'task_type': task_type})
            assert response.status_code == 200, response.text
            task = response.json()
            rows = task['artifact'][artifact_key]
            assert rows
            assert expected[item['code']][task_type] in json.dumps(rows, ensure_ascii=False)
            assert all(row['source_ids'] for row in rows)
            assert all(set(row['source_ids']) <= original_ids for row in rows)
            exported = client.get(f"/api/v1/tasks/{task['id']}/export")
            assert exported.status_code == 200
            assert expected[item['code']][task_type] in exported.text


def test_adapted_cases_cannot_enter_integration(integration_env):
    for scenario in ('la001_edge_block','la002_human_veto','la003_review_release'):
        assert SCENARIOS[scenario]['offline_only']
        with pytest.raises(ValueError,match='offline'):
            validate_case_creation(scenario)
        with pytest.raises(ValueError,match='synthetic manifest'):
            dispatch_scope({'mode':'demo','transport':'cloud','dependencies':{
                'runtime_profile':'integration','data_origin':'bundled_synthetic',
                'synthetic_manifest_hash':synthetic_manifest_hash(scenario)}})


def test_import_recognizes_resaved_and_original_body(demo_env):
    import io
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    from lexaegis.recording_import import identify_recording
    ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    def repack(data, original_only=False, change=False):
        output=io.BytesIO()
        with ZipFile(io.BytesIO(data)) as source, ZipFile(output,'w') as dest:
            for member in source.infolist():
                payload=source.read(member.filename)
                if member.filename=='word/document.xml':
                    root=ET.fromstring(payload)
                    if original_only:
                        body=root.find(ns+'body')
                        for node in list(body):
                            text=''.join(t.text or '' for t in node.iter(ns+'t'))
                            body.remove(node)
                            if text=='原始案件文书及标注': break
                    if change:
                        next(root.iter(ns+'t')).text='更改后的案件正文'
                    payload=ET.tostring(root,encoding='utf-8',xml_declaration=True)
                dest.writestr(member,payload)
            dest.comment=b'resaved by word processor'
        return output.getvalue()
    for item in json.loads((ROOT/'manifest.json').read_text()):
        data=(ROOT / item['path']).read_bytes()
        for original in (False,True):
            saved=repack(data,original_only=original)
            assert saved!=data
            result=demo_env['client'].post('/api/v1/demos/import',files={'file':('重新保存.docx',saved)})
            assert result.status_code==200,result.text
            assert result.json()['scenario']==item['scenario']
        assert identify_recording(repack(data,change=True)) is None
    assert identify_recording(b'not a Word document') is None
