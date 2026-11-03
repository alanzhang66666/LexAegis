"""Stub tests for expired tunnels, stale URLs and false availability."""
import httpx
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/workbench_demo'))

import public_access as access

def test_url_cache_cannot_cross_restart_or_container_recreation():
    previous={'container_id':'one','started_at':'before','observed_url':'https://old.trycloudflare.com'}
    assert access.current_url('', 'one','after',previous) is None
    assert access.current_url('', 'two','before',previous) is None
    assert access.current_url('', 'one','before',previous)==previous['observed_url']
    assert access.current_url('https://new.trycloudflare.com','one','after',previous)=='https://new.trycloudflare.com'

def test_container_running_does_not_make_expired_tunnel_available(tmp_path,monkeypatch):
    monkeypatch.setattr(access,'ROOT',tmp_path)
    monkeypatch.setattr(access,'inspect',lambda _: {'Id':'one','State':{'Running':True,'StartedAt':'current'}})
    monkeypatch.setattr(access,'run',lambda *_: ('https://expired.trycloudflare.com\nRegistered tunnel connection\nUnauthorized: Tunnel not found',''))
    monkeypatch.setattr(access,'https_probe',lambda *_: (_ for _ in ()).throw(AssertionError('Do not probe a known expired URL')))
    result=access.snapshot('demo')
    assert result['container_running'] and not result['public_reachable']
    assert result['url'] is None and result['last_error']=='tunnel_expired'

def test_repair_leaves_working_tunnel_and_its_url_unchanged(monkeypatch):
    result={'public_reachable':True,'url':'https://working.trycloudflare.com'}
    monkeypatch.setattr(access,'snapshot',lambda _:result)
    monkeypatch.setattr(access,'run',lambda *_: (_ for _ in ()).throw(AssertionError('Do not restart a working tunnel')))
    assert access.ensure('demo')==result

def test_public_error_page_is_not_a_working_workbench(monkeypatch):
    actual=httpx.Client
    def server(request):return httpx.Response(200,text='provider error page')
    monkeypatch.setattr(access.httpx,'Client',lambda **kwargs:actual(transport=httpx.MockTransport(server),**kwargs))
    assert not access.https_probe('https://expired.trycloudflare.com','interactive-integration')['reachable']
