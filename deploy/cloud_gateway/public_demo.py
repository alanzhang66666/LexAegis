"""Read-only public adapter for the unchanged, synthetic-only workbench."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

DATA=Path('/data/public-demo')
API='http://127.0.0.1:59765'
GATEWAY='http://127.0.0.1:59766'


def require(response,stage):
    if response.status_code>=400: raise RuntimeError(stage+': HTTP '+str(response.status_code))
    return response.json()


def seed(accounts):
    marker=DATA/'seed-complete.json'
    if marker.exists(): return json.loads(marker.read_text())
    with httpx.Client(base_url=API,trust_env=False,timeout=60) as client:
        def login(role='admin'):
            client.post('/api/v1/logout')
            require(client.post('/api/v1/login',json=accounts[role]),'synthetic_login')
        login()
        existing=require(client.get('/api/v1/users'),'users')
        for role in ('case_operator','legal_reviewer','approver'):
            if not any(user['username']==accounts[role]['username'] for user in existing):
                require(client.post('/api/v1/users',json={**accounts[role],'role':role,
                    'display_name':'公开合成演示 · '+('只读访客' if role=='case_operator' else '自动化测试角色（非真人签署）')}),'create_synthetic_role')
        cases=[]
        packs=require(client.get('/api/v1/domains'),'packs')
        for scenario in ('success','linkage'):
            login()
            case=require(client.post('/api/v1/demos',json={'scenario':scenario}),'create_bundled_case')
            task=require(client.post(f"/api/v1/cases/{case['id']}/tasks",json={'transport':'mock'}),'create_mock_task')
            evaluated=require(client.post(f"/api/v1/tasks/{task['id']}/evaluate"),'evaluate')
            if scenario=='success':
                if evaluated['risk']['blockers']: raise RuntimeError('Synthetic success is blocked')
                pack=next(p for p in packs if p['id']==task['pack_id'])
                conditions=pack.get('manual_review_conditions') or [c for r in pack.get('rules',[]) for c in r.get('conditions',[])]
                review={'request_hash':evaluated['request_hash'],'material_version':case['revision'],
                    'idempotency_key':'public-synthetic-'+task['id'],'conclusion':'allow_processing',
                    'reason':'公开只读合成演示自动化测试，不是真实人员法学签署。',
                    'evidence_ids':[task['fact_snapshot'][0]['id']], 'reviewed_condition_ids':[conditions[0]['id']],
                    'legal_source_ids':[pack['legal_sources'][0]['id']],'acknowledged_risk_notices':True,
                    'scope_note':'仅预置合成演示，模拟调用。','fact_premise':'所有材料均为仓库内置虚构案例。',
                    'authority_judgment':'仅验证合成流程。','external_processing_note':'mock 模拟结果，无服务商调用。',
                    'minimization_note':'沿用原应用披露规则。','final_basis':'自动化合成状态流转示例。'}
                login('legal_reviewer')
                require(client.post(f"/api/v1/tasks/{task['id']}/legal-review",json=review),'synthetic_review')
                login('approver')
                require(client.post(f"/api/v1/tasks/{task['id']}/approve",json={'request_hash':evaluated['request_hash']}),'synthetic_approval')
                login()
                require(client.post(f"/api/v1/tasks/{task['id']}/send"),'mock_only_send')
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    detail=require(client.get('/api/v1/cases/'+case['id']),'case')
                    finished=next(t for t in detail['tasks'] if t['id']==task['id'])
                    if finished['status']=='complete': break
                    time.sleep(.25)
                else: raise RuntimeError('Mock completion timed out')
                if finished['artifact']['provenance']!='simulation': raise RuntimeError('Public demo must be simulated')
                login('legal_reviewer')
                for claim in finished['artifact']['claims']:
                    require(client.post(f"/api/v1/tasks/{task['id']}/claims/{claim['id']}/review"),'synthetic_claim_review')
                require(client.post(f"/api/v1/tasks/{task['id']}/confirm"),'synthetic_confirm')
            elif not evaluated['risk']['blockers']:
                raise RuntimeError('Risk scenario unexpectedly allows dispatch')
            cases.append({'id':case['id'],'scenario':scenario,'task_id':task['id']})
    metadata={'data_origin':'bundled_synthetic','access':'read_only','transport':'mock','real_cloud_calls':0,'cases':cases}
    marker.write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
    return metadata


def serve(accounts,metadata):
    viewer=httpx.Client(base_url=API,trust_env=False,follow_redirects=False,timeout=15)
    login_lock=threading.Lock()
    def login():
        with login_lock:
            require(viewer.post('/api/v1/login',json=accounts['case_operator']),'public_viewer_login')
    login()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,status,content,media='application/json; charset=utf-8',headers=None):
            self.send_response(status)
            self.send_header('Content-Type',media)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-LexAegis-Demo','synthetic-readonly')
            for name,value in (headers or {}).items(): self.send_header(name,value)
            self.end_headers()
            if self.command!='HEAD': self.wfile.write(content)
        def do_GET(self):
            if len(self.path)>8192 or not self.path.startswith('/') or self.path.startswith('//'):
                return self.respond(400,b'{"detail":"Invalid demo path"}')
            if self.path=='/_public_demo_health':
                return self.respond(200,json.dumps({'status':'ready',**metadata}).encode())
            if self.path.split('?',1)[0].endswith('/events'):
                # No state changes in this immutable demo; 204 stops EventSource.
                return self.respond(204,b'')
            try:
                response=viewer.get(self.path)
                if response.status_code==401:
                    login(); response=viewer.get(self.path)
                content=response.content
                media=response.headers.get('content-type','application/octet-stream')
                if 'text/html' in media:
                    badge='<div style="position:fixed;bottom:12px;right:16px;z-index:99999;padding:8px 14px;border-radius:20px;background:#103b46;color:white;font:13px system-ui;box-shadow:0 2px 12px #0003">只读合成演示 · 模拟结果</div>'
                    content=content.replace(b'</body>',badge.encode()+b'</body>')
                self.respond(response.status_code,content,media)
            except (httpx.HTTPError,RuntimeError):
                self.respond(503,b'{"detail":"Demo temporarily unavailable"}')
        do_HEAD=do_GET
        def blocked(self):
            self.respond(403,json.dumps({'detail':'公开演示为只读，请在本地工作台操作。'},ensure_ascii=False).encode())
        do_POST=blocked
        do_PUT=blocked
        do_PATCH=blocked
        do_DELETE=blocked
        do_OPTIONS=blocked
    server=ThreadingHTTPServer(('0.0.0.0',59767),Handler)
    print('Read-only synthetic workbench ready',flush=True)
    try: server.serve_forever()
    finally: viewer.close(); server.server_close()


def main():
    DATA.mkdir(parents=True,exist_ok=True)
    config=DATA/'config'; config.mkdir(mode=0o700,exist_ok=True)
    file=config/'accounts.json'
    if file.exists(): accounts=json.loads(file.read_text())
    else:
        accounts={role:{'username':'admin' if role=='admin' else 'public.demo.'+role,'password':secrets.token_urlsafe(24)}
                  for role in ('admin','case_operator','legal_reviewer','approver')}
        file.write_text(json.dumps(accounts)); file.chmod(0o600)
    secret_file=config/'gateway-secret'
    if not secret_file.exists(): secret_file.write_text(secrets.token_urlsafe(32)); secret_file.chmod(0o600)
    secret=secret_file.read_text().strip()
    base={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','PYTHONPATH'}}
    base.update(LEX_RUN_PROFILE='demo',LEX_DEPLOYMENT_MODE='native',LEX_DATA_DIR=str(DATA/'app'),
        LEX_GATEWAY_DIR=str(DATA/'gateway'),LEX_GATEWAY_SECRET=secret,LEX_API_PORT='59765',LEX_GATEWAY_PORT='59766',
        LEX_GATEWAY_URL=GATEWAY,LEX_EDGE_MODEL='',LEX_EDGE_OUTBOUND_REVIEW='0',LEX_DEMO_LIVE_EDGE_REVIEW='0',
        LEX_OCR_ENABLED='0',LEX_WHISPER_ENABLED='0',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
    processes=[]
    try:
        for role,command in (
            ('gateway',[sys.executable,'-m','uvicorn','lexaegis.gateway:create_gateway','--factory','--host','127.0.0.1','--port','59766','--no-access-log']),
            ('api',[sys.executable,'-m','uvicorn','lexaegis.api:create_app','--factory','--host','127.0.0.1','--port','59765','--no-access-log'])):
            env={**base,'LEX_RUNTIME_ROLE':role}
            if role=='api': env.update(LEX_LOCAL_PASSWORD=accounts['admin']['password'],LEX_LOCAL_ACTOR='公开合成演示管理员')
            processes.append(subprocess.Popen(command,cwd='/app',env=env,stdin=subprocess.DEVNULL))
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if any(p.poll() is not None for p in processes): raise RuntimeError('Demo service exited')
            try:
                if httpx.get(API+'/api/v1/health',trust_env=False,timeout=2).status_code==200: break
            except httpx.HTTPError: pass
            time.sleep(.25)
        else: raise RuntimeError('Demo startup timed out')
        # The API finishes initializing/migrating its empty app store before
        # the worker opens it. Only the deployment startup order changes.
        processes.append(subprocess.Popen([sys.executable,'-m','lexaegis.worker'],cwd='/app',
            env={**base,'LEX_RUNTIME_ROLE':'worker'},stdin=subprocess.DEVNULL))
        metadata=seed(accounts)
        serve(accounts,metadata)
    finally:
        for process in reversed(processes): process.terminate()
        for process in reversed(processes):
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()


if __name__=='__main__': main()
