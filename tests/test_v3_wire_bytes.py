"""Synthetic formal approvals + httpx transport: no external provider is called."""
from copy import deepcopy
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from lexaegis import service, wire_bytes
from lexaegis.cloud import DualSlotProvider, assemble_chat_completion, PreGenerationError
from lexaegis.gateway import create_gateway
from lexaegis.util import sign
from tests.test_gateway_release import SECRET, _bundle, _envelope, _manifest, _request
from tests.test_v3_auto_request_policy import ready, approve


def sse():
    result = json.dumps({'claims':[], 'unused_fact_ids':[], 'gaps':[]})
    event = json.dumps({'choices':[{'delta':{'content':result}}]})
    return httpx.Response(200, content='data: '+event+'\ndata: [DONE]\n', headers={'content-type':'text/event-stream'})


def provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DualSlotProvider('synthetic-only-key', 'synthetic-standby-key', client=client), client


def resign(envelope):
    envelope['signature'] = sign({k:v for k,v in envelope.items() if k!='signature'}, SECRET)
    return envelope


def test_bytes_stable_unicode_and_no_unapproved_fields():
    r = _request(); body = r['body']
    body['messages'][0]['content'] = '工资、日期与否认'
    a = wire_bytes.serialize_body(r['target'], body, body['model'])
    b = wire_bytes.serialize_body(r['target'], dict(reversed(list(body.items()))), body['model'])
    assert a == b and '工资'.encode() in a
    parsed = json.loads(a)
    assert parsed['stream'] is True and parsed['temperature']==0 and parsed['thinking']=={'type':'disabled'}
    assert b'api_key' not in a and b'wire_binding' not in a
    assert wire_bytes.body_receipt(r['target'], body, body['model'])['body_sha256']==hashlib.sha256(a).hexdigest()


@pytest.mark.parametrize('value',[float('nan'),float('inf')])
def test_non_json_numbers_rejected(value):
    r=_request(); r['body']['messages'][0]['bad']=value
    with pytest.raises(ValueError): wire_bytes.approval_binding(r)


@pytest.mark.parametrize('field',['missing','hash','target','version_type','extra','model','size'])
def test_signed_bad_binding_rejected_before_claim(monkeypatch,tmp_path,field):
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    calls=[]
    p,client=provider(lambda request: calls.append(request) or sse())
    app=create_gateway(tmp_path/field,secret=SECRET,provider=p,build_manifest=_manifest())
    r=_request(); envelope=_envelope(r,_bundle(r,_manifest()))
    binding=envelope['approval']['wire_binding']; slot=binding['slots']['primary']
    if field=='missing': envelope['approval'].pop('wire_binding')
    elif field=='hash': slot['body_sha256']='0'*64
    elif field=='target': slot['target']='https://api.openai.com/v1/chat/completions'
    elif field=='version_type': binding['version']=True
    elif field=='extra': binding['authorization']=True
    elif field=='model': slot['model']='unapproved-model'
    else: slot['body_size']+=1
    with TestClient(app) as gateway:
        response=gateway.post('/dispatch',json=resign(envelope))
    assert response.status_code==403, response.text
    assert not calls
    with app.state.store.read() as repo:
        assert repo.list('send')==[] and repo.list('formal_release_claim')==[]
    app.state.store.engine.dispose();client.close()


def test_actual_transport_bytes_equal_approval_and_durable_receipts(monkeypatch,tmp_path):
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    captured=[]
    p,client=provider(lambda request: captured.append(request) or sse())
    app=create_gateway(tmp_path/'actual',secret=SECRET,provider=p,build_manifest=_manifest())
    r=_request(); envelope=_envelope(r,_bundle(r,_manifest()))
    with TestClient(app) as gateway:
        response=gateway.post('/dispatch',json=envelope)
        assert response.status_code==200, response.text
        record=response.json()
        assert record['status']=='complete'
        assert gateway.post('/dispatch',json=envelope).json()==record
    assert len(captured)==1
    expected=envelope['approval']['wire_binding']['slots']['primary']
    actual=hashlib.sha256(captured[0].content).hexdigest()
    attempt=record['attempts'][0]
    assert actual==expected['body_sha256']==attempt['approved_wire_body_sha256']
    assert actual==attempt['prepared_wire_body_sha256']==attempt['attempted_wire_body_sha256']
    assert len(captured[0].content)==expected['body_size']==attempt['wire_body_size']
    assert captured[0].headers['content-type']=='application/json'
    with app.state.store.read() as repo:
        assert repo.get(r['request_id'],'send')['attempts'][0]==attempt
        assert repo.list('formal_release_claim')[0]['state']=='complete'
    assert 'synthetic-only-key' not in json.dumps(record)
    assert '仅总结给定事实' not in json.dumps(attempt,ensure_ascii=False)
    app.state.store.engine.dispose();client.close()


def test_transport_serializer_drift_never_calls_network(monkeypatch):
    r=_request(); captured=[]
    p,client=provider(lambda request: captured.append(request) or sse())
    original=wire_bytes.serialize_body
    count=0
    def drift(*args):
        nonlocal count
        count+=1
        value=original(*args)
        return value if count==1 else value+b' '
    monkeypatch.setattr(wire_bytes,'serialize_body',drift)
    outcome=p.dispatch(r['target'],r['body'],dual_slot=r['dependencies']['dual_slot'])
    assert not captured and outcome.error=='wire_body_mismatch'
    assert outcome.status!='complete' and outcome.disclosure_state=='undisclosed'
    client.close()


def test_persistence_failure_prevents_transport():
    r=_request(); captured=[]
    p,client=provider(lambda request: captured.append(request) or sse())
    def persist(attempts, authorized):
        if attempts[0].get('attempted_wire_body_sha256'): raise RuntimeError('synthetic disk failure')
    with pytest.raises(RuntimeError):
        p.dispatch(r['target'],r['body'],dual_slot=r['dependencies']['dual_slot'],persist_attempt=persist)
    assert not captured
    client.close()


def test_standby_has_its_own_bytes_not_primary_bytes():
    r=_request(); slots=r['dependencies']['dual_slot']
    slots['standby']={'target':'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions','model':'qwen-test'}
    binding=wire_bytes.approval_binding(r); captured=[]
    def handler(request):
        captured.append(request)
        if len(captured)==1: raise httpx.ConnectError('synthetic refusal')
        return sse()
    p,client=provider(handler)
    persisted=[]
    def persist(attempts, authorized):
        for item in attempts: wire_bytes.validate_attempt(binding,item)
        persisted.append(deepcopy(attempts))
    result=p.dispatch(r['target'],r['body'],dual_slot=slots,persist_attempt=persist)
    assert result.status=='complete' and result.selected_slot=='standby'
    assert len(captured)==2
    hashes=[hashlib.sha256(item.content).hexdigest() for item in captured]
    assert hashes[0]!=hashes[1]
    assert hashes==[binding['slots'][name]['body_sha256'] for name in ('primary','standby')]
    assert all(item['attempted_wire_body_sha256']==hashes[index] for index,item in enumerate(result.attempts))
    client.close()


@pytest.mark.parametrize('mutation',['missing','tampered'])
def test_enqueue_rechecks_saved_byte_binding(ready,mutation):
    f=ready
    with f['store'].transaction() as repo:
        task=approve(f,repo)
        assert task['approval']['wire_binding']==wire_bytes.approval_binding(task['request'])
        if mutation=='missing': task['approval'].pop('wire_binding')
        else: task['approval']['wire_binding']['slots']['primary']['body_sha256']='0'*64
        repo.put('task',task,task['case_id'])
        with pytest.raises(ValueError,match='binding'):
            service.reserve_send(repo,task['id'],release_context=f['context'])
        assert repo.list('disclosure')==[] and f['provider'].calls==0


def test_direct_assembly_mismatch_before_transport():
    r=_request(); calls=[]
    client=httpx.Client(transport=httpx.MockTransport(lambda request:calls.append(request) or sse()))
    with pytest.raises(PreGenerationError,match='wire_body_mismatch'):
        assemble_chat_completion(r['target'],r['body'],'synthetic-key',client=client,expected_wire_body_sha256='0'*64)
    assert not calls
    client.close()


def test_uninstrumented_provider_rejected_before_claim(monkeypatch,tmp_path):
    from tests.test_gateway_release import _Provider
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    p=_Provider(); p.supports_wire_binding=False
    app=create_gateway(tmp_path/'unsupported',secret=SECRET,provider=p,build_manifest=_manifest())
    r=_request()
    with TestClient(app) as gateway:
        response=gateway.post('/dispatch',json=_envelope(r,_bundle(r,_manifest())))
    assert response.status_code==403 and p.calls==0
    with app.state.store.read() as repo: assert repo.list('formal_release_claim')==[]
    app.state.store.engine.dispose()


def test_claimed_complete_without_pretransport_receipt_stays_unknown(monkeypatch,tmp_path):
    from tests.test_gateway_release import _Provider, _Outcome
    from lexaegis.cloud import _begin_attempt
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    class LateReceipt(_Provider):
        def dispatch(self,target,body,dual_slot=None,persist_attempt=None):
            self.calls+=1
            result=_Outcome(); result.selected_slot='primary'
            row=_begin_attempt(dual_slot['primary'],body,'primary')
            row.update(attempted_wire_body_sha256=row['prepared_wire_body_sha256'],transmission_state='response_received')
            result.attempts=[row]  # Deliberately never calls persist_attempt.
            return result
    p=LateReceipt();app=create_gateway(tmp_path/'late',secret=SECRET,provider=p,build_manifest=_manifest())
    r=_request();envelope=_envelope(r,_bundle(r,_manifest()))
    with TestClient(app) as gateway:
        response=gateway.post('/dispatch',json=envelope)
        assert response.json()['status']=='unknown'
        assert gateway.post('/dispatch',json=envelope).json()==response.json()
    assert p.calls==1
    app.state.store.engine.dispose()


def test_full_worker_to_http_transport_propagates_byte_receipt(ready,tmp_path):
    from lexaegis.worker import process_one
    from tests.test_release_service_integration import SECRET as WORKER_SECRET
    f=ready;captured=[]
    def response(request):
        captured.append(request)
        result={'claims':[{'text':'合成事实','source_ids':['fact-1']}], 'unused_fact_ids':[], 'gaps':[]}
        content=json.dumps({'choices':[{'delta':{'content':json.dumps(result)}}]})
        return httpx.Response(200,content='data: '+content+'\ndata: [DONE]\n')
    p,client=provider(response)
    gateway=create_gateway(tmp_path/'byte-gateway',secret=WORKER_SECRET,provider=p,build_manifest=f['context']['build_manifest'])
    with f['store'].transaction() as repo:
        task=approve(f,repo)
        binding=deepcopy(task['approval']['wire_binding'])
        service.reserve_send(repo,task['id'],release_context=f['context'])
    with TestClient(gateway) as gate:
        assert process_one(f['store'],f['root'],gate)
    assert len(captured)==1
    with f['store'].read() as repo:
        current=repo.get(task['id'],'task')
        assert current['status']=='complete'
        row=current['attempts'][0]
        actual=hashlib.sha256(captured[0].content).hexdigest()
        assert actual==binding['slots']['primary']['body_sha256']==row['approved_wire_body_sha256']==row['attempted_wire_body_sha256']
        disclosure=repo.get(task['request']['request_id'],'disclosure')
        assert disclosure['attempts'][0]['attempted_wire_body_sha256']==actual
    gateway.state.store.engine.dispose();client.close()


def test_formal_gateway_failover_receipts_match_each_approved_slot(monkeypatch,tmp_path):
    from tests.test_formal_release_standby import (
        _request as standby_request, _gateway_bundle, _envelope as standby_envelope,
        _manifest as standby_manifest, SECRET as STANDBY_SECRET)
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    calls=[]
    def handler(request):
        calls.append(request)
        if len(calls)==1: raise httpx.ConnectError('synthetic local refusal')
        return sse()
    p,client=provider(handler)
    manifest=standby_manifest();r=standby_request()
    envelope=standby_envelope(r,_gateway_bundle(r,manifest))
    app=create_gateway(tmp_path/'formal-standby',secret=STANDBY_SECRET,provider=p,build_manifest=manifest)
    with TestClient(app) as gate:
        response=gate.post('/dispatch',json=envelope)
        assert response.status_code==200,response.text
        assert response.json()['status']=='complete'
        assert response.json()['selected_slot']=='standby'
        assert gate.post('/dispatch',json=envelope).json()==response.json()
    assert len(calls)==2
    for request,attempt in zip(calls,response.json()['attempts']):
        actual=hashlib.sha256(request.content).hexdigest()
        assert actual==attempt['approved_wire_body_sha256']==attempt['attempted_wire_body_sha256']
    app.state.store.engine.dispose();client.close()
