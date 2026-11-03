"""Owned deployment identities, opt-in allowance, and transparent transport."""
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys

import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/cloud_gateway'))

def controller():
    spec=importlib.util.spec_from_file_location('workbench_demo_control_test',ROOT/'deploy/workbench_demo/control.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_new_installation_has_zero_allowance_and_no_provider_key(tmp_path,monkeypatch):
    module=controller();monkeypatch.setattr(module,'private_directory',lambda p:p.mkdir(parents=True,exist_ok=True))
    runtime=tmp_path/'runtime';module.main(['init','--runtime-root',str(runtime)])
    assert json.loads((runtime/'private/global-policy.json').read_text())=={'initial_reserved':0,'lifetime_limit':0}
    assert 'LEX_CLOUD_PRIMARY_KEY=\n' in (runtime/'private/gateway.env').read_text()
    compose=json.loads((runtime/'compose.json').read_text())
    assert all('KEY' not in name for app in compose['services'].values() for name in app.get('environment',{}))
    assert 'app-data:/data' not in compose['services']['gateway']['volumes']
    assert 'private:/run/private:ro' not in compose['services']['workbench']['volumes']
    policy=(runtime/'private/global-policy.json').read_bytes()
    module.main(['init','--runtime-root',str(runtime),'--cloud-limit','10'])
    assert (runtime/'private/global-policy.json').read_bytes()==policy

def test_init_refuses_existing_unmanaged_directory(tmp_path):
    module=controller();(tmp_path/'existing-case.txt').write_text('unrelated data')
    with pytest.raises(ValueError,match='empty'):module.main(['init','--runtime-root',str(tmp_path)])
    assert list(p.name for p in tmp_path.iterdir())==['existing-case.txt']

def test_start_does_not_restart_a_running_tunnel(tmp_path,monkeypatch):
    module=controller()
    monkeypatch.setattr(module,'inspect_owned',lambda *_:{'Id':'owned-tunnel','State':{'Running':True}})
    monkeypatch.setattr(module,'run',lambda *_:(_ for _ in ()).throw(AssertionError('Running tunnel must be preserved')))
    module.start_tunnel(tmp_path)

def test_cross_gateway_quota_is_atomic_and_never_stores_payload(tmp_path):
    from shared_budget import Budget
    quota=tmp_path/'budget.sqlite';a=Budget(quota,initial=0,limit=5);b=Budget(quota,initial=0,limit=5)
    def reserve(i):
        try:(a if i%2 else b).reserve(b'SYNTHETIC-CONTENT-MUST-NOT-BE-STORED','deepseek-flash');return True
        except RuntimeError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(reserve,range(16)))==5
    assert Budget(quota,initial=0,limit=5).status()=={'limit':5,'reserved':5,'remaining':0}
    assert b'SYNTHETIC-CONTENT-MUST-NOT-BE-STORED' not in quota.read_bytes()
    with pytest.raises(ValueError,match='immutable'):Budget(quota,initial=0,limit=10)

def test_default_gateway_starts_without_cloud_key_and_remains_signed(tmp_path,monkeypatch):
    import ds_gateway
    from shared_budget import Budget
    from lexaegis.util import sign
    secret='synthetic-signing-secret-at-least-32-characters'
    policy=tmp_path/'policy.json';policy.write_text('{"initial_reserved":0,"lifetime_limit":0}')
    values={'gateway.env':'LEX_CLOUD_PRIMARY_KEY=\nLEX_KEY_USE_CONFIRMED=0\n','gateway-secret':secret}
    monkeypatch.setattr(ds_gateway,'private_value',lambda path:values[Path(path).name])
    monkeypatch.setattr(ds_gateway,'Budget',lambda _,**kw:Budget(tmp_path/'quota.sqlite',**kw))
    for name,value in {'LEX_RUN_PROFILE':'integration','LEX_GATEWAY_DIR':str(tmp_path/'gateway'),
        'LEX_GATEWAY_ROLE':'edge','LEX_GLOBAL_POLICY_PATH':str(policy),'LEX_DEPLOYMENT_MODE':'native'}.items():monkeypatch.setenv(name,value)
    monkeypatch.delenv('LEX_REGISTERED_DEMO_MANIFEST',raising=False)
    with TestClient(ds_gateway.create_app()) as client:
        assert client.get('/deployment/status').status_code==403
        response=client.get('/deployment/status',headers={'X-Gateway-Signature':sign({'op':'health'},secret)})
        assert response.status_code==200 and response.json()['quota']=={'limit':0,'reserved':0,'remaining':0}
    monkeypatch.setenv('LEX_RUN_PROFILE','production')
    with pytest.raises(ValueError,match='integration-only'):ds_gateway.create_app()
