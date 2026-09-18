"""D-path pilot helpers. Not a send authorization."""
import os
import re
from urllib.parse import urlparse

from .util import digest

D_PATH_HOST = "api.deepseek.com"
STANDBY_CLOSED_NOTE = "D 路径试点关闭备用槽，仅 api.deepseek.com 主槽纳入批准目标。境内与国际百炼均不纳入授权接收方。"
UNJUDGED_COMBINATION = "正式组合风险未获得有效判断，相关发送不放行"
LAYER_B_CLOSED = "层 B 登记为暂不开放，不得发送"
QUASI_ID_BLOCKER_PREFIX = "组合线索仍含准标识："

RELATION_SUB_PURPOSE = "劳动关系经过与争议状态"
WAGE_COMP_SUB_PURPOSE = "欠薪、解除与经济补偿经过"
INJURY_SUB_PURPOSE = "工伤待遇争议经过"
WAGE_SUB_PURPOSE = WAGE_COMP_SUB_PURPOSE

LAYER_B_CLOSED_IDS = frozenset({
    "LA-002", "LA-003", "LA-004", "LA-005",
    "SMP-001", "SMP-002", "SMP-003", "SMP-004", "SMP-005",
})

INJURY_OMIT_MARKERS = ("病历全文", "住院病历", "住院病案", "出院小结", "病案首页", "精细诊断", "诊断证明", "影像报告")
LIMITATION_MARKERS = ("诉讼时效", "仲裁时效", "时效期间", "时效中断", "时效中止", "超过仲裁时效")
W_OFF_WIRE_FIELDS = frozenset({"amount", "wage_base"})

_CASE_NUMBER = re.compile(r"[（(]\d{4}[）)].{0,24}号|(?:LA|SMP)-\d{3}")
_JOB = re.compile(r"(?:职务|岗位为|担任)[^。]{0,16}(?:总经理|副总经理|董事长|法定代表人|财务总监|车间主任)")
_AMOUNT = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+\.\d{2}|\d{5,})(?:\.\d{1,2})?(?:元|万元)")
_YEAR = re.compile(r"((?:19|20)\d{2})")

WALK_BATCHES = (
    {"case_id": "LA-002", "batch": 0, "sub_purpose": None, "transport": "local", "expected_status": "local_only"},
    {"case_id": "LA-005", "batch": 1, "sub_purpose": WAGE_COMP_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "LA-001", "batch": 2, "sub_purpose": RELATION_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "LA-003", "batch": 2, "sub_purpose": RELATION_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "LA-004", "batch": 2, "sub_purpose": RELATION_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "SMP-001", "batch": 3, "sub_purpose": INJURY_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "SMP-002", "batch": 3, "sub_purpose": INJURY_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "SMP-003", "batch": 3, "sub_purpose": INJURY_SUB_PURPOSE, "transport": "cloud", "expected_status": "blocked"},
    {"case_id": "SMP-004", "batch": 4, "sub_purpose": INJURY_SUB_PURPOSE, "transport": "local", "expected_status": "local_only"},
    {"case_id": "SMP-005", "batch": 4, "sub_purpose": INJURY_SUB_PURPOSE, "transport": "local", "expected_status": "local_only"},
)


def d_path_flag():
    path = (os.getenv("LEX_CLOUD_PILOT_PATH") or os.getenv("LEX_CLOUD_PATH") or "").strip().upper()
    return path == "D" or os.getenv("LEX_CLOUD_D_PATH") == "1"


def tightened_allowlist_hosts():
    raw = os.getenv("LEX_CLOUD_ALLOWED_HOSTS")
    if raw is None:
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def d_path_active():
    """True for the D single-recipient pilot, or when the allowlist is only api.deepseek.com."""
    if d_path_flag():
        return True
    hosts = tightened_allowlist_hosts()
    return hosts == {D_PATH_HOST}


def layer_b_closed(stable_id):
    return stable_id in LAYER_B_CLOSED_IDS


def combination_input_hash(emitted, ledger_text="", prompt=""):
    return digest({"prompt": prompt or "", "emitted": emitted or "", "ledger": ledger_text or ""})


def same_recipient_ledger(ledger, recipient=None):
    if not recipient:
        return list(ledger or [])
    target = (recipient.get("target") or "").rstrip("/")
    host = (recipient.get("host") or "").lower()
    matched = []
    for item in ledger or []:
        request = item.get("request") if isinstance(item, dict) else {}
        request = request or {}
        item_target = (request.get("target") or "").rstrip("/")
        item_host = (urlparse(item_target).hostname or "").lower()
        if target and item_target == target:
            matched.append(item)
        elif host and item_host == host:
            matched.append(item)
    return matched


def ledger_corpus(ledger):
    parts = []
    for item in ledger or []:
        request = item.get("request") or {}
        payload = request.get("wire_payload")
        if payload is None:
            payload = request
        if isinstance(payload, dict):
            for fact in payload.get("facts") or []:
                if isinstance(fact, dict) and fact.get("text"):
                    parts.append(str(fact["text"]))
            messages = ((request.get("body") or {}).get("messages") or [])
            for message in messages:
                if isinstance(message, dict) and message.get("content"):
                    parts.append(str(message["content"]))
        elif payload:
            parts.append(str(payload))
    return "\n".join(parts)


def quasi_identifier_hits(text):
    """Formal quasi-ids on the candidate corpus.

    Missing official publication URL is a legal worksheet item, not this list.
    URL / 裁判文书网 / 法宝 mentions are not runtime blockers. DEMO-02 words
    唯一/公开获奖 are not this list either.
    """
    blob = text or ""
    hits = []
    if _CASE_NUMBER.search(blob):
        hits.append("案号")
    if _JOB.search(blob):
        hits.append("过精准职务")
    if _AMOUNT.search(blob):
        hits.append("过精准金额")
    return hits


def combination_judgment_valid(judgment, expected_hash):
    if not isinstance(judgment, dict):
        return False
    outcome = judgment.get("outcome")
    if outcome in {"uncertain", "not_run", "unknown", "succeeded"}:
        return False
    if outcome != "resisted" and judgment.get("status") != "pass":
        return False
    bound = judgment.get("input_hash") or judgment.get("request_hash")
    return bound == expected_hash


def combination_blockers(case, emitted, ledger, *, prompt="", recipient=None):
    """Formal combination gate on the frozen request. Uncertain is not resisted."""
    blockers = []
    scoped = same_recipient_ledger(ledger, recipient)
    ledger_text = ledger_corpus(scoped)
    corpus = "\n".join(part for part in (prompt, emitted, ledger_text) if part)
    hits = quasi_identifier_hits(corpus)
    if hits:
        blockers.append(QUASI_ID_BLOCKER_PREFIX + "、".join(hits))
    judgment = case.get("combination_judgment") if isinstance(case, dict) else None
    expected = combination_input_hash(emitted, ledger_text, prompt)
    if not combination_judgment_valid(judgment, expected):
        blockers.append(UNJUDGED_COMBINATION)
    return blockers


def layer_b_blockers(case):
    stable_id = None
    if isinstance(case, dict):
        stable_id = case.get("source_case_id") or case.get("stable_id")
    if layer_b_closed(stable_id):
        return [LAYER_B_CLOSED]
    return []


def year_inverted(text):
    years = [int(item) for item in _YEAR.findall(text or "")]
    return len(years) >= 2 and years[0] > years[-1]


def walk_row_status(batch, risk):
    if (batch or {}).get("transport") == "local":
        return "local_only"
    if (risk or {}).get("approval_allowed"):
        return "candidate"
    return "blocked"


_SOURCE_IN_NAME = re.compile(r"\b((?:LA|SMP)-\d{3})\b")


def source_id_from_name(name):
    match = _SOURCE_IN_NAME.search(name or "")
    return match.group(1) if match else None


def _fact_count(item):
    if item is None:
        return 0
    if isinstance(item, int):
        return item
    return len(item)


def pick_walk_case(cases, source_id, facts_by_case=None):
    """Prefer Path A / reextract with the most facts. Do not invent a case."""
    facts_by_case = facts_by_case or {}
    ranked = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        name = case.get("name") or ""
        linked = case.get("source_case_id") or case.get("stable_id")
        if linked != source_id and source_id_from_name(name) != source_id:
            continue
        n_facts = _fact_count(facts_by_case.get(case.get("id")))
        path_b = "Path B" in name
        path_a = "Path A" in name or "reextract" in name
        score = (0 if path_b else 1, 1 if path_a else 0, n_facts)
        ranked.append((score, case))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def public_walk_row(batch, risk, extra=None):
    """Counts and status only. No party names, case numbers, or fact text."""
    row = {
        "case_id": (batch or {}).get("case_id"),
        "batch": (batch or {}).get("batch"),
        "transport": (batch or {}).get("transport"),
        "sub_purpose": (batch or {}).get("sub_purpose"),
        "status": walk_row_status(batch, risk),
        "approval_allowed": bool((risk or {}).get("approval_allowed")),
        "n_blockers": len((risk or {}).get("blockers") or []),
        "demo_exception": bool((risk or {}).get("demo_exception")),
        "send": "not_called",
        "http_send": 0,
    }
    extra = extra or {}
    for key in (
        "n_facts", "n_confirmed", "n_outputs", "n_wire", "approve_http",
        "pack_id", "result", "demo_exception",
    ):
        if key in extra:
            row[key] = extra[key]
    return row
