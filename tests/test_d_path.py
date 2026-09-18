import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from lexaegis.cloud import allowed_cloud_hosts, cloud_endpoint_allowed, wire_contract_error
from lexaegis.gateway import create_gateway
from lexaegis.util import digest, sign
from lexaegis.d_path import (
    INJURY_SUB_PURPOSE,
    LAYER_B_CLOSED,
    RELATION_SUB_PURPOSE,
    STANDBY_CLOSED_NOTE,
    UNJUDGED_COMBINATION,
    WAGE_COMP_SUB_PURPOSE,
    WALK_BATCHES,
    combination_input_hash,
    d_path_active,
    pick_walk_case,
    walk_row_status,
)
from lexaegis.disclosure import GENERAL_SUB_PURPOSE, infer_sub_purpose
from lexaegis.local_rules import decide_facts
from lexaegis.policy import assess
from lexaegis.registry import validate_pack
from lexaegis.service import resolve_dispatch_slots


def labor_pack():
    raw = json.loads((Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json").read_text(encoding="utf-8"))
    pack = validate_pack(raw)
    assert pack.dispatch_allowed is False
    return pack.model_dump()


def _ready(output, *, mode="formal", source_case_id=None, judgment=None):
    case = {
        "mode": mode, "ledger_version": 0, "mapping": {}, "mapping_entries": [],
        "source_case_id": source_case_id,
    }
    if judgment is not None:
        case["combination_judgment"] = judgment
    facts = [{"id": "f1", "confirmed": True, "stale": False, "source_ids": [], "field": "event", "value": output}]
    decisions = [{"fact_id": "f1", "output": output, "necessity": "required", "status": "ready", "forbidden": False}]
    docs = [{"status": "ready", "ir": {"needs_review": False, "blocks": []}}]
    return case, facts, decisions, docs


def test_d_path_allowlist_excludes_non_deepseek(monkeypatch):
    monkeypatch.setenv("LEX_CLOUD_PATH", "D")
    monkeypatch.setenv("LEX_CLOUD_ALLOWED_HOSTS", "api.deepseek.com,dashscope.aliyuncs.com")
    assert d_path_active()
    assert allowed_cloud_hosts() == {"api.deepseek.com"}
    assert cloud_endpoint_allowed("https://api.deepseek.com/v1/chat/completions")
    assert not cloud_endpoint_allowed("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")


def test_d_path_closes_standby(monkeypatch):
    monkeypatch.setenv("LEX_CLOUD_PATH", "D")

    class Repo:
        def get(self, *_args, **_kwargs):
            raise KeyError

    slots = resolve_dispatch_slots(Repo(), {
        "cloud_primary": {"url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-v4-flash"},
        "cloud_standby": {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen3.8-flash"},
    })
    assert STANDBY_CLOSED_NOTE in slots["standby_note"] or slots["standby_note"] == STANDBY_CLOSED_NOTE
    assert "standby" not in (slots["dual_slot"] or {})
    assert all(item.get("role") != "standby" for item in slots["authorized_recipients"])


def test_rwi_requires_explicit_sub_purpose():
    facts = [
        {"id": "f1", "field": "event", "value": "劳动者主张未支付工资并申请工伤待遇。", "confirmed": True},
    ]
    assert infer_sub_purpose(facts, "fact_summary") == GENERAL_SUB_PURPOSE
    assert infer_sub_purpose(facts, "fact_summary", RELATION_SUB_PURPOSE) == RELATION_SUB_PURPOSE
    assert infer_sub_purpose(facts, "fact_summary", WAGE_COMP_SUB_PURPOSE) == WAGE_COMP_SUB_PURPOSE
    assert infer_sub_purpose(facts, "fact_summary", INJURY_SUB_PURPOSE) == INJURY_SUB_PURPOSE


def test_w_first_version_drops_amount_and_waiting_post_date():
    pack = labor_pack()
    facts = [
        {"id": "r1", "field": "relation", "value": "[[LEX:P0001]]与[[LEX:P0002]]存在劳动关系", "confirmed": True, "source_ids": ["s1"]},
        {"id": "a1", "field": "amount", "value": "请求经济补偿12000元", "confirmed": True, "source_ids": ["s1"]},
        {"id": "d1", "field": "date", "value": "待岗通知载2023年3月1日", "confirmed": True, "source_ids": ["s1"]},
    ]
    mappings = [
        {"original_value": "甲", "wire_token": "[[LEX:P0001]]"},
        {"original_value": "乙", "wire_token": "[[LEX:P0002]]"},
    ]
    by_id = {item["fact_id"]: item for item in decide_facts(facts, pack, mappings, WAGE_COMP_SUB_PURPOSE)}
    assert not by_id["a1"]["output"]
    assert not by_id["d1"]["output"]
    assert "W 首版不算金额" in (by_id["a1"].get("reason") or "")


def test_injury_omits_medical_detail():
    pack = labor_pack()
    facts = [
        {"id": "e1", "field": "event", "value": "病历全文记载住院手术", "confirmed": True, "source_ids": ["s1"]},
        {"id": "r1", "field": "relation", "value": "[[LEX:P0001]]主张工伤待遇阶段争议", "confirmed": True, "source_ids": ["s1"]},
    ]
    mappings = [{"original_value": "甲", "wire_token": "[[LEX:P0001]]"}]
    by_id = {item["fact_id"]: item for item in decide_facts(facts, pack, mappings, INJURY_SUB_PURPOSE)}
    assert not by_id["e1"]["output"]
    assert by_id["e1"].get("forbidden") is True


def test_formal_cloud_blocks_unjudged_combination_not_demo_words():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张未支付劳动报酬。")
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert UNJUDGED_COMBINATION in result["blockers"]
    assert not any("唯一" in item or "公开获奖" in item for item in result["blockers"])
    assert result["approval_allowed"] is False


def test_formal_cloud_blocks_case_number_quasi_id():
    text = "（2024）京01民终123号维持原判。"
    case, facts, decisions, docs = _ready(text, judgment={"status": "pass", "input_hash": combination_input_hash(text, "")})
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert any("准标识" in item and "案号" in item for item in result["blockers"])


def test_demo_combination_still_uses_pack_terms_only():
    case, facts, decisions, docs = _ready("该岗位为唯一夜班检修员并公开获奖。", mode="demo")
    result = assess(case, {"forbidden_terms": []}, facts, decisions, docs, [], "mock")
    assert UNJUDGED_COMBINATION not in result["blockers"]
    assert not any("组合线索" in item for item in result["blockers"])


def test_layer_b_closed_blocks_send_not_local():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。", source_case_id="LA-005")
    cloud = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert LAYER_B_CLOSED in cloud["blockers"]
    local = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "local")
    assert LAYER_B_CLOSED not in local["blockers"]


def test_allowlist_only_deepseek_is_d_path(monkeypatch):
    monkeypatch.delenv("LEX_CLOUD_PATH", raising=False)
    monkeypatch.delenv("LEX_CLOUD_D_PATH", raising=False)
    monkeypatch.delenv("LEX_CLOUD_PILOT_PATH", raising=False)
    monkeypatch.setenv("LEX_CLOUD_ALLOWED_HOSTS", "api.deepseek.com")
    assert d_path_active()
    assert allowed_cloud_hosts() == {"api.deepseek.com"}
    assert not cloud_endpoint_allowed("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions")
    assert not cloud_endpoint_allowed("https://api.openai.com/v1/chat/completions")


def test_wage_injury_words_do_not_auto_switch():
    pack = labor_pack()
    fact = {
        "id": "a1", "field": "amount", "value": "工资12000元并提及工伤待遇",
        "confirmed": True, "source_ids": ["s1"],
    }
    general = decide_facts([fact], pack, [], GENERAL_SUB_PURPOSE)[0]
    assert "12000" in (general["output"] or "")
    wage = decide_facts([fact], pack, [], WAGE_COMP_SUB_PURPOSE)[0]
    assert not wage["output"]
    injury_fact = {
        "id": "e1", "field": "event", "value": "病历全文记载住院手术",
        "confirmed": True, "source_ids": ["s1"],
    }
    general_med = decide_facts([injury_fact], pack, [], GENERAL_SUB_PURPOSE)[0]
    assert general_med["output"]
    injury = decide_facts([injury_fact], pack, [], INJURY_SUB_PURPOSE)[0]
    assert not injury["output"]


def test_w_limitation_stays_off_wire():
    pack = labor_pack()
    facts = [{
        "id": "e1", "field": "event", "value": "劳动者主张未超过仲裁时效",
        "confirmed": True, "source_ids": ["s1"],
    }]
    decision = decide_facts(facts, pack, [], WAGE_COMP_SUB_PURPOSE)[0]
    assert not decision["output"]
    assert "期限" in (decision.get("reason") or "")


def test_uncertain_combination_is_not_resisted():
    text = "[[LEX:P0001]]主张解除。"
    case, facts, decisions, docs = _ready(
        text,
        judgment={"outcome": "uncertain", "status": "pass", "input_hash": combination_input_hash(text, "")},
    )
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert UNJUDGED_COMBINATION in result["blockers"]


def test_quasi_ids_block_that_case_only():
    dirty = "（2024）京01民终1号维持原判。"
    clean = "[[LEX:P0001]]主张解除劳动合同。"
    dirty_case, dirty_facts, dirty_decisions, dirty_docs = _ready(
        dirty, judgment={"status": "pass", "input_hash": combination_input_hash(dirty, "")},
    )
    clean_case, clean_facts, clean_decisions, clean_docs = _ready(
        clean, judgment={"status": "pass", "input_hash": combination_input_hash(clean, "")},
    )
    pack = {"forbidden_terms": [], "risk_weights": {}}
    dirty_risk = assess(dirty_case, pack, dirty_facts, dirty_decisions, dirty_docs, [], "cloud")
    clean_risk = assess(clean_case, pack, clean_facts, clean_decisions, clean_docs, [], "cloud")
    assert any("准标识" in item and "案号" in item for item in dirty_risk["blockers"])
    assert not any("准标识" in item for item in clean_risk["blockers"])


def test_demo_words_are_not_formal_quasi_ids():
    from lexaegis.d_path import quasi_identifier_hits
    assert quasi_identifier_hits("该岗位为唯一夜班检修员并公开获奖。") == []


def test_url_mentions_are_not_runtime_quasi_ids():
    from lexaegis.d_path import quasi_identifier_hits
    text = "工作副本来自裁判文书网，另见 https://example.invalid/doc 与 pkulaw.com。"
    assert quasi_identifier_hits(text) == []
    case, facts, decisions, docs = _ready(
        text, judgment={"status": "pass", "input_hash": combination_input_hash(text, "")},
    )
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
    assert not any("公开链接" in item for item in result["blockers"])
    assert not any("准标识" in item for item in result["blockers"])


def test_formal_mock_still_forbidden():
    case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。")
    result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "mock")
    assert "正式案件不能使用模拟调用" in result["blockers"]


def test_demo_exception_not_on_formal_la_or_smp():
    for source in ("LA-001", "LA-005", "SMP-001"):
        case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。", source_case_id=source)
        result = assess(case, {"forbidden_terms": [], "risk_weights": {}}, facts, decisions, docs, [], "cloud")
        assert result["demo_exception"] is False
        assert result["approval_allowed"] is False
    demo_case, facts, decisions, docs = _ready("[[LEX:P0001]]主张解除。", mode="demo")
    demo = assess(demo_case, {"forbidden_terms": []}, facts, decisions, docs, [], "mock")
    assert demo["demo_exception"] is True


def test_pick_walk_case_prefers_path_a_not_path_b():
    cases = [
        {"id": "b", "name": "PILOT REST-1 Path B LA-002"},
        {"id": "a", "name": "PILOT REST-1 Path A LA-002"},
        {"id": "r", "name": "PILOT CAL-1 reextract LA-001"},
        {"id": "empty", "name": "PILOT CAL-1 Path A LA-001"},
    ]
    facts = {"b": 7, "a": 38, "r": 77, "empty": 0}
    assert pick_walk_case(cases, "LA-002", facts)["id"] == "a"
    assert pick_walk_case(cases, "LA-001", facts)["id"] == "r"
    assert pick_walk_case(cases, "SMP-005", facts) is None


def test_ten_case_synthetic_walk_never_approves():
    pack = labor_pack()
    mappings = [{"original_value": "甲", "wire_token": "[[LEX:P0001]]"}]
    rows = []
    for batch in WALK_BATCHES:
        facts = [
            {"id": "r1", "field": "relation", "value": "[[LEX:P0001]]与相对方存在劳动关系", "confirmed": True, "stale": False, "source_ids": []},
            {"id": "e1", "field": "event", "value": "[[LEX:P0001]]主张争议经过", "confirmed": True, "stale": False, "source_ids": []},
        ]
        if batch["case_id"] == "LA-005":
            facts.append({"id": "a1", "field": "amount", "value": "12000元", "confirmed": True, "stale": False, "source_ids": []})
        if batch["case_id"] in {"SMP-004", "SMP-005"}:
            facts.append({"id": "m1", "field": "event", "value": "病历全文", "confirmed": True, "stale": False, "source_ids": []})
        decisions = decide_facts(facts, pack, mappings, batch["sub_purpose"] or GENERAL_SUB_PURPOSE)
        case = {
            "mode": "formal", "ledger_version": 0, "mapping_entries": mappings,
            "source_case_id": batch["case_id"],
        }
        docs = [{"status": "ready", "ir": {"needs_review": False, "blocks": []}}]
        risk = assess(case, pack, facts, decisions, docs, [], batch["transport"])
        status = walk_row_status(batch, risk)
        rows.append({"case_id": batch["case_id"], "status": status, "approval_allowed": risk["approval_allowed"]})
        assert status == batch["expected_status"]
        if batch["transport"] != "local":
            assert risk["approval_allowed"] is False
        if batch["case_id"] == "LA-005":
            assert not next(item for item in decisions if item["fact_id"] == "a1")["output"]
    assert len(rows) == 10
    assert all(row["approval_allowed"] is False for row in rows if row["case_id"] not in {"LA-002", "SMP-004", "SMP-005"})


def test_pack_stays_draft_after_rwi_rules():
    pack = labor_pack()
    ids = {item["id"] for item in pack["disclosure_rules"]}
    assert {"r_entity", "w_amount", "i_evidence"} <= ids
    assert pack["dispatch_allowed"] is False
    assert pack["status"] == "draft"


def test_w_wire_contract_stays_id_text_field():
    pack = labor_pack()
    facts = [
        {"id": "r1", "field": "relation", "value": "[[LEX:P0001]]与[[LEX:P0002]]存在劳动关系", "confirmed": True, "source_ids": ["s1"]},
        {"id": "a1", "field": "amount", "value": "请求经济补偿12000元", "confirmed": True, "source_ids": ["s1"]},
    ]
    decisions = decide_facts(facts, pack, [], WAGE_COMP_SUB_PURPOSE)
    wire = {
        "contract_version": 2,
        "task": {"id": "fact_summary", "version": "2.0"},
        "facts": [{"id": item["fact_id"], "text": item["output"], "field": item["field"]} for item in decisions if item["output"]],
    }
    assert wire_contract_error(wire) is None
    assert all(set(item) <= {"id", "text", "field"} for item in wire["facts"])
    assert not any("12000" in (item.get("text") or "") for item in wire["facts"])


def test_non_d_endpoint_403_when_allowlist_tightened(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_CLOUD_ALLOWED_HOSTS", "api.deepseek.com")
    secret = "unit-test-secret-32-characters-long"
    request = {
        "request_id": "req_d_path",
        "case_id": "case_d_path",
        "task_id": "task_d_path",
        "mode": "demo",
        "transport": "cloud",
        "target": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "wire_payload": {
            "contract_version": 2,
            "task": {"id": "fact_summary", "version": "2.0"},
            "facts": [{"id": "f1", "text": "[[LEX:P0001]]", "field": "entity"}],
        },
        "body": {"model": "qwen3.8-flash", "messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "{}"}]},
        "dependencies": {
            "dual_slot": {
                "primary": {
                    "host": "dashscope.aliyuncs.com",
                    "target": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    "model": "qwen3.8-flash",
                }
            }
        },
        "policy": {"approved_for_dispatch": True, "demo_exception": True, "risk_completion": "complete"},
    }
    approval = {
        "actor": "tester",
        "actor_role": "approver",
        "request_hash": digest(request),
        "dependencies": request["dependencies"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    content = {"request": request, "approval": approval}
    envelope = {**content, "signature": sign(content, secret)}
    app = create_gateway(tmp_path / "gw-d-path", secret=secret)
    with TestClient(app) as client:
        response = client.post("/dispatch", json=envelope)
    assert response.status_code == 403
    assert "allowlist" in str(response.json().get("detail") or "").lower()
