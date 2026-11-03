"""Opt-in, hash-pinned synthetic document scope. No production exception."""
import hashlib
import json
import os
import re
from pathlib import Path

SCENARIO='registered_document'

def register():
    from .demo import SCENARIOS
    path=os.getenv('LEX_REGISTERED_DEMO_MANIFEST')
    expected=os.getenv('LEX_REGISTERED_DEMO_MANIFEST_SHA256')
    if not path:
        SCENARIOS.pop(SCENARIO,None)
        return
    if os.getenv('LEX_RUN_PROFILE')!='integration':
        raise ValueError('Registered synthetic documents are integration-only')
    file=Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size>65536:
        raise ValueError('Invalid registered document manifest')
    raw=file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Registered document manifest hash mismatch')
    seed=json.loads(raw)
    fields={'entity','relation','event','date','amount','evidence'}
    facts=seed.get('facts')
    if (seed.get('scenario')!=SCENARIO or seed.get('declaration')!='user_confirmed_synthetic_demo_only'
            or not re.fullmatch(r'[0-9a-f]{64}',seed.get('document_sha256',''))
            or seed.get('live_extract') is not True or not isinstance(seed.get('name'),str)
            or not isinstance(seed.get('document_name'),str) or not isinstance(facts,list) or not 0<len(facts)<=1000
            or any(not isinstance(row,list) or len(row)!=2 or row[0] not in fields
                   or not isinstance(row[1],str) or not row[1].strip() for row in facts)):
        raise ValueError('Invalid registered synthetic declaration')
    SCENARIOS[SCENARIO]=seed

def enabled():
    from .demo import SCENARIOS
    if os.getenv('LEX_RUN_PROFILE')!='integration':return False
    register()
    return os.getenv('LEX_RUN_PROFILE')=='integration' and SCENARIO in SCENARIOS

def is_registered(case):
    from .demo import SCENARIOS
    from .util import digest
    seed=SCENARIOS.get(SCENARIO,{})
    return bool(enabled() and case.get('scenario')==SCENARIO and case.get('mode')=='demo'
        and case.get('runtime_profile')=='integration' and case.get('data_origin')=='bundled_synthetic'
        and case.get('synthetic_manifest_hash')==digest(seed)
        and case.get('registered_document_sha256')==seed.get('document_sha256'))

def public_spec():
    from .demo import SCENARIOS
    if not enabled():return None
    seed=SCENARIOS[SCENARIO]
    return {'scenario':SCENARIO,'name':seed['name'],'filename':seed['document_name'],'sha256':seed['document_sha256']}

def check_upload(case,data,documents):
    from .demo import SCENARIOS
    if not is_registered(case):raise ValueError('This case cannot accept registered uploads')
    if documents:raise ValueError('登记演示每案只接受一份固定材料；请新建演示重做')
    if hashlib.sha256(data).hexdigest()!=SCENARIOS[SCENARIO]['document_sha256']:
        raise ValueError('文件不是已登记并确认的合成文档，未接收')

def check_confirmed_fact(case,data,anchors):
    from .demo import SCENARIOS
    if not is_registered(case):raise ValueError('Unregistered synthetic case')
    seed=SCENARIOS[SCENARIO]
    if (data.get('field'),str(data.get('value','')).strip()) not in {tuple(row) for row in seed['facts']}:
        raise ValueError('候选尚不符合登记演示的字段与原文事实，请校正或删除后再确认')
    ids=data.get('source_ids') or []
    if not ids or any(i not in anchors for i in ids):raise ValueError('登记事实来源无效')
    if not any(data['value'] in anchors[i]['text'] for i in ids):raise ValueError('确认事实必须直接匹配所引原文')
