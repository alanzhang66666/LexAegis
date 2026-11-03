"""Launch the unchanged production API and worker with a private local model."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx
import uvicorn

ROOT=Path('/data/workbench/production')
API='http://127.0.0.1:59765'
ROLES={'admin':('admin','内部工作台管理员'),'case_operator':('operator','内部案件操作员'),
    'technical_reviewer':('technical','内部技术复核'),'legal_reviewer':('legal','内部法学复核'),
    'approver':('approver','内部审批人')}
def require(response,stage):
    if response.status_code>=400:raise RuntimeError(stage+': HTTP '+str(response.status_code))
    return response.json()
def provision(accounts):
    with httpx.Client(base_url=API,trust_env=False,timeout=30) as client:
        require(client.post('/api/v1/login',json=accounts['admin']),'administrator login')
        users=require(client.get('/api/v1/users'),'users')
        for role,(username,label) in ROLES.items():
            if role!='admin' and not any(user['username']==username for user in users):
                require(client.post('/api/v1/users',json={**accounts[role],'role':role,'display_name':label}),'create role')
        settings=require(client.get('/api/v1/bootstrap'),'bootstrap')['settings']
        if settings['edge_url']!='http://edge-model:8080/v1' or settings['edge_model']!='edge-small':
            require(client.put('/api/v1/settings',json={**{k:settings[k] for k in ('cloud_url','cloud_model','cloud_primary','cloud_standby')},
                'edge_url':'http://edge-model:8080/v1','edge_model':'edge-small'}),'configure local edge')
def main():
    ROOT.mkdir(parents=True,exist_ok=True);config=ROOT/'config';config.mkdir(mode=0o700,exist_ok=True)
    path=config/'accounts.json'
    if path.exists():accounts=json.loads(path.read_text())
    else:
        accounts={role:{'username':name,'password':secrets.token_urlsafe(24)} for role,(name,label) in ROLES.items()}
        path.write_text(json.dumps(accounts));path.chmod(0o600)
    base={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','PYTHONPATH'}}
    base.update(LEX_RUN_PROFILE='production',LEX_DEPLOYMENT_MODE='native',LEX_DATA_DIR=str(ROOT/'app'),
        LEX_GATEWAY_DIR=str(ROOT/'unused-gateway'),LEX_GATEWAY_URL='http://formal-gateway:8766',
        LEX_GATEWAY_SECRET=Path('/run/signing/gateway-secret').read_text().strip(),LEX_API_PORT='59765',
        LEX_CLOUD_ALLOWED_HOSTS='api.deepseek.com',LEX_EDGE_URL='http://edge-model:8080/v1',LEX_EDGE_MODEL='edge-small',
        LEX_EDGE_ALLOWED_HOSTS='edge-model',LEX_EDGE_IDLE_UNLOAD_SECONDS='0',
        LEX_EDGE_OUTBOUND_REVIEW='0',LEX_OCR_ENABLED='0',LEX_WHISPER_ENABLED='0',
        PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
    processes=[]
    try:
        processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','lexaegis.api:create_app','--factory',
            '--host','127.0.0.1','--port','59765','--no-access-log'],cwd='/app',
            env={**base,'LEX_RUNTIME_ROLE':'api','LEX_LOCAL_PASSWORD':accounts['admin']['password'],
                 'LEX_LOCAL_ACTOR':'内部工作台管理员'},stdin=subprocess.DEVNULL))
        for _ in range(180):
            if processes[0].poll() is not None:raise RuntimeError('API exited during startup')
            try:
                if httpx.get(API+'/api/v1/health',trust_env=False,timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.5)
        else:raise RuntimeError('API readiness timeout')
        provision(accounts)
        processes.append(subprocess.Popen([sys.executable,'-m','lexaegis.worker'],cwd='/app',
            env={**base,'LEX_RUNTIME_ROLE':'worker'},stdin=subprocess.DEVNULL))
        (ROOT/'ready.json').write_text(json.dumps({'status':'ready','runtime_profile':'production','access':'interactive',
            'edge':'live_local_model','edge_model':'MiniCPM5-2B Q4_K_M','authentication':'original_accounts',
            'formal_cloud_authorization':'blocked_pending_original_gates','repository_source_modified':False}))
        from public_proxy import app
        uvicorn.run(app,host='0.0.0.0',port=59767,access_log=False)
    finally:
        for process in reversed(processes):process.terminate()
        for process in reversed(processes):
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
if __name__=='__main__':main()
