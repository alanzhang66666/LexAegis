"""Tests for the non-authoritative gate experience projection."""
from lexaegis.gate_experience import summarize_gate_decision


def test_groups_blockers_without_losing_gate_details():
    decision = {"approval_eligible": False, "hits": [
        {"gate_id": "G9", "reason_code": "isolation_receipt_missing",
         "message": "missing isolation", "kind": "engineering"},
        {"gate_id": "G3", "message": "provider review missing", "kind": "verification"},
        {"gate_id": "G7", "message": "combination risk", "kind": "prohibition"},
    ]}
    result = summarize_gate_decision(decision)
    assert result["state"] == "blocked"
    assert result["authoritative"] is False
    assert [g["area"] for g in result["groups"]] == [
        "environment", "governance", "request"]
    assert [g["items"][0]["gate_id"] for g in result["groups"]] == [
        "G9", "G3", "G7"]


def test_ready_requires_authoritative_eligibility_and_no_hits():
    assert summarize_gate_decision({"approval_eligible": True, "hits": []})["state"] == "ready_for_approval"
    assert summarize_gate_decision({"approval_eligible": False, "hits": []})["state"] == "blocked"
    assert summarize_gate_decision({"approval_eligible": True, "hits": [
        {"gate_id": "G-product", "message": "blocked"}]})["state"] == "blocked"


def test_unknown_gate_fails_into_system_group():
    result = summarize_gate_decision({"hits": [{"gate_id": "G999", "message": "unknown"}]})
    assert result["groups"][0]["area"] == "system"
    assert result["groups"][0]["items"][0]["gate_id"] == "G999"
