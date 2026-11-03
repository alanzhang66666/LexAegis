"""Build/serve only the public read-only synthetic demo; no provider secrets."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse

import control

ROOT=control.ROOT
HERE=control.HERE
OUTPUT=control.OUTPUT
ENV=OUTPUT/'public-demo.env'
TAG='lexaegis:public-readonly-demo'


def compose(*args):
    return ['docker','compose','--env-file',str(ENV),'-f',str(HERE/'compose.public-demo.yaml'),*args]


def build():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory,(OUTPUT/'public-demo-build.log').open('wb') as log:
        context=Path(directory)
        control.build_context(context)
        shutil.copytree(ROOT/'frontend/dist',context/'frontend/dist')
        for name in ('public_demo.py','Dockerfile.demo'):
            shutil.copy2(HERE/name,context/'deploy/cloud_gateway'/name)
        result=subprocess.run(['docker','build','-f',str(context/'deploy/cloud_gateway/Dockerfile.demo'),'-t',TAG,str(context)],stdout=log,stderr=log)
        if result.returncode: raise RuntimeError('Public demo image build failed')
    image=control.command(['docker','image','inspect',TAG,'--format','{{.Id}}']).decode().strip()
    ENV.write_text('LEX_PUBLIC_DEMO_IMAGE='+image+'\n',encoding='utf-8')
    print('Public demo image built',flush=True)


def status():
    logs=control.command(compose('logs','--no-color','--tail','250','tunnel')).decode('utf-8',errors='replace')
    urls=re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com',logs)
    if not urls: return {'status':'starting','url':None}
    return {'status':'published','url':urls[-1],'access':'read_only','data_origin':'bundled_synthetic','real_cloud_calls':0}


def verify(url,resolve=None):
    hostname=urllib.parse.urlsplit(url).hostname
    original=socket.getaddrinfo
    if resolve:
        if not ipaddress.ip_address(resolve).is_global: raise ValueError('Resolver diagnostic requires a public address')
        def resolver(host,*args,**kwargs): return original(resolve if host==hostname else host,*args,**kwargs)
        socket.getaddrinfo=resolver
    try:
        return verify_requests(url,resolve)
    finally:
        socket.getaddrinfo=original


def verify_requests(url,resolve=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(url+path,timeout=15) as response: return response.status,response.read()
    status_code,html=get('/')
    _,boot=get('/api/v1/bootstrap')
    _,me=get('/api/v1/me')
    boot=json.loads(boot); me=json.loads(me)
    assert status_code==200 and b'<div id="root"' in html
    assert boot['runtime_profile']=='demo' and me['role']=='case_operator'
    _,metadata=get('/_public_demo_health')
    metadata=json.loads(metadata)
    for case in metadata['cases']:
        _,detail=get('/api/v1/cases/'+case['id'])
        task=next(t for t in json.loads(detail)['tasks'] if t['id']==case['task_id'])
        if case['scenario']=='success':
            assert task['status']=='complete' and task['artifact']['provenance']=='simulation'
            assert task['artifact']['claims'] and all(c['anchors'] for c in task['artifact']['claims'])
        else:
            assert task['risk']['blockers']
    request=urllib.request.Request(url+'/api/v1/demos',data=b'{"scenario":"success"}',headers={'Content-Type':'application/json'},method='POST')
    try:
        opener.open(request,timeout=10)
    except urllib.error.HTTPError as error:
        blocked=error.code==403
    else: blocked=False
    assert blocked
    report={'status':'passed','url':url,'html_status':status_code,'runtime_profile':'demo','viewer_role':me['role'],
            'mutations_blocked':blocked,'data_origin':'bundled_synthetic','real_cloud_calls':0,
            'completed_and_blocked_examples_verified':True,
            'diagnostic_dns_override':resolve,'tls_certificate_verification':True,'system_dns_modified':False}
    control.save('public-demo-verification.json',report)
    return report


def start(resolve=None):
    if not ENV.exists(): build()
    control.command(compose('up','-d'),timeout=180)
    for attempt in range(36):
        result=status()
        if result['url']:
            try:
                verify(result['url'],resolve)
                control.save('public-demo.json',result)
                print(result['url'],flush=True)
                return
            except (AssertionError,urllib.error.URLError,TimeoutError): pass
        time.sleep(2)
    control.save('public-demo.json',result)
    raise RuntimeError('Public tunnel not ready; inspect dedicated demo logs')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','start','status','stop','verify'])
    parser.add_argument('--resolve',help='Diagnostic address only; retains hostname/TLS verification, does not change OS DNS')
    args=parser.parse_args()
    if args.action=='build': build()
    elif args.action=='start': start(args.resolve)
    elif args.action=='status': print(json.dumps(status()))
    elif args.action=='stop': control.command(compose('stop')); print('Public demo stopped; data retained')
    else:
        result=status()
        print(json.dumps(verify(result['url'],args.resolve)))


if __name__=='__main__': main()
