import importlib.util
import json
import os
import sys
import types
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from lexaegis.parsing import PaddleOCRProvider, ocr_capability, parse, register_ocr_provider
from lexaegis.registry import import_pack, seed_packs
from lexaegis.storage import Store
from lexaegis.cli import backup, restore
from lexaegis.redteam import app as redteam
from lexaegis.api import create_app
from lexaegis.worker import process_one
from lexaegis.util import sign
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


class FakeOCR:
    provider_id = "fake"
    version = "1.2"

    def health(self):
        return {"status": "available", "detail": "test-only local provider"}

    def recognize(self, image):
        yield "模拟识别文本", .92, [10, 5, 90, 25]


def test_image_ocr_provider_has_coordinates_confidence_and_provenance(tmp_path):
    from PIL import Image
    path = tmp_path / "扫描证据.png"
    Image.new("RGB", (100, 50), "white").save(path)
    result = parse(path, "doc_image", ocr_provider=FakeOCR())
    block = result["blocks"][0]
    assert block["kind"] == "ocr"
    assert block["bbox"] == [.1, .1, .9, .5]
    assert block["confidence"] == .92
    assert block["recognizer"] == "fake@1.2"
    assert result["needs_review"]


def test_ocr_provider_failure_falls_back_to_reviewable_scan(tmp_path):
    from PIL import Image

    class BrokenOCR(FakeOCR):
        def recognize(self, image):
            raise RuntimeError("offline model corrupt")

    path = tmp_path / "scan.jpg"
    Image.new("RGB", (80, 40), "white").save(path)
    result = parse(path, "doc_broken", ocr_provider=BrokenOCR())
    assert result["blocks"][0]["kind"] == "scan"
    assert result["needs_review"]
    assert any("OCR 执行失败" in warning for warning in result["warnings"])


def test_ocr_capability_distinguishes_disabled_unknown_and_available(monkeypatch):
    register_ocr_provider(FakeOCR())
    monkeypatch.setenv("LEX_OCR_PROVIDER", "fake")
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    assert ocr_capability()["status"] == "unconfigured"
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    assert ocr_capability()["status"] == "available"
    monkeypatch.setenv("LEX_OCR_PROVIDER", "missing")
    assert ocr_capability()["status"] == "failed"


def _install_fake_paddleocr(monkeypatch, paddle_cls):
    import importlib.machinery

    module = types.ModuleType("paddleocr")
    module.__spec__ = importlib.machinery.ModuleSpec("paddleocr", loader=None)
    module.PaddleOCR = paddle_cls
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    return module


def _recognize_image(monkeypatch):
    if "numpy" not in sys.modules:
        fake_np = types.ModuleType("numpy")
        fake_np.array = lambda image: image
        monkeypatch.setitem(sys.modules, "numpy", fake_np)
        return object()
    from PIL import Image
    return Image.new("RGB", (8, 8), "white")


def test_ocr_disabled_does_not_import_paddle(monkeypatch):
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    monkeypatch.delenv("LEX_OCR_MODELS_READY", raising=False)
    assert "paddleocr" not in sys.modules
    result = ocr_capability()
    assert result["status"] == "unconfigured"
    assert "paddleocr" not in sys.modules


def test_paddle_ocr_constructs_with_cpu_device(monkeypatch):
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def predict(self, array):
            return []

    _install_fake_paddleocr(monkeypatch, FakePaddleOCR)
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "1")
    image = _recognize_image(monkeypatch)
    assert list(PaddleOCRProvider().recognize(image)) == []
    assert captured["kwargs"]["device"] == "cpu"
    assert captured["kwargs"]["lang"] == "ch"
    assert captured["kwargs"]["enable_mkldnn"] is False
    assert captured["kwargs"]["use_doc_orientation_classify"] is False
    assert captured["kwargs"]["use_doc_unwarping"] is False
    assert captured["kwargs"]["use_textline_orientation"] is False


def test_paddle_ocr_retries_without_device_when_kwarg_rejected(monkeypatch):
    calls = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls.append(dict(kwargs))
            if "device" in kwargs:
                raise TypeError("PaddleOCR.__init__() got an unexpected keyword argument 'device'")

        def predict(self, array):
            return []

    _install_fake_paddleocr(monkeypatch, FakePaddleOCR)
    monkeypatch.setenv("LEX_OCR_MODELS_READY", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    image = _recognize_image(monkeypatch)
    assert list(PaddleOCRProvider().recognize(image)) == []
    assert calls[0]["device"] == "cpu"
    assert "device" not in calls[1]
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""


def test_live_paddleocr_scan_smoke(monkeypatch):
    if importlib.util.find_spec("paddleocr") is None:
        pytest.skip("paddleocr 未安装；不在此环境 pip install")
    if os.environ.get("LEX_OCR_MODELS_READY") != "1":
        pytest.skip("环境未声明 LEX_OCR_MODELS_READY=1；跳过真实 Paddle 冒烟以免触发下载")
    monkeypatch.setenv("LEX_OCR_ENABLED", "1")
    monkeypatch.setenv("LEX_OCR_PROVIDER", "paddle")
    result = parse(Path(__file__).resolve().parent.parent / "examples" / "synthetic_scan.pdf", "live_ocr")
    ocr_blocks = [block for block in result["blocks"] if block["kind"] == "ocr"]
    assert ocr_blocks
    assert ocr_blocks[0]["bbox"]
    assert result["needs_review"] is True


def test_txt_paragraphs_become_source_anchors(tmp_path):
    path = tmp_path / "synthetic.txt"
    path.write_text("第一段主张工资12000元。\n\n第二段引用合成证据。", encoding="utf-8")
    result = parse(path, "doc_txt")
    assert [block["kind"] for block in result["blocks"]] == ["paragraph", "paragraph"]
    assert result["blocks"][0]["text"] == "第一段主张工资12000元。"
    assert result["blocks"][1]["locator"] == "段落 2"
    assert result["needs_review"] is False


def test_txt_crlf_blank_lines_become_multiple_chunks(tmp_path):
    path = tmp_path / "windows.txt"
    path.write_bytes("第一段主张工资12000元。\r\n\r\n第二段引用合成证据。".encode("utf-8"))
    result = parse(path, "doc_txt_crlf")
    assert [block["kind"] for block in result["blocks"]] == ["paragraph", "paragraph"]
    assert result["blocks"][0]["text"] == "第一段主张工资12000元。"
    assert result["blocks"][1]["text"] == "第二段引用合成证据。"
    assert result["blocks"][1]["locator"] == "段落 2"


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
    raw=json.loads(Path('packs/contract_test.json').read_text(encoding='utf-8'))
    raw['id']='new_domain';raw['name']='新增领域测试'
    with env['app'].state.store.transaction() as repo:
        p=import_pack(repo,raw)
        assert p['domain_id']=='new_domain'
        raw['name']='同版本篡改'
        with pytest.raises(ValueError):import_pack(repo,raw)
    assert env['client'].post('/api/v1/cases',json={'name':'测试扩展','domain':'new_domain'}).status_code==200


def test_seed_packs_refreshes_stale_demo_not_published(tmp_path):
    demo = json.loads((Path("packs/labor_demo.json")).read_text(encoding="utf-8"))
    assert demo["forbidden_terms"] == ["唯一", "公开获奖"]
    stale = Store(tmp_path / "stale.sqlite")
    with stale.transaction() as repo:
        import_pack(repo, {**demo, "forbidden_terms": []})
        seed_packs(repo)
        refreshed = repo.get("pack:labor:0.1.0-demo", "pack")
        assert refreshed["forbidden_terms"] == ["唯一", "公开获奖"]
        assert refreshed["status"] == "demo"
    published = Store(tmp_path / "published.sqlite")
    with published.transaction() as repo:
        repo.put("pack", {"id": "pack:labor:0.1.0-demo", "domain_id": "labor", "status": "published",
                          "version": "0.1.0-demo", "name": "劳动争议", "forbidden_terms": []})
        seed_packs(repo)
        kept = repo.get("pack:labor:0.1.0-demo", "pack")
        assert kept["status"] == "published"
        assert kept["forbidden_terms"] == []


def test_redteam_truth_fields_rejected_and_placeholder_not_pass(monkeypatch):
    secret="separate-redteam-secret"
    monkeypatch.setenv("LEX_REDTEAM_SECRET",secret)
    client=TestClient(redteam)
    view={'protocol':'identity','request':{'messages':[]},'disclosed_history':[],'auxiliary':[],'query_budget':3}
    response=client.post('/evaluate',json={'view':view,'signature':sign(view,secret)}).json()
    assert response['capability']=='unimplemented'
    assert response['completion']=='incomplete'
    assert response['outcome']=='not_run'
    view['request']={'truth':{'x':'secret'}}
    assert client.post('/evaluate',json={'view':view,'signature':sign(view,secret)}).status_code==422


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


def test_uploaded_image_page_preview_is_local_png(env, tmp_path):
    from PIL import Image
    image = tmp_path / "evidence.jpeg"
    Image.new("RGB", (120, 60), "white").save(image)
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "图片材料预览"}).json()
    client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("evidence.jpeg", image.read_bytes(), "image/jpeg")},
    )
    process_one(env["app"].state.store, env["root"], env["gate"])
    doc = client.get(f"/api/v1/cases/{case['id']}").json()["documents"][0]
    page = client.get(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/page/1")
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG")
    assert client.get(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/page/2").status_code == 404


def _plant_ocr_text(env, case_id, text="识别文本工资12000元"):
    with env["app"].state.store.transaction() as repo:
        doc = repo.list("document", case_id)[0]
        block = doc["ir"]["blocks"][0]
        block["kind"] = "ocr"
        block["text"] = text
        block["reviewed"] = False
        doc["ir"]["needs_review"] = True
        doc["ir"]["review_status"] = "pending"
        repo.put("document", doc, case_id)
        repo.put("document_version", {"id": f"{doc['id']}:v{doc['version']}", "ir": doc["ir"]}, case_id)
    return doc["id"]


def test_confirm_block_does_not_stale_facts_when_text_unchanged(env):
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "确认本块不使事实过期"}).json()
    client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("scan.pdf", Path("examples/synthetic_scan.pdf").read_bytes(), "application/pdf")},
    )
    process_one(env["app"].state.store, env["root"], env["gate"])
    _plant_ocr_text(env, case["id"])
    data = client.get(f"/api/v1/cases/{case['id']}").json()
    doc = data["documents"][0]
    block = doc["ir"]["blocks"][0]
    fact = client.post(
        f"/api/v1/cases/{case['id']}/facts",
        json={"field": "event", "value": block["text"], "source_ids": [block["id"]], "confirmed": True},
    ).json()
    assert fact["stale"] is False
    result = client.put(
        f"/api/v1/cases/{case['id']}/documents/{doc['id']}/confirmation",
        json={"block_id": block["id"]},
    )
    assert result.status_code == 200, result.text
    ir = result.json()["ir"]
    confirmed = next(item for item in ir["blocks"] if item["id"] == block["id"])
    assert confirmed["reviewed"] is True
    assert confirmed["text"] == block["text"]
    assert ir["needs_review"] is False
    assert ir["review_status"] == "reviewed"
    assert result.json()["version"] == doc["version"]
    detail = client.get(f"/api/v1/cases/{case['id']}").json()
    assert detail["facts"][0]["stale"] is False
    assert detail["facts"][0]["confirmed"] is True
    assert detail["facts"][0]["source_ids"] == [block["id"]]
    assert any(event["event"] == "document.block_confirmed" for event in detail["audit"])


def test_empty_scan_cannot_confirm(env):
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "空白扫描不可确认"}).json()
    client.post(
        f"/api/v1/cases/{case['id']}/documents",
        files={"file": ("scan.pdf", Path("examples/synthetic_scan.pdf").read_bytes(), "application/pdf")},
    )
    process_one(env["app"].state.store, env["root"], env["gate"])
    doc = client.get(f"/api/v1/cases/{case['id']}").json()["documents"][0]
    block = doc["ir"]["blocks"][0]
    assert block["kind"] == "scan"
    assert not block["text"]
    result = client.put(
        f"/api/v1/cases/{case['id']}/documents/{doc['id']}/confirmation",
        json={"block_id": block["id"]},
    )
    assert result.status_code == 409
    assert "转录" in result.text
    unchanged = client.get(f"/api/v1/cases/{case['id']}").json()["documents"][0]["ir"]["blocks"][0]
    assert unchanged["reviewed"] is False
    assert unchanged["id"] == block["id"]


def test_demo_cannot_confirm_block(env):
    case, _ = demo_task(env)
    data = env["client"].get(f"/api/v1/cases/{case['id']}").json()
    doc = data["documents"][0]
    block = doc["ir"]["blocks"][0]
    result = env["client"].put(
        f"/api/v1/cases/{case['id']}/documents/{doc['id']}/confirmation",
        json={"block_id": block["id"]},
    )
    assert result.status_code == 409
    assert "演示" in result.text
    assert doc["ir"]["blocks"][0]["reviewed"] is True
    after = env["client"].get(f"/api/v1/cases/{case['id']}").json()["documents"][0]
    assert after["ir"]["blocks"][0]["id"] == block["id"]
    assert after["version"] == doc["version"]
