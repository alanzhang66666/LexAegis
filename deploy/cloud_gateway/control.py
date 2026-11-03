"""Cloud-gateway-only deployment control. Never edits application code or .env."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = ROOT / '.data' / 'cloud-gateway'
TAG = 'lexaegis:cloud-gateway-candidate'


def command(args, *, data=None, timeout=60, allowed=(0,)):
    result = subprocess.run(args,input=data,capture_output=True,timeout=timeout)
    if result.returncode not in allowed:
        # Do not print arbitrary command stderr or secret provisioning input.
        raise RuntimeError('Cloud deployment command failed: ' + args[0])
    return result.stdout


def compose(envfile,*args):
    base=['docker','compose','--env-file',str(envfile),'-f',str(HERE/'compose.yaml')]
    if Path(envfile).name=='production.env': base+=['-f',str(HERE/'production.override.yaml')]
    return [*base,*args]


def save(name,report):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


def volume(name,profile):
    command(['docker','volume','create','--label','lexaegis.component=cloud-gateway','--label',
             'lexaegis.profile='+profile,name])
    info=json.loads(command(['docker','volume','inspect',name]))[0]
    if (info.get('Labels') or {}).get('lexaegis.component')!='cloud-gateway' or info['Labels'].get('lexaegis.profile')!=profile:
        raise ValueError('Existing Docker volume is outside this deployment')


INSTALL = '''import io,os,sys,tarfile
target=sys.argv[1]; purpose=sys.argv[2]; os.makedirs(target,exist_ok=True)
if purpose=='ledger' and os.path.exists(target+'/gateway.sqlite'):
    print('Existing gateway ledger retained'); sys.exit(0)
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as archive:
    for member in archive:
        if not member.isfile() or member.name not in {'gateway.env','gateway-secret','gateway.sqlite','.lexaegis-runtime.json'}:
            raise ValueError('Unexpected provisioning member')
        path=target+'/'+member.name
        with open(path+'.new','wb') as output: output.write(archive.extractfile(member).read())
        os.chmod(path+'.new',0o600); os.chown(path+'.new',10001,10001); os.replace(path+'.new',path)
os.chmod(target,0o700); os.chown(target,10001,10001)
'''


def install(image,volume_name,target,files,purpose):
    payload=io.BytesIO()
    with tarfile.open(fileobj=payload,mode='w') as archive:
        for name,contents in files.items():
            member=tarfile.TarInfo(name); member.size=len(contents); member.mode=0o600
            archive.addfile(member,io.BytesIO(contents))
    command(['docker','run','--rm','-i','--network','none','--read-only','--user','0:0','--cap-drop=ALL',
        '--cap-add=CHOWN','--cap-add=DAC_OVERRIDE','--cap-add=FOWNER','--security-opt=no-new-privileges',
        '--mount',f'type=volume,src={volume_name},dst=/provision','--entrypoint','python',image,
        '-c',INSTALL,target,purpose],data=payload.getvalue())


def build_context(destination):
    """Send only gateway build inputs to Docker; never the whole workspace."""
    destination=Path(destination)
    shutil.copytree(ROOT/'lexaegis',destination/'lexaegis',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env*'))
    shutil.copytree(ROOT/'packs',destination/'packs')
    shutil.copy2(ROOT/'requirements.lock',destination/'requirements.lock')
    deployment=destination/'deploy/cloud_gateway'
    deployment.mkdir(parents=True)
    for name in ('Dockerfile','cloud_runtime.py','provider_egress.py','tcp_ingress.py','route_guard.py','ds_gateway.py','shared_budget.py'):
        shutil.copy2(HERE/name,deployment/name)


def build():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, (OUTPUT/'build.log').open('wb') as log:
        context=Path(directory)
        build_context(context)
        result=subprocess.run(['docker','build','-f',str(context/'deploy/cloud_gateway/Dockerfile'),'-t',TAG,str(context)],stdout=log,stderr=log)
    if result.returncode:
        raise RuntimeError('Cloud image build failed; inspect the dedicated build log')
    image=command(['docker','image','inspect',TAG,'--format','{{.Id}}']).decode().strip()
    save('image.json',{'tag':TAG,'image_config_id':image,'oci_repository_digest':None,
         'scope':'cloud_gateway_only','application_source_modified':False})
    print('Cloud image built: '+image)


def init(profile,private_config,ledger_source,build_manifest=None):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    image=command(['docker','image','inspect',TAG,'--format','{{.Id}}']).decode().strip()
    config=Path(private_config).resolve()
    if ROOT==config or ROOT in config.parents:
        raise ValueError('Credentials must be outside the repository')
    if profile=='production':
        if config.name=='integration' or build_manifest is None:
            raise ValueError('Production requires separate credentials and the real verified build manifest')
        manifest=json.loads(Path(build_manifest).read_text(encoding='utf-8'))
        if manifest.get('status')!='verified':
            raise ValueError('Build manifest has not been verified by the existing release pipeline')
    files={name:(config/name).read_bytes() for name in ('gateway.env','gateway-secret')}
    for suffix in ('data','secrets'):
        volume(f'lexaegis-cloud-{profile}-{suffix}',profile)
    install(image,f'lexaegis-cloud-{profile}-secrets','/provision',files,'secrets')
    imported=False
    if ledger_source:
        source=Path(ledger_source).resolve()
        if profile!='integration' or source.name!='gateway.sqlite':
            raise ValueError('This importer accepts only an integration gateway ledger')
        marker=json.loads((source.parent/'.lexaegis-runtime.json').read_text(encoding='utf-8'))
        if marker!={'version':1,'runtime_profile':profile,'role':'gateway'}:
            raise ValueError('Gateway ledger profile binding mismatch')
        with tempfile.TemporaryDirectory() as directory:
            snapshot=Path(directory)/'gateway.sqlite'
            with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
                if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Ledger integrity failure')
                kinds={row[0] for row in src.execute('SELECT DISTINCT kind FROM records')}
                if kinds-{'send','integration_quota','deployment_quota','deployment_reservation'}:
                    raise ValueError('Import source contains non-gateway records')
                src.backup(dst)
            install(image,f'lexaegis-cloud-{profile}-data','/provision/gateway',
                    {'gateway.sqlite':snapshot.read_bytes(),'.lexaegis-runtime.json':json.dumps(marker).encode()},'ledger')
        imported=True
    port=58766 if profile=='integration' else 8766
    envfile=OUTPUT/f'{profile}.env'
    # Only non-secret image/profile references enter this env file.
    envfile.write_text(f'LEX_PROFILE={profile}\nLEX_CLOUD_IMAGE={image}\nLEX_CLOUD_PORT={port}\nLEX_INITIAL_CONSUMED=0\n',encoding='utf-8')
    if build_manifest:
        with envfile.open('a',encoding='utf-8') as output:
            output.write('LEX_BUILD_MANIFEST_PATH='+str(Path(build_manifest).resolve()).replace('\\','/')+'\n')
    command(compose(envfile,'config','--quiet'))
    save('setup.json',{'profile':profile,'private_config':str(config),'image_config_id':image,
        'ledger_import_requested':imported,'plaintext_credentials_in_image_or_env':False,'application_source_modified':False})
    print('Cloud configuration initialized; application configuration unchanged')


def health(envfile):
    code="from pathlib import Path; import urllib.request,json; from lexaegis.util import sign; s=Path('/run/private/gateway-secret').read_text().strip(); base='http://127.0.0.1:8766'; h={'X-Gateway-Signature':sign({'op':'health'},s)}; print(json.dumps({p:json.load(urllib.request.urlopen(urllib.request.Request(base+p,headers=h),timeout=5)) for p in ('/health','/deployment/status')}))"
    return json.loads(command(compose(envfile,'exec','-T','gateway','python','-c',code)))


def verify(envfile):
    config=json.loads(command(compose(envfile,'config','--format','json')))
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'local_container_cloud_gateway_not_cross_host_acceptance',
            'health':health(envfile),'checks':[],'application_source_modified':False,'formal_dispatch':'blocked'}
    for role in ('gateway','provider-egress','gateway-ingress'):
        ident=command(compose(envfile,'ps','-q',role)).decode().strip()
        inspected=json.loads(command(['docker','inspect',ident]))[0]
        names={entry.split('=',1)[0] for entry in inspected['Config'].get('Env',[])}
        destinations=[m['Destination'] for m in inspected.get('Mounts',[])]
        report['checks'].append({'name':role+':credential_boundary','passed':
            not {'LEX_CLOUD_PRIMARY_KEY','LEX_CLOUD_API_KEY','LEX_CLOUD_STANDBY_KEY'} & names
            and ('/run/private' in destinations)==(role=='gateway')})
        report['checks'].append({'name':role+':restricted_process','passed':inspected['HostConfig']['ReadonlyRootfs']
            and inspected['Config']['User']=='10001:10001' and 'ALL' in inspected['HostConfig']['CapDrop']})
        report[role+'_image_config_id']=inspected['Image']
        if role=='gateway-ingress':
            bindings=[b for values in inspected['NetworkSettings'].get('Ports',{}).values() for b in (values or [])]
            report['checks'].append({'name':'published_only_on_loopback','passed':bool(bindings) and
                                    all(b['HostIp'] in {'127.0.0.1','::1'} for b in bindings)})
    guard_id=command(compose(envfile,'ps','-q','isolate-ingress-route')).decode().strip()
    guard=json.loads(command(['docker','inspect',guard_id]))[0]
    report['checks'].append({'name':'route_guard_minimal_privilege','passed':guard['Config']['User']=='0:0'
        and set(guard['HostConfig']['CapAdd'] or [])=={'NET_ADMIN'} and 'ALL' in guard['HostConfig']['CapDrop']})
    report['checks'].append({'name':'route_guard_has_no_secrets_or_ledger','passed':not any(
        m['Destination'] in {'/data','/run/private'} for m in guard.get('Mounts',[]))})
    probe="import json,socket; result=[]\nfor host in ('1.1.1.1','2606:4700:4700::1111','api.deepseek.com','example.com'):\n try:\n  s=socket.create_connection((host,443),2); s.close(); connected=True\n except OSError: connected=False\n result.append({'name':'gateway_direct:'+host,'passed':not connected})\nprint(json.dumps(result))"
    for role in ('gateway','gateway-ingress'):
        role_probe=probe.replace('gateway_direct:',role+'_direct:')
        report['checks']+=json.loads(command(compose(envfile,'exec','-T',role,'python','-c',role_probe),timeout=20))
    deny="import socket,json; s=socket.create_connection(('provider-egress',3128),3); s.sendall(b'CONNECT example.com:443 HTTP/1.1\\r\\n\\r\\n'); print(json.dumps({'name':'proxy_rejects_other_host','passed':s.recv(256).startswith(b'HTTP/1.1 403')})); s.close()"
    report['checks'].append(json.loads(command(compose(envfile,'exec','-T','gateway','python','-c',deny))))
    model_probe="from dotenv import dotenv_values; import httpx,json; k=dotenv_values('/run/private/gateway.env',interpolate=False)['LEX_CLOUD_PRIMARY_KEY']; c=httpx.Client(proxy='http://provider-egress:3128',trust_env=False,follow_redirects=False,timeout=15); r=c.get('https://api.deepseek.com/v1/models',headers={'Authorization':'Bearer '+k}); print(json.dumps({'status_code':r.status_code,'models':[v['id'] for v in r.json().get('data',[])][:30] if r.status_code==200 else []})); c.close()"
    try:
        provider=json.loads(command(compose(envfile,'exec','-T','gateway','python','-c',model_probe),timeout=25))
        report['provider_readonly_models_probe']=provider
        report['checks'].append({'name':'provider_tls_and_credential_readonly','passed':provider['status_code']==200})
    except RuntimeError:
        report['checks'].append({'name':'provider_tls_and_credential_readonly','passed':False})
    port=next(line.split('=',1)[1] for line in Path(envfile).read_text(encoding='utf-8').splitlines() if line.startswith('LEX_CLOUD_PORT='))
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        response=opener.open('http://127.0.0.1:'+port+'/health',timeout=3)
        host_status=response.status
        response.close()
    except urllib.error.HTTPError as error:
        host_status=error.code
    except urllib.error.URLError:
        host_status=None
    report['checks'].append({'name':'host_loopback_unsigned_rejected','passed':host_status==403,'status_code':host_status})
    report['status']='passed' if all(check['passed'] for check in report['checks']) else 'failed'
    save('verification.json',report)
    print(json.dumps({'status':report['status'],'checks':len(report['checks']),'quota':report['health']['/deployment/status']['quota']}))
    return report


def backup(envfile):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    code="import sqlite3,sys,tempfile; from pathlib import Path; t=tempfile.NamedTemporaryFile(suffix='.sqlite',delete=False); t.close(); src=sqlite3.connect('/data/gateway/gateway.sqlite'); dst=sqlite3.connect(t.name); src.backup(dst); dst.close(); src.close(); sys.stdout.buffer.write(Path(t.name).read_bytes()); Path(t.name).unlink()"
    payload=command(compose(envfile,'exec','-T','gateway','python','-c',code))
    destination=OUTPUT/('gateway-ledger-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sqlite')
    destination.write_bytes(payload)
    destination.chmod(0o600)
    save('backup.json',{'scope':'gateway_ledger_only_no_originals_no_credentials','path':str(destination),
                       'sha256':hashlib.sha256(payload).hexdigest()})
    print('Gateway ledger backup saved')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','init','start','stop','status','verify','backup'])
    parser.add_argument('--profile',choices=['integration','production'],default='integration')
    parser.add_argument('--private-config',type=Path)
    parser.add_argument('--ledger-source',type=Path)
    parser.add_argument('--build-manifest',type=Path)
    args=parser.parse_args()
    envfile=OUTPUT/f'{args.profile}.env'
    if args.action=='build': build()
    elif args.action=='init':
        private=args.private_config or Path(os.environ.get('LOCALAPPDATA',Path.home()/'.config'))/'LexAegis'/args.profile
        init(args.profile,private,args.ledger_source,args.build_manifest)
    elif args.action=='start':
        command(compose(envfile,'config','--quiet'))
        command(compose(envfile,'up','-d'))
        # Refresh the namespace-coupled guard whenever ingress is recreated.
        command(compose(envfile,'up','-d','--force-recreate','gateway-ingress','isolate-ingress-route'))
        for attempt in range(45):
            try:
                health(envfile)
                break
            except RuntimeError:
                time.sleep(.5)
        else:
            raise RuntimeError('Gateway did not become ready')
        print('Cloud gateway ready')
    elif args.action=='stop':
        command(compose(envfile,'stop'))
        print('Cloud gateway stopped; volumes retained')
    elif args.action=='status': print(json.dumps(health(envfile)))
    elif args.action=='verify':
        if verify(envfile)['status']!='passed': raise SystemExit(1)
    elif args.action=='backup': backup(envfile)


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('Cloud deployment failed ('+type(error).__name__+'); no secret values displayed',file=sys.stderr)
        raise SystemExit(1)
