from io import BytesIO
from hashlib import sha256

from docx import Document


def sample_docx():
    output = BytesIO()
    doc = Document()
    doc.add_paragraph("测试审核表格；并非真实案件")
    doc.save(output)
    return output.getvalue()


def formal_case(env):
    response = env["client"].post("/api/v1/cases", json={"name": "测试正式案件"})
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, case_id, form_type="fa01_source", data=None):
    data = sample_docx() if data is None else data
    return client.post(f"/api/v1/cases/{case_id}/legal-evidence",
                       data={"form_type": form_type},
                       files={"file": ("法学审核.docx", data,
                                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})


def test_legal_evidence_is_separate_from_case_facts_and_dispatch(env):
    client = env["client"]
    case = formal_case(env)
    data = sample_docx()
    response = upload(client, case["id"], data=data)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["status"] == "received_unverified"
    assert record["gate_pass"] is False
    assert record["sha256"] == sha256(data).hexdigest()
    assert "path" not in record
    assert client.get(f"/api/v1/cases/{case['id']}/legal-evidence/{record['id']}/file").content == data
    assert upload(client, case["id"], data=data).json()["id"] == record["id"]
    second = upload(client, case["id"], form_type="fa02_authorization", data=data).json()
    assert second["id"] != record["id"]
    detail = client.get(f"/api/v1/cases/{case['id']}").json()
    assert detail["documents"] == [] and detail["facts"] == [] and detail["jobs"] == []
    assert len(client.get(f"/api/v1/cases/{case['id']}/legal-evidence").json()) == 2


def test_assessment_records_findings_but_never_passes_gate(env):
    client = env["client"]
    case = formal_case(env)
    record = upload(client, case["id"]).json()
    url = f"/api/v1/cases/{case['id']}/legal-evidence/{record['id']}/assessment"
    assert client.put(url, json={"status": "needs_correction", "findings": []}).status_code == 400
    assessed = client.put(url, json={"status": "needs_correction",
                                     "findings": ["来源副本哈希缺失"],
                                     "basis_references": []})
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["status"] == "needs_correction"
    assert assessed.json()["gate_pass"] is False
    assert client.put(url, json={"status": "evidence_checked", "findings": []}).status_code == 400
    checked = client.put(url, json={"status": "evidence_checked", "findings": [],
                                    "basis_references": ["受控库收据及 SHA-256"]})
    assert checked.status_code == 200
    assert checked.json()["gate_pass"] is False
    assert checked.json()["assessed_by"]
    assert client.get("/api/v1/bootstrap").json()["providers"] == []


def test_invalid_docx_demo_case_and_role_are_rejected(env):
    client = env["client"]
    case = formal_case(env)
    assert upload(client, case["id"], data=b"not a DOCX").status_code == 400
    assert upload(client, case["id"], form_type="unknown").status_code == 400
    demo = client.post("/api/v1/demos", json={"scenario": "success"}).json()
    assert upload(client, demo["id"]).status_code == 409
    created = client.post("/api/v1/users", json={"username": "operator", "display_name": "测试操作员",
                                                 "role": "case_operator", "password": "operator-password-123"})
    assert created.status_code == 200
    assert client.post("/api/v1/login", json={"username": "operator", "password": "operator-password-123"}).status_code == 200
    assert upload(client, case["id"]).status_code == 403
    assert client.get(f"/api/v1/cases/{case['id']}/legal-evidence").status_code == 403
