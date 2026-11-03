"""Local stub tests; never call a provider or the real model."""
import httpx
from fastapi.testclient import TestClient
import pytest

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/workbench_demo'))

import edge_connector
import model_route_guard


def test_unconfigured_connector_never_probes_an_existing_host_model(monkeypatch):
    monkeypatch.delenv('LEX_MODEL_CONFIGURED',raising=False)
    monkeypatch.setattr(edge_connector.httpx,'AsyncClient',lambda **kwargs:(_ for _ in ()).throw(AssertionError('Unconfigured model must not be contacted')))
    with TestClient(edge_connector.app) as client:
        assert client.get('/v1/models').status_code==503
        assert client.post('/v1/chat/completions',json={'model':'edge-small'}).status_code==503

def test_model_route_is_required_and_other_routes_are_absent(monkeypatch):
    monkeypatch.setattr(edge_connector,'guarded',lambda:False)
    with TestClient(edge_connector.app) as client:
        assert client.get('/v1/models').status_code==503
        assert client.post('/v1/chat/completions',json={'model':'edge-small'}).status_code==503
        assert client.get('/untrusted-url').status_code==404
        assert client.post('/dispatch',json={}).status_code==404

def test_connector_only_calls_fixed_local_model_without_credentials(monkeypatch):
    observed=[]
    actual=httpx.AsyncClient
    async def local_model(request):
        observed.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"facts":[]}'}}]})
    monkeypatch.setattr(edge_connector,'guarded',lambda:True)
    monkeypatch.setattr(edge_connector.httpx,'AsyncClient',lambda **kwargs:actual(transport=httpx.MockTransport(local_model),**kwargs))
    with TestClient(edge_connector.app) as client:
        body={'model':'edge-small','messages':[{'role':'user','content':'local synthetic'}]}
        response=client.post('/v1/chat/completions',json=body,headers={'Authorization':'Bearer must-not-forward','Cookie':'private-cookie'})
        assert response.status_code==200
        assert str(observed[-1].url)=='http://192.168.65.254:18080/v1/chat/completions'
        assert 'authorization' not in observed[-1].headers and 'cookie' not in observed[-1].headers
        count=len(observed)
        assert client.post('/v1/chat/completions',json={**body,'model':'other-provider'}).status_code==400
        assert client.post('/v1/chat/completions',json={**body,'stream':True}).status_code==400
        assert len(observed)==count

def test_host_route_is_kept_but_ipv4_and_ipv6_defaults_are_removed(monkeypatch):
    calls=[];defaults={'-4':True,'-6':True}
    def command(*args):
        calls.append(args)
        if args[:4]==('-j','-4','route','show'):return b'[{"gateway":"172.23.0.1","dev":"eth0"}]'
        if args[1:] == ('route','show','default'):return b'default' if defaults[args[0]] else b''
        if args[1:] == ('route','del','default'):defaults[args[0]]=False
        return b''
    monkeypatch.setattr(model_route_guard,'command',command)
    model_route_guard.enforce()
    assert ('-4','route','replace','192.168.65.254/32','via','172.23.0.1','dev','eth0') in calls
    assert not any(defaults.values())
