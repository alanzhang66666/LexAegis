"""Portable, opt-in integration deployment; never manages another installation."""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

SOURCE=Path(__file__).resolve().parents[2]
CF_IMAGE='cloudflare/cloudflared:2026.10.7@sha256:4955524aeaa379e154023d5a027c250f7b35041a2e7e950cf13f144bc9b9c5ba'
LABEL='lexaegis.workbench-demo'

def run(args,timeout=180,**kwargs):
    result=subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,**kwargs)
    if result.returncode:raise RuntimeError('Deployment command failed: '+str(args[0])+' (exit '+str(result.returncode)+')')
    return result.stdout

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def private_directory(path):
    path.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        sid=run(['powershell','-NoProfile','-Command','[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value']).decode().strip()
        run(['icacls',path,'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F'])
    else:path.chmod(0o700)

def config(root):
    value=json.loads((root/'deployment.json').read_text(encoding='utf-8'))
    expected='lexaegis-demo-'+hashlib.sha256(str(root).encode()).hexdigest()[:12]
    if value['project']!=expected:raise ValueError('Deployment identity does not belong to this runtime directory')
    return value

def composition(c):
    default={'image':c['image'],'pull_policy':'never','user':'10001:10001','read_only':True,
        'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'tmpfs':['/tmp'],'restart':'unless-stopped',
        'logging':{'driver':'json-file','options':{'max-size':'10m','max-file':'3'}}}
    def service(**kwargs):return {**default,**kwargs}
    health=lambda port,path:{'test':['CMD','python','-c',f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}{path}',timeout=3)"],
        'interval':'5s','timeout':'4s','retries':25,'start_period':'30s'}
    registration={}
    if c.get('manifest_sha256'):
        registration={'LEX_REGISTERED_DEMO_MANIFEST':'/run/registration/registered-manifest.json',
            'LEX_REGISTERED_DEMO_MANIFEST_SHA256':c['manifest_sha256']}
    cmd=lambda module,port:['python','-m','uvicorn',module,'--host','0.0.0.0','--port',str(port),'--no-access-log']
    return {'name':c['project'],'services':{
        'workbench':service(networks={'edge-private':None,'public-origin':{'aliases':['chain-origin']}},
            volumes=['app-data:/data','signing:/run/signing:ro','registration:/run/registration:ro'],
            environment=registration,
            healthcheck=health(59767,'/_public_demo_health'),
            depends_on={'gateway':{'condition':'service_started'},'edge-model':{'condition':'service_healthy' if c.get('model_assets') else 'service_started'}}),
        'gateway':service(command=cmd('ds_gateway:create_app',8766)[:4]+['--factory']+cmd('ds_gateway:create_app',8766)[4:],
            networks=['edge-private','cloud-private'],volumes=['gateway-data:/data','private:/run/private:ro','budget:/quota','registration:/run/registration:ro'],
            environment={**registration,'LEX_RUN_PROFILE':'integration','LEX_RUNTIME_ROLE':'gateway','LEX_GATEWAY_ROLE':'cloud' if c['cloud_enabled'] else 'edge',
                'LEX_GATEWAY_DIR':'/data/gateway','LEX_CLOUD_ALLOWED_HOSTS':'api.deepseek.com','LEX_INITIAL_CONSUMED':'0'}),
        'provider-egress':service(command=['python','/opt/cloud_gateway/provider_egress.py'],networks=['cloud-private','provider-uplink']),
        'edge-model':service(command=cmd('edge_connector:app',8080),networks=['edge-private','model-host-uplink'],
            environment={'LEX_MODEL_HOST_IP':c['model_host_ip'],'LEX_MODEL_CONFIGURED':'1' if c.get('model_assets') else '0'},volumes=['route-guard:/run/route-guard:ro'],healthcheck=health(8080,'/health')),
        'model-guard':service(command=['python','/opt/deployment/model_route_guard.py'],user='0:0',cap_add=['NET_ADMIN'],
            network_mode='service:edge-model',environment={'LEX_MODEL_HOST_IP':c['model_host_ip']},volumes=['route-guard:/run/route-guard']),
        'public-origin':service(command=cmd('public_proxy:app',59767),networks=['public-origin','tunnel-link'],
            environment={'LEX_PUBLIC_CHAIN_ORIGIN':'http://chain-origin:59767'}),
        'local-ingress':service(command=['python','/opt/deployment/local_ingress.py'],networks=['tunnel-link','host-publish'],
            ports=['127.0.0.1:'+str(c['port'])+':59767'],volumes=['ingress-guard:/run/route-guard:ro']),
        'local-ingress-guard':service(command=['python','/opt/cloud_gateway/route_guard.py'],user='0:0',cap_add=['NET_ADMIN'],
            network_mode='service:local-ingress',volumes=['ingress-guard:/run/route-guard']),
        'tunnel':service(image=CF_IMAGE,user='65532:65532',networks=['tunnel-link','tunnel-uplink'],
            command=['tunnel','--no-autoupdate','--protocol','http2','--edge-ip-version','4','--url','http://public-origin:59767'],depends_on=['public-origin'])},
        'networks':{**{n:{'internal':True} for n in ('edge-private','cloud-private','public-origin','tunnel-link')},
            **{n:{} for n in ('provider-uplink','model-host-uplink','tunnel-uplink')},
            'host-publish':{'driver_opts':{'com.docker.network.bridge.enable_ip_masquerade':'false'}}},
        'volumes':{n:{'external':True,'name':c['project']+'-'+n} for n in ('app-data','gateway-data','signing','private','registration','budget','route-guard','ingress-guard')}}

def init(root,args):
    if (root/'deployment.json').exists():
        config(root);print('Existing deployment retained; no credentials, policy or ledger changed');return
    if root.exists() and any(root.iterdir()):raise ValueError('Choose an empty private runtime directory')
    address=ipaddress.ip_address(args.model_host_ip)
    if not isinstance(address,ipaddress.IPv4Address) or not address.is_private:raise ValueError('Model host must be a private IPv4 address')
    if not 0<=args.initial_consumed<=args.cloud_limit<=1000:raise ValueError('Invalid explicitly configured allowance')
    if not 1024<=args.port<=65535:raise ValueError('Invalid loopback port')
    private_directory(root);private=root/'private';private_directory(private)
    secret=secrets.token_urlsafe(48)
    for name,value in [('gateway-secret',secret),('gateway.env','LEX_CLOUD_PRIMARY_KEY=\nLEX_KEY_USE_CONFIRMED=0\n')]:
        file=private/name;file.write_text(value,encoding='utf-8');file.chmod(0o600)
    save(private/'global-policy.json',{'initial_reserved':args.initial_consumed,'lifetime_limit':args.cloud_limit})
    (private/'global-policy.json').chmod(0o600)
    manifest_hash=None
    if args.manifest:
        source=Path(args.manifest).resolve();raw=source.read_bytes();registration=private/'registered-manifest.json';registration.write_bytes(raw);registration.chmod(0o600)
        manifest_hash=hashlib.sha256(raw).hexdigest()
        # Validate in a disposable subprocess; do not contaminate another app's registry.
        env={**os.environ,'LEX_RUN_PROFILE':'integration','LEX_REGISTERED_DEMO_MANIFEST':str(registration),
            'LEX_REGISTERED_DEMO_MANIFEST_SHA256':manifest_hash}
        run([sys.executable,'-c','from lexaegis.registered_demo import register; register()'],env=env)
    project='lexaegis-demo-'+hashlib.sha256(str(root).encode()).hexdigest()[:12]
    c={'project':project,'image':project+':source','port':args.port,'public':args.public,'cloud_enabled':args.cloud_limit>0,
        'model_host_ip':args.model_host_ip,'model_assets':str(Path(args.model_assets).resolve()) if args.model_assets else None,
        'manifest_sha256':manifest_hash,'created_at':datetime.now(timezone.utc).isoformat()}
    save(root/'deployment.json',c);save(root/'compose.json',composition(c))
    print('Private deployment initialized; cloud allowance is '+str(args.cloud_limit)+'. Provider credentials were not printed.')

def build(root):
    c=config(root)
    if not (SOURCE/'frontend/dist/index.html').exists():raise ValueError('Build the frontend before building this image')
    with tempfile.TemporaryDirectory(prefix='lexaegis-public-build-') as temp:
        target=Path(temp)
        for directory in ('lexaegis','packs','frontend/dist'):
            shutil.copytree(SOURCE/directory,target/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env*'))
        shutil.copy2(SOURCE/'requirements.lock',target/'requirements.lock')
        for directory,names in [('deploy/workbench_demo',('Dockerfile','workbench.py','public_proxy.py','poll_events.js','edge_connector.py','model_route_guard.py','local_ingress.py')),
                ('deploy/cloud_gateway',('cloud_runtime.py','ds_gateway.py','shared_budget.py','provider_egress.py','route_guard.py'))]:
            (target/directory).mkdir(parents=True,exist_ok=True)
            for name in names:shutil.copy2(SOURCE/directory/name,target/directory/name)
        with (root/'build.log').open('wb') as log:
            result=subprocess.run(['docker','build','-f',str(target/'deploy/workbench_demo/Dockerfile'),'-t',c['image'],str(target)],stdout=log,stderr=log)
            if result.returncode:raise RuntimeError('Image build failed; inspect the private build.log')
    image=run(['docker','image','inspect',c['image'],'--format','{{.Id}}']).decode().strip()
    save(root/'build-identity.json',{'image_config_id':image,'source_commit':run(['git','-C',SOURCE,'rev-parse','HEAD']).decode().strip(),
        'formal_release_identity':'pending','built_at':datetime.now(timezone.utc).isoformat()})
    print('Source image built: '+image)

def compose(root,*args):return ['docker','compose','-f',root/'compose.json',*args]

def inspect_owned(root,service):
    c=config(root);ids=run(compose(root,'ps','-aq',service)).decode().split()
    if not ids:return None
    info=json.loads(run(['docker','inspect',ids[0]]))[0]
    labels=info['Config'].get('Labels') or {}
    if labels.get('com.docker.compose.project')!=c['project'] or labels.get('com.docker.compose.service')!=service:
        raise ValueError('Container belongs to another deployment')
    return info

def provision(root):
    c=config(root)
    from dotenv import dotenv_values
    values=dotenv_values(root/'private/gateway.env',interpolate=False)
    key=(values.get('LEX_CLOUD_PRIMARY_KEY') or '').strip()
    policy=json.loads((root/'private/global-policy.json').read_text(encoding='utf-8'))
    if bool(policy['lifetime_limit'])!=c['cloud_enabled']:raise ValueError('Allowance does not match the initialized mode')
    if c['cloud_enabled'] and (len(key)<20 or not any(values.get(name)=='1' for name in ('LEX_KEY_USE_CONFIRMED','LEX_KEY_ROTATION_CONFIRMED'))):
        raise ValueError('Configure and confirm the provider credential in the private file before provisioning')
    if not c['cloud_enabled'] and key:raise ValueError('Zero-budget edge mode must remain keyless')
    for volume in composition(c)['volumes'].values():
        name=volume['name'];run(['docker','volume','create','--label',LABEL+'='+c['project'],name])
        labels=json.loads(run(['docker','volume','inspect',name]))[0].get('Labels') or {}
        if labels.get(LABEL)!=c['project']:raise ValueError('Volume belongs to another deployment')
    for name,members in [('private',('gateway.env','gateway-secret','global-policy.json')),('signing',('gateway-secret',)),
                         ('registration',('registered-manifest.json',) if c['manifest_sha256'] else ())]:
        payload=io.BytesIO()
        with tarfile.open(fileobj=payload,mode='w') as archive:
            for member in members:
                raw=(root/'private'/member).read_bytes();entry=tarfile.TarInfo(member);entry.size=len(raw);entry.mode=0o600
                archive.addfile(entry,io.BytesIO(raw))
        installer="""import io,os,sys,tarfile
from pathlib import Path
target=Path('/provision')
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as archive:
 for entry in archive:
  if entry.name not in {'gateway.env','gateway-secret','global-policy.json','registered-manifest.json'} or not entry.isfile():raise ValueError('Unexpected provision member')
  file=target/entry.name;raw=archive.extractfile(entry).read()
  if file.exists():
   if file.read_bytes()!=raw:raise ValueError('Existing private configuration differs; reconcile explicitly')
  else:file.write_bytes(raw)
  file.chmod(0o600);os.chown(file,10001,10001)
target.chmod(0o700);os.chown(target,10001,10001)
"""
        run(['docker','run','--rm','-i','--network','none','--read-only','--user','0:0','--cap-drop=ALL','--cap-add=CHOWN',
            '--cap-add=DAC_OVERRIDE','--cap-add=FOWNER','--security-opt=no-new-privileges',
            '--mount','type=volume,src='+c['project']+'-'+name+',dst=/provision','--entrypoint','python',c['image'],'-c',installer],input=payload.getvalue())

def start_tunnel(root):
    info=inspect_owned(root,'tunnel')
    if info is None:run(compose(root,'up','-d','--no-deps','tunnel'))
    elif not info['State']['Running']:run(['docker','start',info['Id']])

def start(root):
    c=config(root);save(root/'compose.json',composition(c));provision(root)
    if c.get('model_assets'):
        run([sys.executable,Path(__file__).with_name('edge_service.py'),'start'],env={**os.environ,
            'LEX_MODEL_ASSETS':c['model_assets'],'LEX_DEMO_RUNTIME_ROOT':str(root)})
    run(compose(root,'up','-d','gateway','provider-egress','edge-model','model-guard','workbench','public-origin','local-ingress','local-ingress-guard'))
    for _ in range(90):
        info=inspect_owned(root,'workbench')
        if info and info['State'].get('Health',{}).get('Status')=='healthy':break
        time.sleep(.5)
    else:raise RuntimeError('Workbench health timed out; inspect only this deployment logs')
    if c['public']:start_tunnel(root)
    raw=run(compose(root,'exec','-T','workbench','python','-c',"from pathlib import Path; print(Path('/data/workbench/integration/config/accounts.json').read_text())"))
    (root/'private/accounts.json').write_bytes(raw);(root/'private/accounts.json').chmod(0o600)
    status(root)

def status(root):
    c=config(root);states={}
    for service in ('workbench','gateway','provider-egress','edge-model','model-guard','public-origin','local-ingress','local-ingress-guard','tunnel'):
        info=inspect_owned(root,service)
        states[service]={'running':bool(info and info['State']['Running']),
            'id':info['Id'] if info else None,'started_at':info['State']['StartedAt'] if info else None}
    result={'project':c['project'],'scope':'integration_synthetic_only','local_url':'http://127.0.0.1:'+str(c['port']),
        'containers':states,'formal_dispatch':'blocked','isolation_acceptance':'not_verified','release_identity':'pending'}
    if states['tunnel']['running']:
        info=inspect_owned(root,'tunnel')
        # Read the current process metrics rather than trust old startup logs.
        raw=run(compose(root,'exec','-T','public-origin','python','-c',
            "import urllib.request; print(urllib.request.urlopen('http://tunnel:20241/quicktunnel',timeout=3).read().decode())"))
        import re
        host=json.loads(raw)['hostname'].removeprefix('https://')
        if not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com',host):raise ValueError('Unexpected quick-tunnel hostname')
        result['observed_public_url']='https://'+host
        from public_access import https_probe
        probe=https_probe(result['observed_public_url'],'interactive-integration');result['public_probe']=probe
        result['public_url']=result['observed_public_url'] if probe['reachable'] else None
    save(root/'status.json',result);print(json.dumps(result));return result

def stop(root):
    run(compose(root,'stop'))
    c=config(root)
    if c.get('model_assets'):
        run([sys.executable,Path(__file__).with_name('edge_service.py'),'stop'],env={**os.environ,'LEX_DEMO_RUNTIME_ROOT':str(root)})
    print('Owned deployment stopped; all volumes and ledgers retained')

def verify(root):
    c=config(root)
    code="""import json,urllib.request
from pathlib import Path
from lexaegis.util import sign
secret=Path('/run/private/gateway-secret').read_text().strip()
request=urllib.request.Request('http://127.0.0.1:8766/deployment/status',headers={'X-Gateway-Signature':sign({'op':'health'},secret)})
print(urllib.request.urlopen(request,timeout=4).read().decode())
"""
    gateway=json.loads(run(compose(root,'exec','-T','gateway','python','-c',code)))
    save(root/'gateway-status.json',gateway)
    status(root);print(json.dumps({'gateway_quota':gateway['quota'],'generation_posts':0}))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','build','start','stop','status','verify','repair'])
    parser.add_argument('--runtime-root',type=Path,default=SOURCE/'.data/workbench-demo')
    parser.add_argument('--manifest');parser.add_argument('--model-assets');parser.add_argument('--public',action='store_true')
    parser.add_argument('--port',type=int,default=58765);parser.add_argument('--model-host-ip',default='192.168.65.254')
    parser.add_argument('--cloud-limit',type=int,default=0);parser.add_argument('--initial-consumed',type=int,default=0)
    args=parser.parse_args(argv);root=args.runtime_root.resolve()
    if args.action=='init':init(root,args);return
    config(root)
    if args.action=='repair':
        c=config(root)
        if not c['public']:raise ValueError('This deployment was not configured for a public tunnel')
        current=status(root)
        if current.get('public_url'):return
        info=inspect_owned(root,'tunnel')
        if info and info['State']['Running']:run(['docker','restart','--time','5',info['Id']])
        else:start_tunnel(root)
        print('Tunnel repair may change its temporary URL; run status after registration');return
    globals()[args.action](root)

if __name__=='__main__':
    try:main()
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError,KeyError) as error:
        print('Deployment failed ('+type(error).__name__+'); credentials suppressed',file=sys.stderr);raise SystemExit(1)
