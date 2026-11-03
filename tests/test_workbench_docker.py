"""Explicit opt-in isolated Docker smoke; no vendor or existing deployment used."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

pytestmark=pytest.mark.skipif(os.getenv('LEX_RUN_WORKBENCH_DOCKER_TESTS')!='1',reason='Explicit isolated Docker smoke opt-in required')
SOURCE=Path(__file__).resolve().parents[1]

def controller():
    spec=importlib.util.spec_from_file_location('docker_workbench_control',SOURCE/'deploy/workbench_demo/control.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_isolated_stack_and_origin_updates_preserve_tunnel(tmp_path):
    module=controller();root=Path(os.environ['LEX_DEMO_TEST_RUNTIME_ROOT']).resolve();c=module.config(root)
    assert not c['cloud_enabled'] and not c['public']
    module.provision(root)
    config=module.composition(c)
    module.save(root/'compose.json',config)
    script=(SOURCE/'tests/workbench_model_stub.py').read_text(encoding='utf-8')
    edge=config['services']['edge-model'];edge.update(command=['python','-c',script],networks=['edge-private'],volumes=[])
    tunnel=config['services']['tunnel'];tunnel.update(image=c['image'],user='10001:10001',
        command=['python','-m','http.server','20241'],networks=['tunnel-link'])
    smoke=root/'smoke-compose.json';module.save(smoke,config)
    cmd=lambda *args:['docker','compose','-f',str(smoke),*args]
    def run(*args):return module.run(cmd(*args),timeout=150)
    try:
        run('up','-d','gateway','provider-egress','edge-model','workbench','public-origin','local-ingress','local-ingress-guard','tunnel')
        for _ in range(90):
            info=module.inspect_owned(root,'workbench')
            if info and info['State'].get('Health',{}).get('Status')=='healthy':break
            time.sleep(.5)
        else:raise AssertionError('Synthetic workbench did not become healthy')
        # The ingress cannot listen before its namespace route receipt is ready.
        import httpx
        for _ in range(60):
            try:
                if httpx.get('http://127.0.0.1:'+str(c['port']),trust_env=False,timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.5)
        else:raise AssertionError('Guarded loopback ingress is not reachable')
        gateway_probe="""import json,urllib.request
from pathlib import Path
from lexaegis.util import sign
secret=Path('/run/signing/gateway-secret').read_text().strip()
request=urllib.request.Request('http://gateway:8766/health',headers={'X-Gateway-Signature':sign({'op':'health'},secret)})
print(urllib.request.urlopen(request,timeout=4).read().decode())
"""
        assert json.loads(run('exec','-T','workbench','python','-c',gateway_probe))['gateway_role']=='edge'
        raw=run('exec','-T','workbench','python','-c',"from pathlib import Path; print(Path('/data/workbench/integration/config/accounts.json').read_text())")
        (root/'private/accounts.json').write_bytes(raw)
        env={**os.environ,'LEX_REGISTERED_E2E_URL':'http://127.0.0.1:'+str(c['port']),
            'LEX_REGISTERED_E2E_ACCOUNTS':str(root/'private/accounts.json'),
            'LEX_REGISTERED_E2E_DOCUMENT':str(SOURCE/'.artifacts/migration/public-synthetic.docx')}
        # Packaged Windows hosts can virtualize the Playwright cache between
        # parent and child processes. Prefer the installed browser in that case.
        if os.name=='nt' and 'LEX_CHROME' not in env:
            edge=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
            if edge.exists():env['LEX_CHROME']=str(edge)
        with (SOURCE/'.artifacts/migration/browser-registered.log').open('wb') as log:
            result=subprocess.run(['pnpm.cmd' if os.name=='nt' else 'pnpm','exec','playwright','test','--config=playwright.registered.config.ts'],
                cwd=SOURCE/'frontend',env=env,stdout=log,stderr=log)
        assert result.returncode==0,'Registered document browser test failed; inspect private browser-registered.log'
        before=module.inspect_owned(root,'tunnel')
        module.start_tunnel(root)
        run('up','-d','--no-deps','--force-recreate','workbench','public-origin')
        after=module.inspect_owned(root,'tunnel')
        assert before['Id']==after['Id'] and before['State']['StartedAt']==after['State']['StartedAt']
        for service in ('workbench','gateway','local-ingress'):
            probe="""import json,socket
r={}
for name,family,address in [('ipv4',socket.AF_INET,('1.1.1.1',443)),('ipv6',socket.AF_INET6,('2606:4700:4700::1111',443,0,0))]:
 s=socket.socket(family);s.settimeout(2)
 try:s.connect(address);r[name]='reachable'
 except OSError:r[name]='blocked'
 finally:s.close()
print(json.dumps(r))
"""
            value=json.loads(run('exec','-T',service,'python','-c',probe))
            assert value=={'ipv4':'blocked','ipv6':'blocked'}
        module.save(SOURCE/'.artifacts/migration/docker-smoke.json',{'passed':True,'vendor_tunnel_started':False,
            'edge':'synthetic HTTP stub','new_vendor_generation_posts':0,'tunnel_session_preserved':True,
            'project':c['project'],'image':c['image']})
    finally:
        # Only this validated project; external persistent volumes are retained.
        run('down','--remove-orphans')
