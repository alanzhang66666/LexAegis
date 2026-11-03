"""Transparent public transport for the original workbench, with browser sessions."""
import ipaddress
import json
import os
from http.cookies import SimpleCookie
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from starlette.responses import Response, JSONResponse

API='http://127.0.0.1:59765'
ROOT=Path('/data/workbench')/os.getenv('LEX_PUBLIC_PROFILE','integration')
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
CHAIN_ORIGIN=os.environ.get('LEX_PUBLIC_CHAIN_ORIGIN','')
if CHAIN_ORIGIN not in ('','http://chain-origin:59767'):
    raise RuntimeError('Unapproved public chain origin')


def same_origin(host,origin):
    if not origin: return True  # Original API also accepts authenticated non-browser clients.
    try:
        target=urlsplit('//'+host)
        source=urlsplit(origin)
        if source.username or source.password or source.query or source.fragment or source.path not in ('','/'):
            return False
        scheme='http' if target.hostname in {'127.0.0.1','localhost','demo','testserver'} else 'https'
        port=target.port or (443 if scheme=='https' else 80)
        return source.scheme==scheme and source.hostname==target.hostname and (source.port or (443 if scheme=='https' else 80))==port
    except ValueError:
        return False


def session_cookie(raw):
    jar=SimpleCookie()
    try: jar.load(raw)
    except Exception: return ''
    value=jar.get('lex_session')
    if value and re.fullmatch(r'[A-Za-z0-9_-]{10,200}',value.value):
        return 'lex_session='+value.value
    return ''


async def forward_chain(request):
    """Fixed internal origin; keep browser identity and approved body bytes."""
    route=request.url.path
    if request.method not in ('GET','HEAD') and not same_origin(request.headers.get('host',''),request.headers.get('origin')):
        return JSONResponse({'detail':'不允许跨站请求'},403)
    if not route.startswith('/') or route.startswith('//') or len(route)>8192:
        return JSONResponse({'detail':'Invalid request path'},400)
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>32*1024*1024:return JSONResponse({'detail':'请求超过 32 MiB'},413)
    headers={name:request.headers[name] for name in
        ('host','origin','content-type','accept','range','if-none-match','if-modified-since') if name in request.headers}
    cookie=session_cookie(request.headers.get('cookie',''))
    if cookie:headers['Cookie']=cookie
    address=request.headers.get('cf-connecting-ip')
    if address:
        try:headers['CF-Connecting-IP']=str(ipaddress.ip_address(address))
        except ValueError:pass
    target=CHAIN_ORIGIN+route+('?' + request.url.query if request.url.query else '')
    try:
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=120) as client:
            upstream=await client.request(request.method,target,content=bytes(content),headers=headers)
    except httpx.HTTPError:
        return JSONResponse({'detail':'完整演示工作台暂时不可用，请先启动 chain'},503)
    response=Response(upstream.content,status_code=upstream.status_code)
    for name in ('content-type','content-disposition','content-security-policy','content-range','accept-ranges',
                 'etag','last-modified','x-lexaegis-deployment'):
        if name in upstream.headers:response.headers[name]=upstream.headers[name]
    location=upstream.headers.get('location')
    if location:response.headers['Location']=location[len(CHAIN_ORIGIN):] if location.startswith(CHAIN_ORIGIN+'/') else location
    for value in upstream.headers.get_list('set-cookie'):
        if value.startswith('lex_session='):
            if urlsplit('//'+request.headers.get('host','')).hostname not in {'127.0.0.1','localhost'} and not re.search(r'(?:^|;)\s*secure(?:;|$)',value,re.I):value+='; Secure'
            response.raw_headers.append((b'set-cookie',value.encode('latin-1')))
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response


@app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
async def forward(request: Request,path: str):
    if CHAIN_ORIGIN:return await forward_chain(request)
    route=request.url.path
    if route=='/_public_demo_health' and request.method in ('GET','HEAD'):
        try: metadata=json.loads((ROOT/'ready.json').read_text())
        except (OSError,ValueError): return JSONResponse({'status':'starting'},503)
        return JSONResponse(metadata)
    if route=='/_workbench_transport.js' and request.method in ('GET','HEAD'):
        return Response(Path(__file__).with_name('poll_events.js').read_bytes(),media_type='application/javascript',headers={'Cache-Control':'no-store'})
    if request.method not in ('GET','HEAD') and not same_origin(request.headers.get('host',''),request.headers.get('origin')):
        return JSONResponse({'detail':'不允许跨站请求'},403)
    if not route.startswith('/') or route.startswith('//') or len(route)>8192:
        return JSONResponse({'detail':'Invalid request path'},400)
    if route.endswith('/events') and route.startswith('/api/v1/cases/'):
        # Cloudflare Quick Tunnel has no SSE. The head script supplies equivalent
        # case-change notifications via authenticated polling, without UI changes.
        return Response(status_code=204)
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>32*1024*1024: return JSONResponse({'detail':'请求超过 32 MiB'},413)
    headers={}
    for name in ('content-type','accept','range','if-none-match','if-modified-since'):
        if name in request.headers: headers[name]=request.headers[name]
    cookie=session_cookie(request.headers.get('cookie',''))
    if cookie: headers['Cookie']=cookie
    if request.headers.get('origin'): headers['Origin']=API
    # Cloudflare overwrites CF-Connecting-IP. Only this trusted tunnel can reach
    # the adapter; use the validated address for the original login rate limiter.
    address=request.headers.get('cf-connecting-ip')
    if address:
        try: headers['X-Forwarded-For']=str(ipaddress.ip_address(address))
        except ValueError: pass
    target=API+route+('?' + request.url.query if request.url.query else '')
    try:
        # A fresh cookie jar for EVERY request: no global auto-login, role mapping,
        # or session sharing across browsers. Original API authenticates each user.
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=120) as client:
            upstream=await client.request(request.method,target,content=bytes(content),headers=headers)
    except httpx.HTTPError:
        return JSONResponse({'detail':'工作台暂时不可用，请稍后重试'},503)
    body=upstream.content
    media=upstream.headers.get('content-type','application/octet-stream')
    if 'text/html' in media:
        body=body.replace(b'<head>',b'<head><script src="/_workbench_transport.js"></script>',1)
    response=Response(body,status_code=upstream.status_code)
    for name in ('content-type','content-disposition','content-security-policy','content-range','accept-ranges','etag','last-modified'):
        if name in upstream.headers: response.headers[name]=upstream.headers[name]
    location=upstream.headers.get('location')
    if location: response.headers['Location']=location[len(API):] if location.startswith(API+'/') else location
    for value in upstream.headers.get_list('set-cookie'):
        if value.startswith('lex_session='):
            if urlsplit('//'+request.headers.get('host','')).hostname not in {'127.0.0.1','localhost'} and not re.search(r'(?:^|;)\s*secure(?:;|$)',value,re.I): value+='; Secure'
            response.raw_headers.append((b'set-cookie',value.encode('latin-1')))
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-LexAegis-Deployment']='interactive-integration' if os.getenv('LEX_PUBLIC_PROFILE','integration')=='integration' else 'interactive-production-local'
    return response
