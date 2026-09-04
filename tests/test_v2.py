import math

import pytest

from lexaegis.attacks import evaluate as attack
from lexaegis.contracts import MappingEntry
from lexaegis.detection import detect_text, merge_overlaps, risk_signals
from lexaegis.dataset import build_semisynthetic_manifest, validate_annotations
from lexaegis.experiments import gaussian_dp, l2_clip, mia_requires_real_outputs, random_projection, rdp_gaussian, rdp_to_epsilon
from lexaegis.registry import validate_pack
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


def test_local_timeline_extends_without_dispatch(env):
    case,document,fact=formal_material(env)
    result=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"task_type":"timeline","transport":"local"})
    assert result.status_code==200
    task=result.json()
    assert task["status"]=="complete" and task["request"] is None
    assert task["artifact"]["provenance"]=="local_deterministic"


def test_wire_payload_excludes_local_only_data(env):
    case=env["client"].post("/api/v1/demos",json={"scenario":"success"}).json()
    task=env["client"].post(f"/api/v1/cases/{case['id']}/tasks",json={"transport":"mock"}).json()
    evaluated=env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    wire=evaluated["request"]["wire_payload"]
    assert set(wire)=={"contract_version","task","facts"}
    assert "林澄" not in str(wire) and "mapping" not in str(wire).lower()
    assert "[[LEX:P0001]]" in str(wire)


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
    assert attack(protocol,{"facts":[]},[],[{"candidate_count":10}])["outcome"]=="resisted"
    assert attack(protocol,{"facts":[]},[],[{"candidate_count":2}])["outcome"]=="succeeded"
    with pytest.raises(ValueError):
        attack(protocol,{"mapping_entries":[]},[],[])


def test_capabilities_report_separate_axes(env):
    result=env["client"].get("/api/v1/capabilities").json()
    assert {"technical","runtime","legal","validation"} <= result.keys()
    assert result["legal"]["status"]!="available"


def test_semisynthetic_scaffold_has_frozen_split_but_never_fake_labels():
    records,manifest=build_semisynthetic_manifest()
    assert len(records)==100
    assert list(manifest["split"].values()).count("development")==70
    assert list(manifest["split"].values()).count("blind")==30
    assert all(record["synthetic"] and not record["labels"] for record in records)
    assert len(validate_annotations(records))==200
    assert manifest["freeze_status"]=="unfrozen_pending_annotation"
