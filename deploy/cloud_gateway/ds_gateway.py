"""Deployment factory. Original gateway checks stay authoritative."""
from contextlib import asynccontextmanager
from io import StringIO
import hmac
import json
import os
from pathlib import Path
from dotenv import dotenv_values
from fastapi import Header,HTTPException

from cloud_runtime import IntegrationBudget,private_value
from shared_budget import Budget,BudgetClient

def create_app():
    if os.getenv('LEX_RUN_PROFILE')!='integration':raise ValueError('This operational trial factory is integration-only')
    from lexaegis import registered_demo
    registered_demo.register()
    from lexaegis.cloud import DualSlotProvider
    from lexaegis.gateway import create_gateway
    from lexaegis.util import sign
    values=dotenv_values(stream=StringIO(private_value('/run/private/gateway.env')),interpolate=False)
    policy=json.loads(Path(os.getenv('LEX_GLOBAL_POLICY_PATH','/run/private/global-policy.json')).read_text())
    if policy['lifetime_limit']>0 and values.get('LEX_KEY_USE_CONFIRMED')!='1' and values.get('LEX_KEY_ROTATION_CONFIRMED')!='1':raise ValueError('Key use was not confirmed')
    key=values.get('LEX_CLOUD_PRIMARY_KEY','')
    expected_role='cloud' if policy['lifetime_limit']>0 else 'edge'
    if os.getenv('LEX_GATEWAY_ROLE')!=expected_role:raise ValueError('Gateway role does not match its explicitly configured allowance')
    if not policy['lifetime_limit'] and key:raise ValueError('Zero-budget edge mode forbids provider credentials')
    secret=private_value('/run/private/gateway-secret')
    if len(secret)<24:raise ValueError('Gateway signing credential missing')
    quota=Budget('/quota/cloud-budget.sqlite',initial=policy['initial_reserved'],limit=policy['lifetime_limit'])
    if policy['lifetime_limit']>0 and len(key)<20:raise ValueError('Gateway provider credential missing')
    client=BudgetClient(budget=quota,proxy='http://provider-egress:3128',trust_env=False,follow_redirects=False,timeout=90,
        headers={'Accept-Encoding':'identity'})
    app=create_gateway(secret=secret,provider=DualSlotProvider(primary_key=key,standby_key='',client=client))
    if os.getenv('LEX_RUN_PROFILE')!='integration':raise ValueError('This operational trial factory is integration-only')
    budget=IntegrationBudget(app,app.state.store,secret,limit=10,initial=int(os.getenv('LEX_INITIAL_CONSUMED','0')))
    budget.limit=policy['lifetime_limit']
    old=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with old(application) as state:
            try:yield state
            finally:client.close()
    app.router.lifespan_context=lifespan
    @app.get('/deployment/status')
    def status(x_gateway_signature:str=Header(default='')):
        if not hmac.compare_digest(sign({'op':'health'},secret),x_gateway_signature):raise HTTPException(403,'Invalid gateway signature')
        return {'runtime_profile':'integration','gateway_role':expected_role,'quota':quota.status(),
            'local_ledger_quota':budget.quota(),'formal_dispatch':'blocked','source_application':'original_gateway_checks',
            'isolation_acceptance':'not_verified','registered_document':bool(os.getenv('LEX_REGISTERED_DEMO_MANIFEST'))}
    return budget
