"""Deployment wrapper around the UNMODIFIED LexAegis gateway.

Secrets and operational integration quota live here; legal/approval validation
continues to be performed by lexaegis.gateway without replacement or bypass.
"""
import hmac
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lexaegis.cloud import DualSlotProvider
from lexaegis.gateway import Envelope, create_gateway
from lexaegis.util import digest, sign


def private_value(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Gateway configuration must be a private regular file')
    return path.read_text(encoding='utf-8').strip()


class IntegrationBudget:
    """Durable pre-reservation; no retries or refunds after uncertain dispatch."""
    def __init__(self, app, store, secret, limit=10, initial=0):
        if not 0 <= initial or not 0 <= limit <= 10:
            raise ValueError('Invalid integration quota')
        self.app, self.store, self.secret, self.limit = app, store, secret, limit
        with store.transaction() as repo:
            try:
                repo.get('cloud-deployment-quota','deployment_quota')
            except KeyError:
                old = repo.list('integration_quota')
                used = max([initial,len(repo.list('send'))] + [r['reserved'] for r in old])
                repo.put('deployment_quota',{'id':'cloud-deployment-quota','reserved':used})

    def quota(self):
        with self.store.read() as repo:
            used = repo.get('cloud-deployment-quota','deployment_quota')['reserved']
        return {'limit':self.limit,'reserved':used,'remaining':max(0,self.limit-used)}

    def reserve(self,request):
        # Never await a response or block the event loop while holding SQLite's
        # writer lock. The original gateway may be writing its send receipt.
        with self.store.transaction() as repo:
            try:
                repo.get(request['request_id'],'send')
                return None
            except KeyError:
                pass
            reservation='deployment-reservation:'+request['request_id']
            try:
                repo.get(reservation,'deployment_reservation')
                return 'Uncertain reservation; reconcile before reuse'
            except KeyError:
                pass
            quota=repo.get('cloud-deployment-quota','deployment_quota')
            if quota['reserved']>=self.limit:
                return 'Integration cloud quota exhausted'
            quota['reserved']+=1
            repo.put('deployment_quota',quota)
            repo.put('deployment_reservation',{'id':reservation,'request_hash':digest(request)})
        return None

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/dispatch' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        raw = b''
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect': return
            raw += message.get('body',b'')
            if len(raw) > 1024 * 1024:
                return await JSONResponse({'detail':'Request exceeds deployment limit'},413)(scope,receive,send)
            if not message.get('more_body'): break
        try:
            envelope = Envelope.model_validate_json(raw)
            request = envelope.request.model_dump()
            signed = {'request':request,'approval':envelope.approval}
            for name in ('formal_release','cloud_envelope'):
                value = getattr(envelope,name)
                if value is not None: signed[name] = value
            if not hmac.compare_digest(sign(signed,self.secret),envelope.signature):
                return await JSONResponse({'detail':'Invalid gateway signature'},403)(scope,receive,send)
            if request['transport'] == 'cloud':
                rejection=await run_in_threadpool(self.reserve,request)
                if rejection:
                    return await JSONResponse({'detail':rejection},409)(scope,receive,send)
        except (ValueError, ValidationError, KeyError, TypeError):
            return await JSONResponse({'detail':'Invalid gateway envelope'},403)(scope,receive,send)
        delivered = False
        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request','body':raw,'more_body':False}
            return await receive()
        await self.app(scope,replay_body,send)


def create_app():
    config_root = Path(os.getenv('LEX_PRIVATE_CONFIG','/run/private'))
    secret = private_value(config_root/'gateway-secret')
    # Do not expand ${...}, accept arbitrary environment settings, or echo values.
    key_text = private_value(config_root/'gateway.env')
    from io import StringIO
    values = dotenv_values(stream=StringIO(key_text),interpolate=False)
    if set(values) - {'LEX_CLOUD_PRIMARY_KEY','LEX_KEY_USE_CONFIRMED','LEX_KEY_ROTATION_CONFIRMED'}:
        raise ValueError('Unexpected gateway credential settings')
    if values.get('LEX_KEY_USE_CONFIRMED') != '1' and values.get('LEX_KEY_ROTATION_CONFIRMED') != '1':
        raise ValueError('Explicit key-use confirmation is required')
    key = (values.get('LEX_CLOUD_PRIMARY_KEY') or '').strip()
    if len(key) < 20 or len(secret) < 24:
        raise ValueError('Gateway credentials are not configured')
    # Explicit proxy supplied through the existing provider injection interface;
    # inherited HTTP_PROXY/HTTPS_PROXY settings are never trusted.
    client = httpx.Client(proxy='http://provider-egress:3128',trust_env=False,follow_redirects=False,timeout=90)
    provider = DualSlotProvider(primary_key=key,standby_key='',client=client)
    app = create_gateway(secret=secret,provider=provider)
    original_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            try:
                yield state
            finally:
                client.close()
    app.router.lifespan_context=lifespan
    budget = None
    if os.getenv('LEX_RUN_PROFILE') == 'integration':
        budget = IntegrationBudget(app,app.state.store,secret,
            int(os.getenv('LEX_INTEGRATION_MAX_CLOUD_ATTEMPTS','0')),int(os.getenv('LEX_INITIAL_CONSUMED','0')))
    @app.get('/deployment/status')
    def deployment_status(x_gateway_signature: str = __import__('fastapi').Header(default='')):
        from fastapi import HTTPException
        if not hmac.compare_digest(sign({'op':'health'},secret),x_gateway_signature):
            raise HTTPException(403,'Invalid gateway signature')
        return {'runtime_profile':os.getenv('LEX_RUN_PROFILE'),'gateway_role':'cloud',
                'quota':budget.quota() if budget else None,'formal_dispatch':'blocked',
                'source_application':'unmodified','isolation_acceptance':'not_verified'}
    return budget if budget else app
