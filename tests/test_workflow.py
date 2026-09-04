import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from docx import Document
from fastapi.testclient import TestClient
from lexaegis.api import create_app
from lexaegis.gateway import create_gateway
from lexaegis.worker import process_one, recover
from lexaegis.policy import check_claims
from lexaegis.util import digest, sign
from .conftest import demo_task, approve


def task_state(env, case_id, task_id):
    return next(t for t in env["client"].get(f"/api/v1/cases/{case_id}").json()["tasks"] if t["id"]==task_id)


def test_complete_synthetic_workflow_and_source_confirmation(env):
    case,task=demo_task(env)
    task=approve(env,task)
    client=env["client"]
    assert client.post(f"/api/v1/tasks/{task['id']}/send").status_code==200
    assert process_one(env["app"].state.store,env["root"],env["gate"])
    finished=task_state(env,case["id"],task["id"])
    assert finished["status"]=="complete"
    assert finished["artifact"]["provenance"]=="simulation"
    assert not finished["artifact"]["confirmed"]
    assert client.post(f"/api/v1/tasks/{task['id']}/confirm").status_code==409
    for claim in finished["artifact"]["claims"]:
        assert claim["anchors"]
        assert client.post(f"/api/v1/tasks/{task['id']}/claims/{claim['id']}/review").status_code==200
    assert client.post(f"/api/v1/tasks/{task['id']}/confirm").json()["artifact"]["confirmed"]
    exported=client.get(f"/api/v1/tasks/{task['id']}/export").json()
    assert exported["artifact"]["provenance"]=="simulation"
    assert exported["view"]=="cloud"
    assert "local_text" not in exported["artifact"]["claims"][0]
    assert client.get(f"/api/v1/tasks/{task['id']}/export?view=local").status_code==409
    assert client.post(f"/api/v1/tasks/{task['id']}/local-export-approval",json={"actor":"复核律师","actor_role":"legal_reviewer"}).status_code==200
    local=client.get(f"/api/v1/tasks/{task['id']}/export?view=local").json()
    assert local["artifact"]["claims"][0]["local_text"]
    assert local["bundle_type"]=="local_review_bundle"


@pytest.mark.parametrize("scenario",["linkage","stop"])
def test_risk_and_stop_examples_block_approval(env,scenario):
    case,task=demo_task(env,scenario)
    result=env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    assert result["risk"]["blockers"]
    assert result["risk"]["completion"]=="incomplete"
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/approve",json={"request_hash":result["request_hash"]}).status_code==409
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/stop").json()["status"]=="stopped"


def test_unapproved_and_modified_requests_do_not_send(env):
    case,task=demo_task(env)
    client=env["client"]
    assert client.post(f"/api/v1/tasks/{task['id']}/send").status_code==409
    task=approve(env,task)
    old_hash=task["request_hash"]
    decision=task["decisions"][0]
    assert client.patch(f"/api/v1/tasks/{task['id']}/decisions/{decision['fact_id']}",json={"transform":"delete","necessity":"unnecessary"}).status_code==200
    assert client.post(f"/api/v1/tasks/{task['id']}/send").status_code==409
    assert client.post(f"/api/v1/tasks/{task['id']}/approve",json={"request_hash":old_hash}).status_code==409


def test_concurrent_double_submit_reserves_one_send(env):
    case,task=demo_task(env)
    task=approve(env,task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:env["client"].post(f"/api/v1/tasks/{task['id']}/send").status_code,range(2)))
    assert sorted(results)==[200,409]
    data=env["client"].get(f"/api/v1/cases/{case['id']}").json()
    assert len(data["ledger"])==1
    assert len([j for j in data["jobs"] if j["kind"]=="send"])==1


def test_history_invalidates_second_approval(env):
    case,first=demo_task(env)
    second=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"mock"}).json()
    first,second=approve(env,first),approve(env,second)
    env["client"].post(f"/api/v1/tasks/{first['id']}/send")
    process_one(env["app"].state.store,env["root"],env["gate"])
    result=env["client"].post(f"/api/v1/tasks/{second['id']}/send")
    assert result.status_code==409
    assert "累计披露" in result.text


def test_timeout_becomes_unknown_and_reconcile_never_posts(env):
    import httpx
    class TimeoutClient:
        def post(self,*args,**kwargs):
            raise httpx.ReadTimeout("test timeout")
        def get(self,*args,**kwargs):
            return httpx.Response(404,request=httpx.Request("GET","http://testserver"))
    case,task=demo_task(env)
    approve(env,task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    process_one(env["app"].state.store,env["root"],TimeoutClient())
    assert task_state(env,case["id"],task["id"])["status"]=="unknown"
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/send").status_code==409
    env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile")
    process_one(env["app"].state.store,env["root"],TimeoutClient())
    assert task_state(env,case["id"],task["id"])["status"]=="unknown"


def test_restart_recovers_inflight_send_as_unknown(env):
    case,task=demo_task(env)
    approve(env,task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    with env["app"].state.store.transaction() as repo:
        job=repo.list("job",case["id"])[0]
        job["status"]="running"
        repo.put("job",job,case["id"])
    recover(env["app"].state.store)
    assert task_state(env,case["id"],task["id"])["status"]=="unknown"
    assert not process_one(env["app"].state.store,env["root"],env["gate"])


def test_gateway_hash_auth_and_deduplication(env):
    case,task=demo_task(env)
    task=approve(env,task)
    content={"request":task["request"],"approval":task["approval"]}
    envelope={**content,"signature":sign(content,"unit-test-secret-32-characters-long")}
    result=env["gate"].post("/dispatch",json=envelope)
    assert result.status_code==200
    assert result.json()["status"]=="complete"
    assert env["gate"].post("/dispatch",json=envelope).json()==result.json()
    content["request"]["body"]["messages"][1]["content"]="tampered"
    assert env["gate"].post("/dispatch",json=envelope).status_code==403
    envelope["signature"]=sign(content,"unit-test-secret-32-characters-long")
    assert env["gate"].post("/dispatch",json=envelope).status_code==403
    assert env["gate"].get('/requests/'+task['request']['request_id']).status_code==403


def test_synthetic_mode_cannot_accept_user_material_or_custom_payload(env):
    case,task=demo_task(env)
    client=env["client"]
    assert client.post(f"/api/v1/cases/{case['id']}/documents",files={"file":("private.pdf",b"secret","application/pdf")}).status_code==409
    assert client.post(f"/api/v1/cases/{case['id']}/facts",json={"field":"event","value":"secret","source_ids":["x"],"confirmed":True}).status_code==409
    d=task["decisions"][0]
    assert client.patch(f"/api/v1/tasks/{task['id']}/decisions/{d['fact_id']}",json={"transform":"keep","necessity":"required","output":"private data"}).status_code==409


def formal_material(env):
    client=env["client"]
    case=client.post('/api/v1/cases',json={"name":"正式测试案件"}).json()
    doc=Document();doc.add_paragraph("劳动者林甲主张工资12000元。");table=doc.add_table(rows=1,cols=1);table.cell(0,0).text="工资表证据"
    stream=io.BytesIO();doc.save(stream)
    r=client.post(f"/api/v1/cases/{case['id']}/documents",files={"file":("sample.docx",stream.getvalue(),"application/octet-stream")})
    assert r.status_code==200
    process_one(env["app"].state.store,env["root"],env["gate"])
    data=client.get(f"/api/v1/cases/{case['id']}").json()
    document=data["documents"][0]
    block=document["ir"]["blocks"][0]
    fact=client.post(f"/api/v1/cases/{case['id']}/facts",json={"field":"event","value":block["text"],"source_ids":[block["id"]],"confirmed":True}).json()
    return case,document,fact


def test_formal_missing_rules_and_attacks_block(env):
    case,doc,fact=formal_material(env)
    client=env["client"]
    assert client.post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"mock"}).status_code==409
    task=client.post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"cloud"}).json()
    result=client.post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    assert "适用规则尚未正式发布" in result["risk"]["blockers"]
    assert any("四类" in b for b in result["risk"]["blockers"])
    assert not result["risk"]["approval_allowed"]


def test_corrected_doc_retains_old_anchors_and_stales_tasks_after_restart(env):
    case,doc,fact=formal_material(env)
    client=env["client"]
    task=client.post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"cloud"}).json()
    old_anchor=fact["source_ids"][0]
    corrected=client.put(f"/api/v1/cases/{case['id']}/documents/{doc['id']}/correction",json={"block_id":old_anchor,"text":"校正后工资15000元"})
    assert corrected.status_code==200
    assert corrected.json()["version"]==2
    with TestClient(create_app(env["root"],password="test-restart-password")) as restarted:
        restarted.post('/api/v1/login',json={"password":"test-restart-password"})
        anchors=restarted.get(f"/api/v1/cases/{case['id']}/anchors").json()
        assert any(a["id"]==old_anchor and "12000" in a["text"] for a in anchors)
        data=restarted.get(f"/api/v1/cases/{case['id']}").json()
        assert data["facts"][0]["stale"]
        assert data["tasks"][0]["stale"]
        assert restarted.post(f"/api/v1/tasks/{task['id']}/evaluate").status_code==409


def test_case_mapping_isolated_and_consistent(env):
    case,a=demo_task(env)
    b=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"mock"}).json()
    other,c=demo_task(env)
    assert a["decisions"][0]["output"]==b["decisions"][0]["output"]
    assert a["decisions"][0]["output"]==c["decisions"][0]["output"]=="[[LEX:P0001]]"
    alias=a["decisions"][0]["output"]
    assert alias in a["decisions"][2]["output"]
    first=env["client"].get(f"/api/v1/cases/{case['id']}").json()["case"]
    second=env["client"].get(f"/api/v1/cases/{other['id']}").json()["case"]
    assert first["mapping_entries"] is not second["mapping_entries"]


def test_hallucinated_numbers_and_missing_sources_never_auto_verify(env):
    case,task=demo_task(env)
    valid=task["decisions"][5]["fact_id"]
    claims=check_claims({"claims":[{"text":"工资999999元","source_ids":[valid]},{"text":"无依据陈述","source_ids":["missing"]}]},task,task["fact_snapshot"])
    assert all(c["status"]=="needs_review" for c in claims)
    assert "日期或金额存在未在引用事实中出现的数字" in claims[0]["issues"]
    assert not claims[1]["anchors"]


def test_endpoint_change_invalidates_old_task(env):
    case,task=demo_task(env)
    approve(env,task)
    response=env["client"].put('/api/v1/settings',json={"cloud_url":"https://api.openai.com/v1","cloud_model":"new-model","edge_url":"http://localhost:11434/v1","edge_model":""})
    assert response.status_code==200
    assert env["client"].post(f"/api/v1/tasks/{task['id']}/send").status_code==409


def test_public_edge_endpoint_and_cross_site_calls_rejected(env):
    result=env["client"].put('/api/v1/settings',json={"cloud_url":"https://api.openai.com/v1","cloud_model":"x","edge_url":"https://example.com/v1","edge_model":"x"})
    assert result.status_code==409
    assert env["client"].post('/api/v1/demos',json={"scenario":"success"},headers={"Origin":"https://malicious.example"}).status_code==403
    with TestClient(env["app"]) as unauthenticated:
        assert unauthenticated.get('/api/v1/bootstrap').status_code==401


def test_cloud_mock_provider_and_unknown_provider_error(env):
    class Provider:
        api_key="test-only-key"
        calls=0
        def send(self,target,body):
            self.calls+=1
            f=json.loads(body["messages"][1]["content"])["facts"][0]
            return {"claims":[{"text":f["text"],"source_ids":[f["id"]]}]}
    provider=Provider()
    gateway=TestClient(create_gateway(env["temp"]/"test-provider",secret="unit-test-secret-32-characters-long",provider=provider))
    env["client"].put('/api/v1/settings',json={"cloud_url":"https://api.openai.com/v1","cloud_model":"test-model","edge_url":"http://localhost:11434/v1","edge_model":""})
    case,task=demo_task(env,transport="cloud")
    task=approve(env,task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send")
    process_one(env["app"].state.store,env["root"],gateway)
    assert provider.calls==1
    assert task_state(env,case["id"],task["id"])["artifact"]["provenance"]=="cloud"
    # This is a test double, not evidence of a live model invocation.
