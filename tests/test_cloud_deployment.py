"""Cloud-only regressions; no application files or real provider are changed."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from lexaegis.gateway import create_gateway
from tests.test_gateway_release import SECRET, _Provider, _request, _envelope


def runtime():
    spec=importlib.util.spec_from_file_location('deployment_cloud_runtime',Path(__file__).resolve().parents[1]/'deploy/cloud_gateway/cloud_runtime.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(index):
    value=_request('integration')
    value['request_id']=f'cloud-deployment-test-{index}'
    return value


def test_quota_is_atomic_and_persistent_without_changing_core(monkeypatch,tmp_path):
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    module=runtime(); provider=_Provider(); root=tmp_path/'gateway'
    app=create_gateway(root,secret=SECRET,provider=provider)
    budget=module.IntegrationBudget(app,app.state.store,SECRET,10,0)
    with TestClient(budget) as client:
        def send(index): return client.post('/dispatch',json=_envelope(request(index))).status_code
        with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(send,range(16)))
        assert results.count(200)==10 and results.count(409)==6
        assert provider.calls==10 and budget.quota()['remaining']==0
    app=create_gateway(root,secret=SECRET,provider=provider)
    budget=module.IntegrationBudget(app,app.state.store,SECRET,10,0)
    with TestClient(budget) as client:
        assert client.post('/dispatch',json=_envelope(request(99))).status_code==409
        with app.state.store.read() as repo:
            completed=repo.list('send')[0]
        index=int(completed['id'].rsplit('-',1)[1])
        assert client.post('/dispatch',json=_envelope(request(index))).status_code==200
        assert provider.calls==10


def test_previous_ten_attempts_are_imported_not_reset(monkeypatch,tmp_path):
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    module=runtime(); provider=_Provider()
    app=create_gateway(tmp_path/'gateway',secret=SECRET,provider=provider)
    with app.state.store.transaction() as repo:
        repo.put('integration_quota',{'id':'integration-cloud-quota','reserved':10})
    budget=module.IntegrationBudget(app,app.state.store,SECRET,10,0)
    with TestClient(budget) as client:
        assert client.post('/dispatch',json=_envelope(request(1))).status_code==409
    assert provider.calls==0 and budget.quota()['reserved']==10


def test_bad_signature_cannot_consume_cloud_quota(monkeypatch,tmp_path):
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    module=runtime(); provider=_Provider()
    app=create_gateway(tmp_path/'gateway',secret=SECRET,provider=provider)
    budget=module.IntegrationBudget(app,app.state.store,SECRET,10,0)
    value=_envelope(request(1)); value['signature']='invalid'
    with TestClient(budget) as client:
        assert client.post('/dispatch',json=value).status_code==403
    assert budget.quota()['reserved']==0 and provider.calls==0


def test_unknown_attempt_is_never_refunded_or_replayed(monkeypatch,tmp_path):
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    module=runtime(); provider=_Provider(fail=True)
    app=create_gateway(tmp_path/'gateway',secret=SECRET,provider=provider)
    budget=module.IntegrationBudget(app,app.state.store,SECRET,1,0)
    with TestClient(budget) as client:
        assert client.post('/dispatch',json=_envelope(request(1))).json()['status']=='unknown'
        assert client.post('/dispatch',json=_envelope(request(1))).json()['status']=='unknown'
        assert client.post('/dispatch',json=_envelope(request(2))).status_code==409
    assert provider.calls==1


def test_proxy_only_accepts_the_exact_tls_target():
    spec=importlib.util.spec_from_file_location('deployment_proxy',Path(__file__).resolve().parents[1]/'deploy/cloud_gateway/provider_egress.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.allowed_connect(b'CONNECT api.deepseek.com:443 HTTP/1.1\r\n\r\n')
    for target in ('example.com:443','127.0.0.1:443','api.deepseek.com.evil:443','api.deepseek.com:80'):
        assert not module.allowed_connect(f'CONNECT {target} HTTP/1.1\r\n\r\n'.encode())


def test_factory_health_uses_original_gateway_and_closes_client(monkeypatch,tmp_path):
    from lexaegis.util import sign
    module=runtime()
    monkeypatch.setenv('LEX_RUN_PROFILE','integration')
    monkeypatch.setenv('LEX_GATEWAY_ROLE','cloud')
    monkeypatch.setenv('LEX_GATEWAY_DIR',str(tmp_path/'gateway'))
    monkeypatch.setattr(module,'private_value',lambda path:SECRET if path.name=='gateway-secret' else
        'LEX_CLOUD_PRIMARY_KEY=synthetic-cloud-key-1234567890\nLEX_KEY_USE_CONFIRMED=1\n')
    with TestClient(module.create_app()) as client:
        assert client.get('/health').status_code==403
        headers={'X-Gateway-Signature':sign({'op':'health'},SECRET)}
        assert client.get('/health',headers=headers).json()['gateway_role']=='cloud'
        assert client.get('/deployment/status',headers=headers).json()['quota']['remaining']==0


def test_docker_context_contains_only_gateway_inputs(tmp_path):
    spec=importlib.util.spec_from_file_location('cloud_control',Path(__file__).resolve().parents[1]/'deploy/cloud_gateway/control.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.build_context(tmp_path)
    assert {p.name for p in tmp_path.iterdir()}=={'lexaegis','packs','requirements.lock','deploy'}
    assert not list(tmp_path.rglob('*.env')) and not list(tmp_path.rglob('*.sqlite'))
    assert not list(tmp_path.rglob('__pycache__'))
    assert (tmp_path/'lexaegis/gateway.py').read_bytes()==(module.ROOT/'lexaegis/gateway.py').read_bytes()
