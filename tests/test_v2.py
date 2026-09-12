import math
from pathlib import Path

import pytest

from lexaegis.attacks import POSITIVE_CONTROL_REQUEST, evaluate as attack
from lexaegis.contracts import MappingEntry
from lexaegis.detection import bind_source_spans, detect_text, merge_overlaps, risk_signals
from lexaegis.dataset import build_semisynthetic_manifest, validate_annotations
from lexaegis.experiments import gaussian_dp, l2_clip, mia_requires_real_outputs, random_projection, rdp_gaussian, rdp_to_epsilon
from lexaegis.registry import run_pack_regressions, validate_pack
from lexaegis import task_engine
from lexaegis.policy import check_claims, check_cloud_feedback, ensure_mappings, transform
from lexaegis.task_engine import validate_cloud_result
from lexaegis.util import digest
from .test_workflow import formal_material


def test_mapping_contract_and_coordinate_detection():
    entry=MappingEntry(entity_id="entity_0001",wire_token="[[LEX:P0001]]",display_alias="主体1",original_value="林甲",source_ids=["b1"],mapping_version=1)
    assert entry.wire_token=="[[LEX:P0001]]"
    findings=detect_text("电话13800138000，重复13800138000",anchor_id="b1")
    assert len(findings)==2 and all(item["source_anchor_id"]=="b1" for item in findings)
    merged=merge_overlaps([{"id":"a","category":"A","value":"x","start":0,"end":4,"risk":"medium","source_anchor_id":"b1"},
                           {"id":"b","category":"B","value":"y","start":2,"end":5,"risk":"critical","source_anchor_id":"b1"}])
    assert merged[0]["end"]==5 and merged[0]["risk"]=="critical"


def test_v1_cannot_be_promoted_and_v2_default_is_conservative():
    with pytest.raises(ValueError):
        validate_pack({"schema_version":1,"id":"legacy","name":"legacy","version":"1","status":"published","task_ids":["fact_summary"],
                       "fact_fields":["event"],"rules":[],"references":["x"],"review_record":"x","required_attacks":[]})
    pack=validate_pack({"schema_version":2,"id":"new_domain","name":"新案由","version":"0.1","status":"draft","task_ids":["timeline"],
                        "fact_fields":[{"id":"event","label":"事件"}],"rules":[{"field":"event","necessity":"uncertain","transform":"delete","reason":"待审"}],
                        "references":[]})
    assert pack.rules[0].necessity=="uncertain" and pack.rules[0].transform=="delete"
    assert pack.task_field_matrix[0].necessity=="uncertain"
    assert not pack.dispatch_allowed and pack.legal_status=="pending_legal_review"


def test_pack_rejects_executable_regex_and_runs_synthetic_regression():
    raw={"schema_version":2,"id":"safe_pack","name":"技术测试案由","version":"0.1","status":"draft","task_ids":["timeline"],
         "fact_fields":[{"id":"event","label":"事件"}],
         "rules":[{"field":"event","necessity":"uncertain","transform":"delete","reason":"待审"}],
         "references":[],"synthetic_cases":[{"id":"c1","expected_decisions":[{"field":"event","transform":"delete"}]}]}
    pack=validate_pack(raw)
    assert run_pack_regressions(pack.model_dump())["status"]=="passed"
    raw["direct_identifier_patterns"]=[{"category":"bad","pattern":"(a+)+"}]
    with pytest.raises(ValueError,match="回溯"):
        validate_pack(raw)


def test_detection_binds_every_exact_original_span_and_finds_context_name():
    anchors={
        "b1":{"id":"b1","text":"劳动者林甲主张联系13800138000。","document_version":1},
        "b2":{"id":"b2","text":"另页记载13800138000。","document_version":1},
    }
    phone=detect_text("联系13800138000")
    bound=bind_source_spans(phone,["b1","b2"],anchors)
    assert {item["anchor_id"] for item in bound[0]["source_spans"]}=={"b1","b2"}
    assert bound[0]["coordinate_space"]=="disclosure" and bound[0]["locator_status"]=="located"
    assert "姓名" in {item["category"] for item in detect_text(anchors["b1"]["text"])}


def test_local_timeline_extends_without_dispatch(env):
    case,document,fact=formal_material(env)
    result=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"task_type":"timeline","transport":"local"})
    assert result.status_code==200
    task=result.json()
    assert task["status"]=="complete" and task["request"] is None
    assert task["artifact"]["provenance"]=="local_deterministic"


def test_local_evidence_inventory_lists_evidence_facts(env):
    case, document, _ = formal_material(env)
    block = document["ir"]["blocks"][0]
    env["client"].post(f"/api/v1/cases/{case['id']}/facts", json={
        "field": "evidence", "value": "劳动合同原件", "source_ids": [block["id"]], "confirmed": True,
    })
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "evidence_inventory", "transport": "local"},
    )
    assert result.status_code == 200
    task = result.json()
    assert task["status"] == "complete" and task["request"] is None
    assert task["artifact"]["provenance"] == "local_deterministic"
    assert any(item["text"] == "劳动合同原件" for item in task["artifact"]["items"])


def test_local_issue_extraction_groups_by_field_without_dispatch(env):
    case, document, fact = formal_material(env)
    block = document["ir"]["blocks"][0]
    env["client"].post(f"/api/v1/cases/{case['id']}/facts", json={
        "field": "amount", "value": "工资12000元", "source_ids": [block["id"]], "confirmed": True,
    })
    result = env["client"].post(
        f"/api/v1/cases/{case['id']}/tasks",
        json={"task_type": "issue_extraction", "transport": "local"},
    )
    assert result.status_code == 200
    task = result.json()
    assert task["status"] == "complete" and task["request"] is None
    assert task["artifact"]["provenance"] == "local_deterministic"
    issues = task["artifact"]["issues"]
    assert issues and all(item.get("source_ids") for item in issues)
    topics = {item["topic"] for item in issues}
    assert topics == {"disputed_event", "remuneration"}
    event = next(item for item in issues if item["topic"] == "disputed_event")
    assert fact["id"] in event["fact_ids"]
    ledger = env["client"].get(f"/api/v1/cases/{case['id']}").json()["ledger"]
    assert ledger == []
    for transport in ("cloud", "mock"):
        rejected = env["client"].post(
            f"/api/v1/cases/{case['id']}/tasks",
            json={"task_type": "issue_extraction", "transport": transport},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "任务不支持所选传输方式"
    assert env["client"].get(f"/api/v1/cases/{case['id']}").json()["ledger"] == []


def test_entrypoint_task_executes_without_service_state_machine_change(env, monkeypatch):
    class Plugin:
        @staticmethod
        def definition():
            return {"schema_version":2,"id":"custom_timeline","name":"扩展时间线","version":"1.0","status":"available",
                    "execution_type":"local_deterministic",
                    "input_schema":{"type":"object","required":["facts"],"properties":{"facts":{"type":"array"}}},
                    "output_schema":{"type":"object","required":["events"],"properties":{"events":{"type":"array"}}},
                    "validator":"custom_v1","transports":["local"],"ui_renderer":"timeline","max_payload_chars":50000}
        @staticmethod
        def run(payload):
            return {"events":[{"id":item["id"],"text":item["value"],"source_ids":item["source_ids"]} for item in payload["facts"]]}
    class Entry:
        name="custom"
        @staticmethod
        def load():
            return Plugin
    monkeypatch.setattr(task_engine,"entry_points",lambda group:[Entry()])
    case,_,_=formal_material(env)
    with env["app"].state.store.transaction() as repo:
        pack=repo.list("pack")[-1]
        pack["task_ids"].append("custom_timeline")
        pack["task_field_matrix"].append({"task_id":"custom_timeline","field":"event","necessity":"uncertain","rationale":"测试"})
        repo.put("pack",pack)
    result=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",
                              json={"task_type":"custom_timeline","transport":"local","pack_id":pack["id"]})
    assert result.status_code==200,result.text
    assert result.json()["artifact"]["events"] and result.json()["status"]=="complete"


def test_create_task_uses_v2_matrix_or_conservative_default(env):
    case,document,_=formal_material(env)
    with env["app"].state.store.transaction() as repo:
        pack=next(item for item in repo.list("pack") if item.get("schema_version")==2)
        pack["task_field_matrix"]=[{"task_id":"fact_summary","field":"event","necessity":"required","rationale":"矩阵必填"}]
        repo.put("pack",pack)
    block=document["ir"]["blocks"][0]
    env["client"].post(f"/api/v1/cases/{case['id']}/facts",json={"field":"day_nature","value":"工作日","source_ids":[block["id"]],"confirmed":True,"day_nature":"weekday"})
    task=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"cloud"}).json()
    by_field={item["field"]:item for item in task["decisions"]}
    assert by_field["event"]["necessity"]=="required"
    assert by_field["day_nature"]["necessity"]=="uncertain" and by_field["day_nature"]["transform"]=="delete"
    with env["app"].state.store.transaction() as repo:
        pack=repo.get(task["pack_id"],"pack")
        pack["task_field_matrix"]=[]
        pack["disclosure_rules"]=[]
        repo.put("pack",pack)
    empty=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"cloud"}).json()
    assert all(item["necessity"]=="uncertain" and item["transform"]=="delete" for item in empty["decisions"])


def test_wire_payload_excludes_local_only_data(env):
    case=env["client"].post("/api/v1/demos",json={"scenario":"success"}).json()
    task=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"mock"}).json()
    evaluated=env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    wire=evaluated["request"]["wire_payload"]
    assert set(wire)=={"contract_version","task","facts"}
    assert all(set(item)<= {"id","text","field"} and "field" in item for item in wire["facts"])
    assert "林澄" not in str(wire) and "mapping" not in str(wire).lower()
    assert "[[LEX:P0001]]" in str(wire)
    deps=evaluated["request"]["dependencies"]
    assert not deps["dual_slot"].get("standby")
    assert "备用" in (deps.get("standby_note") or "")
    assert not deps.get("standby_model")
    assert deps["prompt_hash"]


def test_claim_validator_flags_unknown_direct_identifier():
    task={"decisions":[{"fact_id":"f1","output":"[[LEX:P0001]]主张工资12000元"}]}
    facts=[{"id":"f1","source_ids":["b1"]}]
    claims=check_claims({"claims":[{"text":"[[LEX:P0001]]电话13800138000，主张工资12000元","source_ids":["f1"]}]},task,facts)
    assert "陈述包含未在引用事实中出现的直接标识" in claims[0]["issues"]


def test_mapping_conflict_and_unknown_or_broken_tokens_are_explicit():
    case = {"mapping_entries": [
        {"entity_id": "entity_0001", "wire_token": "[[LEX:P0001]]", "original_value": "合成人物甲"},
        {"entity_id": "entity_0002", "wire_token": "[[LEX:P0001]]", "original_value": "合成人物乙"},
    ]}
    with pytest.raises(ValueError, match="冲突"):
        ensure_mappings(case, [])
    task = {"decisions": [{"fact_id": "f1", "output": "[[LEX:P0001]]主张工资12000元"}]}
    facts = [{"id": "f1", "source_ids": ["b1"]}]
    claims = check_claims({"claims": [
        {"text": "[[LEX:P9999]]主张工资12000元", "source_ids": ["f1"]},
        {"text": "[[LEX:P0001]主张工资12000元", "source_ids": ["f1"]},
    ]}, task, facts)
    assert any("未知" in issue for issue in claims[0]["issues"])
    assert any("破损" in issue for issue in claims[1]["issues"])


def test_mapping_entry_accepts_polc_tokens_and_aliases():
    entry = MappingEntry(entity_id="entity_0002", wire_token="[[LEX:O0002]]", display_alias="单位1",
                         original_value="合成公司", source_ids=["b1"], mapping_version=1, aliases=["合成企业"])
    assert entry.wire_token == "[[LEX:O0002]]" and entry.aliases == ["合成企业"]


def test_entity_aliases_share_token_in_transform():
    case = {"id": "case_alias0001", "mapping_entries": [], "mapping_version": 1}
    entries = ensure_mappings(case, [
        {"field": "entity", "value": "林甲", "source_ids": ["b1"], "aliases": ["小林", "林某甲"]},
    ])
    token = entries[0]["wire_token"]
    assert entries[0]["aliases"] == ["小林", "林某甲"]
    assert transform("小林与林某甲、林甲发生争议", "pseudonymize", entries) == f"{token}与{token}、{token}发生争议"


def test_alias_conflict_skips_alias_and_keeps_two_tokens():
    orders = (
        [
            {"field": "entity", "value": "林甲", "source_ids": ["b1"], "aliases": ["林乙"]},
            {"field": "entity", "value": "林乙", "source_ids": ["b2"]},
        ],
        [
            {"field": "entity", "value": "林乙", "source_ids": ["b2"]},
            {"field": "entity", "value": "林甲", "source_ids": ["b1"], "aliases": ["林乙"]},
        ],
    )
    for facts in orders:
        case = {"id": "case_alias0002", "mapping_entries": [], "mapping_version": 1}
        entries = ensure_mappings(case, facts)
        tokens = {entry["original_value"]: entry["wire_token"] for entry in entries}
        assert tokens["林甲"] != tokens["林乙"]
        assert "林乙" not in next(entry for entry in entries if entry["original_value"] == "林甲").get("aliases", [])
        assert any(item["alias"] == "林乙" and item["reason"] == "alias_conflicts_with_other_entity"
                   for item in case["skipped_aliases"])
        replaced = transform("林甲与林乙", "pseudonymize", entries)
        assert replaced == f"{tokens['林甲']}与{tokens['林乙']}"


def test_check_claims_recognizes_polc_tokens():
    task = {"decisions": [{"fact_id": "f1", "output": "[[LEX:O0001]]与[[LEX:L0002]]签订合同"}]}
    facts = [{"id": "f1", "source_ids": ["b1"]}]
    claims = check_claims({"claims": [{"text": "[[LEX:O0001]]与[[LEX:L0002]]签订合同", "source_ids": ["f1"]}]}, task, facts)
    assert claims[0]["status"] == "source_matched"
    broken = check_claims({"claims": [{"text": "[[LEX:C0001]签订合同", "source_ids": ["f1"]}]}, task, facts)
    assert any("破损" in issue for issue in broken[0]["issues"])


def _feedback_task():
    return {"decisions": [
        {"fact_id": "f1", "output": "[[LEX:P0001]]主张工资12000元", "field": "entity"},
        {"fact_id": "f2", "output": "2024年3月1日签订合同", "field": "date"},
        {"fact_id": "f3", "output": "月工资8000元", "field": "amount"},
    ], "type": "fact_summary"}


def _feedback_facts():
    return [{"id": fact_id, "source_ids": ["b1"]} for fact_id in ("f1", "f2", "f3")]


def test_feedback_computes_unused_fact_ids_locally():
    task, facts = _feedback_task(), _feedback_facts()
    raw = {"claims": [
        {"text": "[[LEX:P0001]]主张工资12000元", "source_ids": ["f1"]},
        {"text": "2024年3月1日签订合同", "source_ids": ["f2"]},
    ]}
    claims = check_claims(raw, task, facts)
    feedback = check_cloud_feedback(raw, task, claims)
    assert feedback["unused_fact_ids"] == ["f3"]
    assert feedback["gaps"] == []
    assert feedback["feedback_issues"] == []


def test_feedback_unused_mismatch_keeps_claims():
    task, facts = _feedback_task(), _feedback_facts()
    raw = {"claims": [
        {"text": "[[LEX:P0001]]主张工资12000元", "source_ids": ["f1"]},
        {"text": "2024年3月1日签订合同", "source_ids": ["f2"]},
    ], "unused_fact_ids": ["f1"]}
    result = validate_cloud_result("fact_summary", raw, task, facts)
    assert result["unused_fact_ids"] == ["f3"]
    assert len(result["claims"]) == 2
    assert any("不一致" in issue for issue in result["feedback_issues"])


def test_feedback_gap_unknown_id_and_identifier_leak():
    task, facts = _feedback_task(), _feedback_facts()
    raw = {"claims": [{"text": "[[LEX:P0001]]主张工资12000元", "source_ids": ["f1"]}],
           "gaps": [
               {"code": "missing_field", "detail": "缺少争议发生地", "fact_ids": ["missing"]},
               {"code": "other", "detail": "联系电话13800138000", "fact_ids": ["f3"]},
           ]}
    result = validate_cloud_result("fact_summary", raw, task, facts)
    assert result["unused_fact_ids"] == ["f2", "f3"]
    assert result["gaps"] == []
    assert any("未外发" in issue for issue in result["feedback_issues"])
    assert any("直接标识" in issue for issue in result["feedback_issues"])


def test_initialize_backfills_empty_edge_model_from_env(tmp_path, monkeypatch):
    from lexaegis.storage import Store
    from lexaegis import service
    store = Store(tmp_path / "app.sqlite")
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    service.initialize(store)
    with store.transaction() as repo:
        settings = repo.get("settings")
        assert not settings.get("edge_model")
        assert settings["edge_url"] == "http://127.0.0.1:8080/v1"
        settings["edge_model"] = "already-saved"
        settings["edge_url"] = "http://127.0.0.1:11434/v1"
        repo.put("settings", settings)
    monkeypatch.setenv("LEX_EDGE_MODEL", "edge-small")
    monkeypatch.setenv("LEX_EDGE_URL", "http://127.0.0.1:8080/v1")
    service.initialize(store)
    with store.read() as repo:
        kept = repo.get("settings")
        assert kept["edge_model"] == "already-saved"
        assert kept["edge_url"] == "http://127.0.0.1:11434/v1"
    with store.transaction() as repo:
        settings = repo.get("settings")
        settings["edge_model"] = ""
        repo.put("settings", settings)
    service.initialize(store)
    with store.read() as repo:
        filled = repo.get("settings")
        assert filled["edge_model"] == "edge-small"
        assert filled["edge_url"] == "http://127.0.0.1:8080/v1"


def test_dp_budget_projection_and_real_mia_inputs():
    assert math.isclose(math.sqrt(sum(value*value for value in l2_clip([3,4],2))),2)
    one=gaussian_dp([3,4],max_norm=2,noise_multiplier=.5,seed=7)
    two=gaussian_dp([3,4],max_norm=2,noise_multiplier=.5,seed=7)
    assert one==two and one["clipped_norm"]<=2.000001
    rdp=rdp_gaussian(noise_multiplier=1.2,steps=3,orders=[2,4,8])
    assert rdp_to_epsilon(rdp,1e-5)>0
    projection=random_projection([[1,0],[0,1]],1,23)
    assert projection==random_projection([[1,0],[0,1]],1,23)
    assert mia_requires_real_outputs(None)["outcome"]=="not_applicable"


def test_frozen_attack_is_data_driven_and_rejects_local_fields():
    protocol={"kind":"candidate_set","threshold":.2,"query_budget":3}
    assert attack(protocol,{"facts":[]},[],[{"candidate_count":10}])["outcome"]=="uncertain"
    assert attack(protocol,POSITIVE_CONTROL_REQUEST,[],[])["outcome"]=="succeeded"
    with pytest.raises(ValueError):
        attack(protocol,{"mapping_entries":[]},[],[])


def test_capabilities_report_separate_axes(env):
    result=env["client"].get("/api/v1/capabilities").json()
    assert {"technical","runtime","legal","validation"} <= result.keys()
    assert result["legal"]["status"]!="available"
    assert result["validation"]["status"] == "unconfigured"
    assert result["validation"]["cloud_outbound"] == "not_verified"
    assert result["validation"]["formal_dispatch"] == "blocked"
    assert result["redteam"]["status"] == "unconfigured"
    assert result["isolation"]["status"] == "unconfigured"
    assert "未验收" in result["isolation"]["detail"]
    assert "隔离部署仍未验收" in result["validation"]["detail"]
    assert "真实云端外发仍未验收" in result["validation"]["detail"]
    assert "正式案件仍未验收" in result["validation"]["detail"]
    assert "未验证" in result["validation"]["detail"]
    assert "可能披露" in result["cloud"]["detail"]
    assert "工程基线" in result["redteam"]["detail"]

    with env["app"].state.store.transaction() as repo:
        settings = repo.get("settings")
        settings["isolation_verified"] = True
        settings["deployment_mode"] = "isolated"
        repo.put("settings", settings)
    isolated = env["client"].get("/api/v1/capabilities").json()
    assert isolated["isolation"]["status"] == "available"
    assert isolated["validation"]["status"] == "unconfigured"
    assert isolated["validation"]["cloud_outbound"] == "not_verified"
    assert isolated["validation"]["formal_dispatch"] == "blocked"
    detail = isolated["validation"]["detail"]
    assert "隔离部署已记录" in detail
    assert "真实云端外发仍未验收" in detail
    assert "正式案件仍未验收" in detail
    assert "隔离部署仍未验收" not in detail
    assert "隔离仍未验收" not in detail
    isolation_clause = next(part for part in detail.split("；") if "隔离部署" in part)
    assert "仍未验收" not in isolation_clause
    assert "未验证" in isolated["validation"]["detail"]
    assert "可能披露" in isolated["cloud"]["detail"]
    assert "工程基线" in isolated["redteam"]["detail"]


def test_capability_panel_copy_distinguishes_honesty_states():
    source = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"
    text = source.read_text(encoding="utf-8")
    assert "未验证" in text
    assert "可能披露" in text
    assert "工程基线" in text
    assert "尚未开始生成" not in text


def test_semisynthetic_scaffold_has_frozen_split_but_never_fake_labels():
    records,manifest=build_semisynthetic_manifest()
    assert len(records)==100
    assert list(manifest["split"].values()).count("development")==70
    assert list(manifest["split"].values()).count("blind")==30
    assert all(record["synthetic"] and not record["labels"] for record in records)
    assert len(validate_annotations(records))==200
    assert manifest["freeze_status"]=="unfrozen_pending_annotation"
