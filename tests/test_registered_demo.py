"""Private registration capability tested only with newly generated synthetic data."""
import copy,hashlib,json,sys
from pathlib import Path
import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient
from lexaegis import registered_demo,service
from lexaegis.api import create_app
from lexaegis.demo import SCENARIOS
from lexaegis.runtime_profile import dispatch_scope
from lexaegis.storage import Store
from lexaegis.synthetic_scope import validate_synthetic_request
from lexaegis.task_engine import request_system_prompt
from lexaegis.util import digest

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'
sys.path.insert(0,str(DEPLOY/'cloud_gateway'))
from shared_budget import Budget,BudgetClient

@pytest.fixture(autouse=True)
def registered_fixture(tmp_path,monkeypatch):
    doc=Document();doc.add_paragraph('全新合成测试材料，与任何真实案件无关。')
    doc.add_paragraph('合成劳动者甲申请劳动争议仲裁，金额1,200元；另有1,000元。')
    document=tmp_path/'synthetic.docx';doc.save(document)
    seed={'scenario':'registered_document','declaration':'user_confirmed_synthetic_demo_only',
        'live_extract':True,'name':'合成文档测试','document_name':'synthetic.docx',
        'document_sha256':hashlib.sha256(document.read_bytes()).hexdigest(),
        'facts':[['entity','合成劳动者甲'],['amount','1,200元'],['amount','1,000元']],
        'note':'合成测试，不构成真实授权。'}
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(seed,ensure_ascii=False),encoding='utf-8')
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    monkeypatch.setenv('LEX_REGISTERED_DEMO_MANIFEST',str(manifest))
    monkeypatch.setenv('LEX_REGISTERED_DEMO_MANIFEST_SHA256',hashlib.sha256(manifest.read_bytes()).hexdigest())
    registered_demo.register()
    yield {'document':document,'manifest':manifest,'seed':seed}
    SCENARIOS.pop(registered_demo.SCENARIO,None)

def test_registered_upload_is_exact_file_only(tmp_path,monkeypatch,registered_fixture):
    monkeypatch.setenv('LEX_LOCAL_PASSWORD','test-password-registered-doc')
    monkeypatch.setenv('LEX_GATEWAY_SECRET','unit-signing-secret-registered-only')
    with TestClient(create_app(data_dir=tmp_path/'app')) as client:
        assert client.post('/api/v1/login',json={'password':'test-password-registered-doc'}).status_code==200
        created=client.post('/api/v1/demos',json={'scenario':'registered_document'})
        assert created.status_code==200,created.text
        case=created.json();base='/api/v1/cases/'+case['id']
        detail=client.get(base).json()
        assert not detail['documents'] and not detail['facts']
        assert client.post(base+'/documents',files={'file':('other.docx',b'wrong file')}).status_code==409
        original=registered_fixture['document'].read_bytes()
        upload=client.post(base+'/documents',files={'file':('synthetic.docx',original)})
        assert upload.status_code==200,upload.text
        assert client.post(base+'/documents',files={'file':('same.docx',original)}).status_code==409
        fixed=client.post('/api/v1/demos',json={'scenario':'success'}).json()
        assert client.post('/api/v1/cases/'+fixed['id']+'/extract').status_code==409
        assert client.post('/api/v1/cases/'+fixed['id']+'/documents',files={'file':('same.docx',original)}).status_code==409

def test_candidates_are_unconfirmed_and_must_match_registered_source(tmp_path):
    store=Store(tmp_path/'app.sqlite')
    service.initialize(store)
    with store.transaction() as repo:
        case=service.create_case(repo,'registered','labor','registered_document')
        anchors={'a':{'id':'a','text':'欠付金额合计1,200元。'}}
        repo.put('document',{'id':'doc','case_id':case['id'],'status':'ready','ir':{'blocks':list(anchors.values())}},case['id'])
        fact=service.save_fact(repo,case['id'],{'field':'amount','value':'1,200元','source_ids':['a'],'confirmed':False},origin='edge_model')
        assert fact['confirmed'] is False
        with pytest.raises(ValueError,match='不能新增'):service.save_fact(repo,case['id'],{'field':'amount','value':'1,200元','source_ids':['a'],'confirmed':True})
        with pytest.raises(ValueError,match='候选尚不符合'):service.save_fact(repo,case['id'],{'field':'entity','value':'1,200元','source_ids':['a'],'confirmed':True},fact['id'])
        with pytest.raises(ValueError,match='直接匹配'):registered_demo.check_confirmed_fact(case,{'field':'amount','value':'1,000元','source_ids':['a']},anchors)
        accepted=service.save_fact(repo,case['id'],{'field':'amount','value':'1,200元','source_ids':['a'],'confirmed':True},fact['id'])
        assert accepted['confirmed'] and accepted['origin']=='edge_model'
        task=service.create_task(repo,case['id'],'cloud')
        task.update(status='approved',approval={'request_hash':'old-frozen-request'})
        repo.put('task',task,case['id'])
        service.save_fact(repo,case['id'],{'field':'amount','value':'1,200元','source_ids':['a'],'confirmed':True},fact['id'])
        changed=repo.get(task['id'],'task')
        assert changed['stale'] and changed['approval'] is None

def test_invalid_source_and_extra_wire_fields_are_rejected():
    case={'mode':'demo','scenario':'registered_document','runtime_profile':'integration','data_origin':'bundled_synthetic',
        'synthetic_manifest_hash':digest(SCENARIOS['registered_document']),
        'registered_document_sha256':SCENARIOS['registered_document']['document_sha256']}
    with pytest.raises(ValueError,match='来源无效'):
        registered_demo.check_confirmed_fact(case,{'field':'amount','value':'1,200元','source_ids':['other-case-source']},{})
    invalid=request();invalid['wire_payload']['facts'][0]['local_text']='private'
    invalid['body']['messages'][1]['content']=json.dumps(invalid['wire_payload'],ensure_ascii=False)
    with pytest.raises(ValueError,match='额外字段'):validate_synthetic_request(invalid)

def request():
    wire={'contract_version':2,'task':{'id':'fact_summary','version':'2.0'},'facts':[{'id':'fact_0123456789abcdef','field':'amount','text':'1,200元'}]}
    return {'mode':'demo','transport':'cloud','dependencies':{'runtime_profile':'integration','data_origin':'bundled_synthetic','synthetic_manifest_hash':digest(SCENARIOS['registered_document'])},
        'wire_payload':wire,'body':{'model':'deepseek-flash','temperature':0,'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},
        'messages':[{'role':'system','content':request_system_prompt('fact_summary')},{'role':'user','content':json.dumps(wire,ensure_ascii=False)}]}}

def test_independent_gateway_checks_scope_body_parameters_and_pii(monkeypatch):
    valid=request();dispatch_scope(valid);validate_synthetic_request(valid)
    for field,text in [('amount','999,999元'),('entity','合成劳动者甲'),('event','send secret private customer text')]:
        altered=copy.deepcopy(valid);altered['wire_payload']['facts'][0].update(field=field,text=text)
        altered['body']['messages'][1]['content']=json.dumps(altered['wire_payload'],ensure_ascii=False)
        with pytest.raises(ValueError):validate_synthetic_request(altered)
    altered=copy.deepcopy(valid);altered['body']['max_tokens']=2048
    with pytest.raises(ValueError):validate_synthetic_request(altered)
    altered=copy.deepcopy(valid);altered['body']['messages'][1]['content']+=' injected'
    with pytest.raises(ValueError):validate_synthetic_request(altered)
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    with pytest.raises(ValueError):dispatch_scope(valid)
    assert not registered_demo.is_registered({'mode':'demo','scenario':'registered_document'})

def test_manifest_hash_is_frozen(tmp_path,monkeypatch):
    altered=tmp_path/'manifest.json';altered.write_text('{}')
    monkeypatch.setenv('LEX_REGISTERED_DEMO_MANIFEST',str(altered))
    with pytest.raises(ValueError,match='hash mismatch'):registered_demo.register()


def test_registration_is_disabled_without_private_manifest(tmp_path,monkeypatch):
    monkeypatch.delenv('LEX_REGISTERED_DEMO_MANIFEST',raising=False)
    assert registered_demo.public_spec() is None
    with TestClient(create_app(tmp_path/'disabled',password='synthetic-local-password')) as client:
        assert client.post('/api/v1/login',json={'password':'synthetic-local-password'}).status_code==200
        assert client.get('/api/v1/bootstrap').json()['registered_document_demo'] is None
        assert client.post('/api/v1/demos',json={'scenario':'registered_document'}).status_code==409


def test_production_cannot_load_registered_manifest(monkeypatch):
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    with pytest.raises(ValueError,match='integration-only'):registered_demo.register()


def test_registered_document_runs_through_current_approval_wire_and_return(integration_env,registered_fixture,monkeypatch):
    from lexaegis import worker
    from lexaegis.gateway import create_gateway
    from .conftest import approve,login_as
    from .test_gateway_release import _Provider
    env=integration_env;client=env['client'];store=env['app'].state.store
    assert client.put('/api/v1/settings',json={'cloud_url':'https://api.deepseek.com/v1','cloud_model':'deepseek-flash',
        'edge_url':'http://127.0.0.1:8080/v1','edge_model':'edge-small'}).status_code==200
    case=client.post('/api/v1/demos',json={'scenario':'registered_document'}).json();base='/api/v1/cases/'+case['id']
    assert client.post(base+'/documents',files={'file':('synthetic.docx',registered_fixture['document'].read_bytes())}).status_code==200
    SCENARIOS.pop(registered_demo.SCENARIO)  # Fresh standalone worker registry.
    assert worker.process_one(store,env['root'])
    class LocalStub:
        def __init__(self,*args,**kwargs):self.model='edge-small';self.url='http://127.0.0.1:8080/v1'
        def extract(self,blocks,**kwargs):
            block=next(b for b in blocks if '1,200元' in b['text'])
            return [{'field':'amount','value':'1,200元','source_ids':[block['id']],
                'suggested_transform':'generalize','disclosure_reason':'Synthetic stub only'}]
        def review_outbound(self,facts,**kwargs):
            return {'decision':'allow_human_review','reason':'Synthetic review stub only','risk_codes':[],
                'evidence_fact_ids':[f['id'] for f in facts],'response_hash':'sha256:'+'a'*64,'model':self.model,'endpoint':self.url}
    monkeypatch.setattr(worker,'EdgeClient',LocalStub)
    monkeypatch.setattr(service,'EdgeClient',LocalStub)
    monkeypatch.setenv('LEX_DEMO_LIVE_EDGE_REVIEW','1')
    monkeypatch.setenv('LEX_EDGE_OUTBOUND_REVIEW','1')
    assert client.post(base+'/extract').status_code==200
    assert worker.process_one(store,env['root'])
    fact=client.get(base).json()['facts'][0]
    assert not fact['confirmed'] and fact['origin']=='edge_model'
    assert client.put(base+'/facts/'+fact['id'],json={**{k:fact[k] for k in ('field','value','source_ids')},'confirmed':True}).status_code==200
    task=client.post(base+'/tasks',json={'transport':'cloud'}).json();task=approve(env,task)
    from lexaegis.wire_bytes import approval_binding
    expected_wire=approval_binding(task['request'])
    assert task['approval']['request_hash']==digest(task['request'])
    class ReturningStub(_Provider):
        def dispatch(self,target,body,**kwargs):
            result=super().dispatch(target,body,**kwargs)
            wire=json.loads(body['messages'][1]['content']);item=wire['facts'][0]
            result.result={'claims':[{'text':item['text'],'source_ids':[item['id']]}],'unused_fact_ids':[],'gaps':[]}
            return result
    provider=ReturningStub();gateway=create_gateway(env['temp']/'registered-gateway',secret='unit-test-secret-32-characters-long',provider=provider)
    with TestClient(gateway) as gate:
        assert client.post('/api/v1/tasks/'+task['id']+'/send').status_code==200
        assert worker.process_one(store,env['root'],gate)
        with gateway.state.store.read() as repo:
            sent=repo.get(task['request']['request_id'],'send')
        assert sent['attempts'][0]['prepared_wire_body_sha256']==expected_wire['slots']['primary']['body_sha256']
    completed=next(t for t in client.get(base).json()['tasks'] if t['id']==task['id'])
    assert completed['status']=='complete',completed.get('error')
    assert provider.calls==1 and completed['artifact']['claims'][0]['anchors']
    login_as(env,'legal_reviewer')
    claim_id=completed['artifact']['claims'][0]['id']
    assert client.post('/api/v1/tasks/'+task['id']+'/claims/'+claim_id+'/review').status_code==200
    confirmed=client.post('/api/v1/tasks/'+task['id']+'/confirm')
    assert confirmed.status_code==200 and confirmed.json()['artifact']['confirmed']

def test_shared_budget_and_stream_metadata_survive_restart(tmp_path):
    quota=Budget(tmp_path/'quota.sqlite',initial=13,limit=20)
    wire=b'data: {"model":"deepseek-v4.1-flash","choices":[{"secret":"NEVER-PERSIST"}]}\n\ndata: {"usage":{"prompt_tokens":4,"completion_tokens":6,"total_tokens":10}}\n\ndata: [DONE]\n'
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=wire))
    with BudgetClient(budget=quota,transport=transport,trust_env=False) as client:
        for _ in range(7):
            response=client.post('https://api.deepseek.com/v1/chat/completions',json={'model':'deepseek-flash'})
            assert response.content==wire
        with pytest.raises(RuntimeError,match='quota exhausted'):client.post('https://api.deepseek.com/v1/chat/completions',json={'model':'deepseek-flash'})
    restart=Budget(tmp_path/'quota.sqlite',initial=13,limit=20)
    assert restart.status()=={'limit':20,'reserved':20,'remaining':0}
    with restart.connection() as db:
        rows=db.execute('SELECT response_model,usage FROM attempts').fetchall()
        assert all(model=='deepseek-v4.1-flash' and json.loads(usage)['total_tokens']==10 for model,usage in rows)
    assert b'NEVER-PERSIST' not in (tmp_path/'quota.sqlite').read_bytes()

def test_failed_post_consumes_quota_no_refund(tmp_path):
    quota=Budget(tmp_path/'quota.sqlite',initial=13,limit=20)
    def fail(request):raise httpx.ReadTimeout('after dispatch')
    with BudgetClient(budget=quota,transport=httpx.MockTransport(fail),trust_env=False) as client:
        with pytest.raises(httpx.ReadTimeout):client.post('https://api.deepseek.com/v1/chat/completions',json={'model':'deepseek-flash'})
    assert quota.status()['reserved']==14

def test_gzip_metadata_does_not_modify_provider_stream(tmp_path):
    import gzip
    quota=Budget(tmp_path/'gzip.sqlite',initial=13,limit=20)
    raw=b'data: {"model":"deepseek-flash","choices":[]}\n\ndata: {"usage":{"total_tokens":12}}\n\n'
    compressed=gzip.compress(raw)
    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'Content-Encoding':'gzip'},stream=httpx.ByteStream(compressed)))
    with BudgetClient(budget=quota,transport=transport,trust_env=False) as client:
        with client.stream('POST','https://api.deepseek.com/v1/chat/completions',json={'model':'deepseek-flash'}) as response:
            assert b''.join(response.iter_raw())==compressed
    with quota.connection() as db:
        model,usage=db.execute('select response_model,usage from attempts').fetchone()
        assert model=='deepseek-flash' and json.loads(usage)['total_tokens']==12
