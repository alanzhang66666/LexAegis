from lexaegis.policy import assess, ledger_usage, resolve_disclosure_budget
from lexaegis.service import anchor_index


def _ready(output):
    case = {"mode": "demo", "ledger_version": 0, "mapping": {}, "mapping_entries": []}
    facts = [{"id": "f1", "confirmed": True, "stale": False, "source_ids": []}]
    decisions = [{"fact_id": "f1", "output": output, "necessity": "required", "status": "ready", "forbidden": False}]
    docs = [{"status": "ready", "ir": {"needs_review": False, "blocks": []}}]
    return case, facts, decisions, docs


def test_combination_block_reads_pack_forbidden_terms():
    case, facts, decisions, docs = _ready("该岗位为唯一夜班检修员并公开获奖。")
    blocked = assess(case, {"forbidden_terms": ["唯一", "公开获奖"]}, facts, decisions, docs, [], "mock")
    assert "组合线索风险：唯一岗位或公开事件仍保留" in blocked["blockers"]
    open_pack = assess(case, {"forbidden_terms": []}, facts, decisions, docs, [], "mock")
    assert not any("组合线索" in item for item in open_pack["blockers"])


def test_empty_forbidden_terms_do_not_invent_combination_block():
    case, facts, decisions, docs = _ready("该岗位为唯一夜班检修员并公开获奖。")
    result = assess(case, {}, facts, decisions, docs, [], "mock")
    assert not any("组合线索" in item for item in result["blockers"])


def test_combination_block_message_uses_matched_terms():
    case, facts, decisions, docs = _ready("材料提及内部代号赤狐。")
    result = assess(case, {"forbidden_terms": ["赤狐"]}, facts, decisions, docs, [], "mock")
    assert any("组合线索" in item and "赤狐" in item for item in result["blockers"])
    assert "组合线索风险：唯一岗位或公开事件仍保留" not in result["blockers"]


def test_disclosure_budget_blocks_when_ledger_chars_or_entries_exceed(monkeypatch):
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_CHARS", "40")
    monkeypatch.delenv("LEX_DISCLOSURE_BUDGET_ENTRIES", raising=False)
    case, facts, decisions, docs = _ready("短文本")
    ledger = [{"request": {"wire_payload": {"contract_version": 2, "facts": [{"id": "a", "text": "x" * 80}]}}}]
    result = assess(case, {"forbidden_terms": []}, facts, decisions, docs, ledger, "mock")
    assert "跨轮外发已超过工程预算（字符或条数）" in result["blockers"]
    assert result["approval_allowed"] is False


def test_disclosure_budget_blocks_entry_count(monkeypatch):
    monkeypatch.delenv("LEX_DISCLOSURE_BUDGET_CHARS", raising=False)
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_ENTRIES", "1")
    case, facts, decisions, docs = _ready("短文本")
    ledger = [{"request": {"wire_payload": {"facts": [{"text": "a"}]}}}]
    result = assess(case, {"forbidden_terms": []}, facts, decisions, docs, ledger, "mock")
    assert "跨轮外发已超过工程预算（字符或条数）" in result["blockers"]


def test_resolve_disclosure_budget_defaults_are_conservative(monkeypatch):
    monkeypatch.delenv("LEX_DISCLOSURE_BUDGET_CHARS", raising=False)
    monkeypatch.delenv("LEX_DISCLOSURE_BUDGET_ENTRIES", raising=False)
    assert resolve_disclosure_budget() == (50000, 20)
    assert ledger_usage([]) == (0, 0)


def test_assess_treats_missing_ir_as_pending_parse():
    case, facts, decisions, _ = _ready("短文本")
    result = assess(case, {"forbidden_terms": []}, facts, decisions, [{"status": "pending", "ir": None}], [], "mock")
    assert "材料解析或 OCR 复核未完成" in result["blockers"]
    assert result["approval_allowed"] is False


def test_anchor_index_skips_unparsed_documents():
    class Repo:
        def list(self, kind, case_id):
            return [{"ir": None, "status": "pending"}, {"ir": {"blocks": [{"id": "b1", "text": "x"}]}}]

    assert list(anchor_index(Repo(), "case_x")) == ["b1"]


def test_resolve_disclosure_budget_ignores_invalid_or_nonpositive_env(monkeypatch):
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_CHARS", "not-a-number")
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_ENTRIES", "0")
    assert resolve_disclosure_budget() == (50000, 20)
    assert resolve_disclosure_budget(chars=12345, entries=3) == (12345, 3)
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_CHARS", "-5")
    monkeypatch.setenv("LEX_DISCLOSURE_BUDGET_ENTRIES", "abc")
    assert resolve_disclosure_budget(chars=8000, entries=4) == (8000, 4)
    case, facts, decisions, docs = _ready("短文本")
    result = assess(case, {"forbidden_terms": []}, facts, decisions, docs, [], "mock")
    assert "跨轮外发已超过工程预算（字符或条数）" not in result["blockers"]
