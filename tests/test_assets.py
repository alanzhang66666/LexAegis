import json
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from lexaegis.parsing import parse
from lexaegis.registry import import_pack
from lexaegis.cli import backup, restore
from lexaegis.redteam import app as redteam
from lexaegis.api import create_app
from lexaegis.worker import process_one
from .test_workflow import formal_material
from .conftest import demo_task, approve


def test_scan_without_ocr_preserves_page_and_requires_review():
    path=Path(__file__).resolve().parent.parent/'examples/synthetic_scan.pdf'
    result=parse(path,'doc_scan')
    assert result['needs_review']
    assert result['blocks'][0]['kind']=='scan'
    assert result['blocks'][0]['page']==1
    assert result['blocks'][0]['bbox']==[0,0,1,1]
    assert result['warnings']


def test_docx_table_has_distinct_source_anchors():
    result=parse(Path('examples/synthetic_labor.docx'),'doc_table')
    assert any(b['kind']=='table' and '行' in b['locator'] for b in result['blocks'])
    assert len({b['id'] for b in result['blocks']})==len(result['blocks'])


def test_pdf_text_and_scan_mixed_pages(tmp_path):
    # Minimal text PDF, assembled with explicit xref offsets to avoid another runtime dependency.
    bodies=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream=b'BT /F1 14 Tf 72 700 Td (Synthetic wages 12000 CNY) Tj ET'
    bodies.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    bodies.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>')
    content=b'%PDF-1.4\n';offsets=[]
    for i,body in enumerate(bodies,1):
        offsets.append(len(content));content+=f'{i} 0 obj\n'.encode()+body+b'\nendobj\n'
    start=len(content);content+=f'xref\n0 {len(bodies)+1}\n0000000000 65535 f \n'.encode()
    for offset in offsets:content+=f'{offset:010} 00000 n \n'.encode()
    content+=f'trailer\n<< /Size {len(bodies)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()
    path=tmp_path/'mixed.pdf';path.write_bytes(content)
    ir=parse(path,'mixed')
    assert ir['blocks'][0]['kind']=='pdf_text'
    assert '12000' in ir['blocks'][0]['text']
    assert ir['blocks'][1]['kind']=='scan'
    assert ir['needs_review']


def test_domain_pack_extends_without_gate_change_and_immutable_versions(env):
    raw=json.loads(Path('packs/contract_test.json').read_text())
    raw['id']='new_domain';raw['name']='新增领域测试'
    with env['app'].state.store.transaction() as repo:
        p=import_pack(repo,raw)
        assert p['domain_id']=='new_domain'
        raw['name']='同版本篡改'
        with pytest.raises(ValueError):import_pack(repo,raw)
    assert env['client'].post('/api/v1/cases',json={'name':'测试扩展','domain':'new_domain'}).status_code==200


def test_redteam_truth_fields_rejected_and_placeholder_not_pass():
    client=TestClient(redteam)
    request={'protocol':'identity','request':{'messages':[]}}
    response=client.post('/evaluate',json=request).json()
    assert response['capability']=='unimplemented'
    assert response['completion']=='incomplete'
    assert response['outcome']=='not_run'
    assert client.post('/evaluate',json={**request,'identity_mapping':{'x':'secret'}}).status_code==422


def test_backup_restore_includes_material_versions_approvals_and_send_records(env):
    case,doc,fact=formal_material(env)
    demo,task=demo_task(env);approve(env,task)
    env['client'].post(f"/api/v1/tasks/{task['id']}/send")
    process_one(env['app'].state.store,env['root'],env['gate'])
    destination=env['temp']/'backup.zip'
    backup(env['root'],env['temp']/'gateway',destination)
    with zipfile.ZipFile(destination) as archive:
        assert not any('password' in n or 'secret' in n for n in archive.namelist())
    restored=env['temp']/'restored';gateway=env['temp']/'restored-gateway'
    restore(destination,restored,gateway)
    with TestClient(create_app(restored,password='restore-test')) as client:
        client.post('/api/v1/login',json={'password':'restore-test'})
        detail=client.get('/api/v1/cases/'+case['id']).json()
        assert detail['facts'][0]['source_ids']==fact['source_ids']
        assert client.get(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/file").status_code==200
        demonstration=client.get('/api/v1/cases/'+demo['id']).json()
        assert demonstration['tasks'][0]['approval']
        assert demonstration['ledger'][0]['status']=='sent'
    with pytest.raises(ValueError):restore(destination,restored,gateway)


def test_missing_edge_keeps_manual_flow_available(env):
    case,doc,fact=formal_material(env)
    assert fact['confirmed']
    r=env['client'].post('/api/v1/cases/'+case['id']+'/extract')
    assert r.status_code==409
    assert '未配置' in r.text


def test_scan_page_render_and_manual_transcription(env):
    client=env['client']
    case=client.post('/api/v1/cases',json={'name':'扫描转录验收'}).json()
    client.post(f"/api/v1/cases/{case['id']}/documents",files={'file':('scan.pdf',Path('examples/synthetic_scan.pdf').read_bytes(),'application/pdf')})
    process_one(env['app'].state.store,env['root'],env['gate'])
    doc=client.get('/api/v1/cases/'+case['id']).json()['documents'][0]
    page=client.get(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/page/1")
    assert page.status_code==200 and page.content.startswith(b'\x89PNG')
    result=client.put(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/correction",json={'block_id':doc['ir']['blocks'][0]['id'],'text':'Synthetic amount: 12000 CNY'})
    assert result.status_code==200
    assert result.json()['version']==2
    assert not result.json()['ir']['needs_review']
