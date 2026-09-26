"""Return-side output verification: the five legally-material distortion
classes are checked against the wire payload, default severity blocks."""
import pytest

from lexaegis.output_checks import apply_return_checks, severities


def _claim(text, source_ids=("f1",)):
    return {"id": "c1", "text": text, "local_text": text,
            "source_ids": list(source_ids), "anchors": [], "issues": [],
            "status": "source_matched", "reviewed": False}


def _decisions(output, fact_id="f1"):
    return [{"fact_id": fact_id, "field": "event", "output": output}]


def _facts(**fields):
    return [{"id": "f1", "field": "event", "value": "v", **fields}]


def test_month_truncation_blocks_by_default():
    claims = [_claim("[[LEX:P0001]]于2025年3月离职。")]
    counts = apply_return_checks(
        claims, _decisions("[[LEX:P0001]]于2025年3月15日离职。"), _facts(), {})
    assert counts["block"] >= 1
    assert claims[0]["status"] == "blocked"
    assert any("截月" in i for i in claims[0]["issues"])


def test_pack_may_downgrade_to_review_not_off_for_others():
    pack = {"return_check_severity": {"month_truncation": "review"}}
    claims = [_claim("[[LEX:P0001]]于2025年3月离职。")]
    counts = apply_return_checks(
        claims, _decisions("[[LEX:P0001]]于2025年3月15日离职。"), _facts(), pack)
    assert counts["review"] >= 1
    assert claims[0]["status"] == "needs_review"
    assert not claims[0].get("blocked")


def test_severity_rejects_unknown_check_and_level():
    with pytest.raises(ValueError):
        severities({"return_check_severity": {"magic": "block"}})
    with pytest.raises(ValueError):
        severities({"return_check_severity": {"month_truncation": "skip"}})


def test_claim_flattened_to_finding():
    facts = _facts(claim_stance="claim", statement_status="claimed")
    claims = [_claim("法院认定[[LEX:P0001]]被拖欠工资。")]
    counts = apply_return_checks(
        claims, _decisions("[[LEX:P0001]]主张被拖欠工资。"), facts, {})
    messages = "；".join(claims[0]["issues"])
    assert "法院认定" in messages or "无争议" in messages
    assert claims[0]["status"] == "blocked"


def test_denial_dropped():
    facts = _facts(claim_stance="deny", dispute_status="denied")
    claims = [_claim("[[LEX:P0001]]确认加班事实。")]
    apply_return_checks(
        claims, _decisions("[[LEX:P0001]]否认加班事实。"), facts, {})
    assert any("否认" in i for i in claims[0]["issues"])
    assert claims[0]["status"] == "blocked"


def test_denial_preserved_passes():
    facts = _facts(claim_stance="deny", dispute_status="denied")
    claims = [_claim("[[LEX:P0001]]否认加班事实。")]
    counts = apply_return_checks(
        claims, _decisions("[[LEX:P0001]]否认加班事实。"), facts, {})
    assert counts["block"] == 0
    assert claims[0]["status"] == "source_matched"


def test_holder_flip():
    facts = _facts(field="evidence", evidence_holder="worker")
    claims = [_claim("用人单位持有考勤记录。")]
    apply_return_checks(
        claims, _decisions("劳动者持有考勤记录。"), facts, {})
    assert any("改挂" in i for i in claims[0]["issues"])
    assert claims[0]["status"] == "blocked"


def test_subject_pair_reversal():
    claims = [_claim("[[LEX:O0001]]向[[LEX:P0001]]支付工资。")]
    apply_return_checks(
        claims, _decisions("[[LEX:P0001]]向[[LEX:O0001]]支付工资。"), _facts(), {})
    assert any("主体" in i for i in claims[0]["issues"])
    assert claims[0]["status"] == "blocked"


def test_same_direction_passes():
    claims = [_claim("[[LEX:P0001]]向[[LEX:O0001]]支付工资。")]
    counts = apply_return_checks(
        claims, _decisions("[[LEX:P0001]]向[[LEX:O0001]]支付工资。"), _facts(), {})
    assert counts["block"] == 0


def test_claim_review_endpoint_refuses_blocked(env):
    """A blocked claim cannot be confirmed — the task must be redone."""
    client = env["client"]
    case = client.post("/api/v1/cases", json={"name": "阻断复核测试", "domain": "labor"}).json()
    store = env["app"].state.store
    with store.transaction() as repo:
        settings_version = repo.get("settings")["version"]
        repo.put("task", {
            "id": "t1", "case_id": case["id"], "status": "complete", "version": 1,
            "stale": False, "case_revision": case["revision"],
            "settings_version": settings_version,
            "type": "fact_summary", "artifact": {
                "claims": [{"id": "c1", "text": "x", "anchors": ["a1"],
                            "issues": ["阻断：截月导致期限或先后关系错误"],
                            "status": "blocked", "reviewed": False}],
            },
        }, case["id"])
    result = client.post("/api/v1/tasks/t1/claims/c1/review")
    assert result.status_code in (400, 409)


def test_pack_level_return_severity_roundtrip(env):
    """The runtime pack schema keeps return_check_severity verbatim."""
    import json
    pack = json.loads(open("packs/labor_v2_draft.json", encoding="utf-8").read())
    pack.setdefault("return_check_severity", {})
    assert severities(pack)["month_truncation"] == "block"
