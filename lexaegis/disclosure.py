"""Bounded disclosure candidates. Draft legal overlay, not published law."""
import re

from .contracts import ConfidentialityRecord, ProcessingBasis
from .policy import registered_name_residuals, transform

from .d_path import (
    INJURY_OMIT_MARKERS,
    INJURY_SUB_PURPOSE,
    LIMITATION_MARKERS,
    RELATION_SUB_PURPOSE,
    W_OFF_WIRE_FIELDS,
    WAGE_COMP_SUB_PURPOSE,
    year_inverted,
)

GUIDE_VERSION = "G-2026-09-12-v1.0"
GENERAL_SUB_PURPOSE = "劳动争议文书事实保真整理"
OVERTIME_SUB_PURPOSE = "核对加班"
CORE_FACT_SUMMARY_PURPOSES = frozenset({
    GENERAL_SUB_PURPOSE, RELATION_SUB_PURPOSE, WAGE_COMP_SUB_PURPOSE, INJURY_SUB_PURPOSE,
})

OVERTIME_FIELDS = frozenset({
    "claim_stance", "day_nature", "overtime_hours", "wage_base", "evidence_holder",
})
OVERTIME_ATTRS = (
    "claim_stance", "day_nature", "hours", "wage_base", "evidence_holder", "evidence_attribution",
)
CANDIDATE_KINDS = ("original_precision", "tokenize", "moderate_generalize", "delete")
KIND_TO_TRANSFORM = {
    "original_precision": "keep",
    "tokenize": "pseudonymize",
    "moderate_generalize": "generalize",
    "delete": "delete",
}
TRANSFORM_TO_KIND = {value: key for key, value in KIND_TO_TRANSFORM.items()}
UNKNOWN = {None, "", "unknown"}
SENSITIVITY_NOTE = "清单类别映射为工程对照，非正式法源"
SENSITIVITY_ALIASES = {
    "必须保留": "must_keep",
    "条件保留": "conditional_keep",
    "必须保留或条件保留": "keep_or_conditional",
    "假名化保留": "pseudonymize_keep",
    "默认删除": "default_delete",
    "禁止外发": "forbid_outbound",
    "转人工": "human_review",
    "must_keep": "must_keep",
    "conditional_keep": "conditional_keep",
    "keep_or_conditional": "keep_or_conditional",
    "pseudonymize_keep": "pseudonymize_keep",
    "default_delete": "default_delete",
    "forbid_outbound": "forbid_outbound",
    "human_review": "human_review",
}
SENSITIVITY_OVERLAY = {
    "must_keep": {"necessity": "required", "transform": "keep", "forbidden": False, "cloud_eligible": True},
    "conditional_keep": {"necessity": "conditional", "transform": "keep", "forbidden": False, "cloud_eligible": True},
    "keep_or_conditional": {
        "necessity": "uncertain", "transform": "delete", "forbidden": False, "cloud_eligible": False, "status": "review",
    },
    "pseudonymize_keep": {"necessity": "conditional", "transform": "pseudonymize", "forbidden": False, "cloud_eligible": True},
    "default_delete": {"necessity": "unnecessary", "transform": "delete", "forbidden": False, "cloud_eligible": False},
    "forbid_outbound": {"necessity": "unnecessary", "transform": "delete", "forbidden": True, "cloud_eligible": False},
    "human_review": {
        "necessity": "uncertain", "transform": "delete", "forbidden": False, "cloud_eligible": False, "status": "review",
    },
}
DAY_NATURE_VALUES = {
    "weekday": "weekday", "工作日": "weekday",
    "rest_day": "rest_day", "休息日": "rest_day",
    "holiday": "holiday", "节假日": "holiday", "法定节假日": "holiday",
}
CLAIM_VALUES = {
    "claim": "claim", "主张": "claim",
    "deny": "deny", "否认": "deny",
    "hold_evidence": "hold_evidence", "持有证据": "hold_evidence",
}
STATEMENT_VALUES = {
    "claimed": "claimed", "主张": "claimed",
    "denied": "denied", "否认": "denied",
    "admitted": "admitted", "承认": "admitted", "认可": "admitted",
    "court_found": "court_found", "法院认定": "court_found",
    "document_recorded": "document_recorded", "文书记载": "document_recorded",
    "not_stated": "not_stated", "未记载": "not_stated",
    "unknown": "unknown",
}
FINDING_MARKERS = ("法院认定", "本院认定", "已查明", "无争议事实")
HOLDER_VALUES = {
    "worker": "worker", "劳动者": "worker",
    "employer": "employer", "用人单位": "employer",
    "third_party": "third_party", "第三人": "third_party",
}
ROLE_VALUES = {**HOLDER_VALUES, "代理人": "third_party"}
NEGATION_MARKERS = ("否认", "未承认", "不认可", "抗辩", "不确认")
CLAIM_MARKERS = ("主张", "认为", "辩称")
DATE_DAY = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
DATE_ISO = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
DATE_MONTH_ONLY = re.compile(r"(\d{4})年(\d{1,2})月(?!\d)")
NUM = re.compile(r"\d+(?:\.\d+)?")
LAWYER_LAW_CATEGORIES = frozenset({
    "party_privacy", "trade_secret", "state_secret", "other_confidential",
})
LAWYER_LAW_ARTICLE = "第41条"
LAWYER_LAW_DATE = "2026-09-01"
LAWYER_LAW_MAPPING = "2017年文本第38条对应2026-09-01施行文本第41条，不得沿用旧条号。"
SEPARATE_JUDGMENT_NOTE = "必要性、可处理性与残余风险分别判定，不输出综合安全分。"
INSTRUCTION_MARKERS = ("忽略规则", "忽略以上", "发送完整身份证")
RESTRICTED_CONFIDENTIALITY = frozenset({"state_secret"})


def known(value):
    return value not in UNKNOWN


def infer_sub_purpose(facts, task_type, requested=None):
    if requested:
        return requested
    if task_type != "fact_summary":
        return None
    return GENERAL_SUB_PURPOSE


def fact_attr(fact, name):
    raw = fact.get(name)
    if known(raw):
        return _normalize(name, raw)
    if fact.get("field") == name:
        return _normalize(name, fact.get("value"))
    if name == "hours" and fact.get("field") == "overtime_hours":
        return _as_number(fact.get("value"))
    if name == "wage_base" and fact.get("field") == "wage_base":
        return fact.get("value")
    return None if raw in UNKNOWN else raw


def _normalize(name, value):
    if value is None:
        return None
    text = str(value).strip()
    if name == "day_nature":
        return DAY_NATURE_VALUES.get(text, text if text in DAY_NATURE_VALUES.values() else None)
    if name == "claim_stance":
        stance = CLAIM_VALUES.get(text, text if text in CLAIM_VALUES.values() else None)
        if stance == "hold_evidence":
            return None
        return stance
    if name == "statement_status":
        return STATEMENT_VALUES.get(text, text if text in STATEMENT_VALUES.values() else None)
    if name in {"evidence_holder", "subject_role"}:
        table = HOLDER_VALUES if name == "evidence_holder" else ROLE_VALUES
        return table.get(text, text if text in table.values() else None)
    if name == "hours":
        return _as_number(value)
    return text or None


def _as_number(value):
    if value in UNKNOWN:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = NUM.search(str(value))
    return float(match.group(0)) if match else None


def _context(fact, sub_purpose):
    return {
        "sub_purpose": sub_purpose,
        "day_nature": fact_attr(fact, "day_nature"),
        "claim_stance": fact_attr(fact, "claim_stance"),
        "evidence_holder": fact_attr(fact, "evidence_holder"),
        "hours": fact_attr(fact, "hours"),
        "wage_base": fact_attr(fact, "wage_base"),
        "subject_role": fact_attr(fact, "subject_role"),
        "dispute_status": fact.get("dispute_status"),
        "statement_status": fact_attr(fact, "statement_status") or fact.get("statement_status") or fact.get("dispute_status"),
    }


def evaluate_condition(condition, fact, sub_purpose):
    ctx = _context(fact, sub_purpose)
    attribute = condition.get("attribute")
    operator = condition.get("operator")
    values = [str(item) for item in condition.get("values") or []]
    actual = ctx.get(attribute, fact.get(attribute))
    if operator == "known":
        if actual in UNKNOWN or actual is None:
            return "unknown"
        return "met"
    if actual in UNKNOWN or actual is None:
        return "unknown"
    actual_text = str(actual)
    if operator == "eq":
        return "met" if values and actual_text == values[0] else "unmet"
    if operator == "in":
        return "met" if actual_text in values else "unmet"
    return "unknown"


def matching_rules(pack, fact, task_type, sub_purpose):
    found = []
    for rule in pack.get("disclosure_rules") or []:
        if rule.get("task_id") != task_type:
            continue
        affected = rule.get("affected_fields") or []
        if affected and fact.get("field") not in affected:
            continue
        if rule.get("sub_purpose") and sub_purpose != rule.get("sub_purpose"):
            continue
        found.append(rule)
    return found


def _merge_rules(rules):
    primary = dict(rules[0])
    relations, sources, forbidden = [], [], []
    allowed = None
    for rule in rules:
        relations.extend(rule.get("immutable_relations") or [])
        sources.extend(rule.get("legal_source_ids") or [])
        forbidden.extend(rule.get("forbidden_default_transforms") or [])
        current = list(rule.get("allowed_transforms") or CANDIDATE_KINDS)
        allowed = current if allowed is None else [kind for kind in allowed if kind in set(current)]
    primary["immutable_relations"] = list(dict.fromkeys(relations))
    primary["legal_source_ids"] = list(dict.fromkeys(sources))
    primary["forbidden_default_transforms"] = list(dict.fromkeys(forbidden))
    if allowed:
        primary["allowed_transforms"] = allowed
    primary["id"] = rules[0]["id"]
    primary["merged_rule_ids"] = [rule["id"] for rule in rules]
    return primary


def resolve_conditional_rule(pack, fact, task_type, sub_purpose=None):
    rules = matching_rules(pack, fact, task_type, sub_purpose)
    if not rules:
        return None
    fully, unknown_hits, unknown_ids = [], [], []
    for rule in rules:
        statuses = [evaluate_condition(item, fact, sub_purpose) for item in rule.get("conditions") or []]
        if any(status == "unmet" for status in statuses):
            continue
        pending = [item["id"] for item, status in zip(rule.get("conditions") or [], statuses) if status == "unknown"]
        if pending:
            unknown_hits.append(rule)
            unknown_ids.extend(pending)
            continue
        fully.append(rule)
    if unknown_hits:
        return {
            "rule": _merge_rules(unknown_hits + fully),
            "unknown_conditions": list(dict.fromkeys(unknown_ids)),
            "unmet_rules": [],
        }
    if fully:
        return {"rule": _merge_rules(fully), "unknown_conditions": [], "unmet_rules": []}
    return None


def dates_in(text):
    found = []
    for year, month, day in DATE_DAY.findall(text or ""):
        found.append((int(year), int(month), int(day)))
    for year, month, day in DATE_ISO.findall(text or ""):
        found.append((int(year), int(month), int(day)))
    return found


def has_calendar_day(text):
    return bool(dates_in(text))


def lost_calendar_day(original, output):
    return has_calendar_day(original) and bool(output) and not has_calendar_day(output)


def shifted_calendar(original, output):
    left, right = dates_in(original), dates_in(output)
    return bool(left and right and left != right)


def month_truncated(original, output):
    return lost_calendar_day(original, output) and bool(DATE_MONTH_ONLY.search(output or ""))


def constraint_reasons(fact, candidate, rule, mappings, all_facts=None):
    reasons = []
    original = fact.get("value") or ""
    output = candidate.get("output") or ""
    kind = candidate.get("kind")
    relations = set((rule or {}).get("immutable_relations") or [])
    if not relations:
        relations = {
            "subject_ownership", "date_relation", "numeric_relation",
            "negation", "dispute_status", "source",
        }
    if "date_relation" in relations:
        if month_truncated(original, output):
            reasons.append("阻断：截月导致期限或先后关系错误（一般整理与加班同一等级）")
        elif lost_calendar_day(original, output) and kind != "delete":
            reasons.append("须保持来源日历日精度，不能去掉日期中的日")
        if shifted_calendar(original, output):
            reasons.append("禁止整体平移日历，以免改变星期、节假日或法规范生效日")
    if "numeric_relation" in relations and kind != "delete":
        hours = fact_attr(fact, "hours")
        wage = fact_attr(fact, "wage_base")
        emitted = set(NUM.findall(output))
        if hours is not None and _number_text(hours) not in emitted:
            reasons.append("加班小时数被改写或丢失")
        if known(wage) and not any(token in output for token in NUM.findall(str(wage))):
            reasons.append("工资基数被改写或丢失")
    if "negation" in relations and kind != "delete":
        if _negated(fact, original) and output and not _keeps_negation(original, output):
            reasons.append("否认或抗辩被删成肯定陈述")
    if "dispute_status" in relations and kind != "delete":
        stance = fact_attr(fact, "claim_stance") or fact.get("statement_status") or fact.get("dispute_status")
        if stance in {"claim", "deny", "claimed", "denied", "disputed"} and output:
            if _flattens_dispute(original, output, stance):
                reasons.append("主张或否认被写成无争议事实")
        if output and _upgrades_to_finding(fact, original, output):
            reasons.append("主张或文书记载被提升为法院认定")
    if "subject_ownership" in relations and kind != "delete":
        swapped = _subject_swap(fact, output, mappings, all_facts)
        if swapped:
            reasons.append(swapped)
    if "source" in relations:
        holder = fact_attr(fact, "evidence_holder")
        attribution = fact.get("evidence_attribution")
        if kind == "delete" and (rule or {}).get("min_precision") == "who_holds" and known(holder):
            reasons.append("删除后无法保留谁持有加班证据")
        if kind != "delete" and known(attribution) and attribution not in output:
            reasons.append("证据出处或归属被改挂或丢失")
        if kind != "delete" and known(holder) and _holder_flipped(holder, original, output, fact):
            reasons.append("证据持有人被改挂")
    forbidden = set((rule or {}).get("forbidden_default_transforms") or [])
    if kind in forbidden or (kind == "moderate_generalize" and "date_month_truncation" in forbidden and month_truncated(original, output)):
        reasons.append("该变换属于本规则禁止的默认精度损失")
    allowed = (rule or {}).get("allowed_transforms")
    if allowed and kind not in allowed:
        reasons.append("候选不在本规则允许的有界变换集合内")
    return list(dict.fromkeys(reasons))


def _number_text(value):
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _negated(fact, original):
    return bool(fact.get("negated") or fact_attr(fact, "claim_stance") == "deny"
                or fact.get("dispute_status") in {"denied", "disputed"}
                or any(marker in original for marker in NEGATION_MARKERS))


def _keeps_negation(original, output):
    present = [marker for marker in NEGATION_MARKERS if marker in original]
    if not present:
        return "否认" in output or "抗辩" in output
    return any(marker in output for marker in present)


def _flattens_dispute(original, output, stance):
    if stance in {"deny", "denied", "disputed"}:
        return not _keeps_negation(original, output)
    if stance in {"claim", "claimed"} and any(marker in original for marker in CLAIM_MARKERS):
        return not any(marker in output for marker in CLAIM_MARKERS)
    return False


def _upgrades_to_finding(fact, original, output):
    status = fact_attr(fact, "statement_status") or fact.get("statement_status") or fact.get("dispute_status")
    stance = fact_attr(fact, "claim_stance")
    if status == "court_found":
        return False
    if status not in {"claimed", "denied", "admitted", "document_recorded", "not_stated", "disputed"} and stance not in {"claim", "deny"}:
        return False
    return any(marker in output for marker in FINDING_MARKERS) and not any(marker in original for marker in FINDING_MARKERS)


def _mapping_entries(mappings):
    if isinstance(mappings, list):
        return mappings
    if isinstance(mappings, dict):
        return [{"original_value": key, "wire_token": value} for key, value in mappings.items()]
    return []


def _subject_swap(fact, output, mappings, all_facts):
    own = fact.get("value") if fact.get("field") == "entity" else None
    entries = _mapping_entries(mappings)
    for entry in entries:
        other = entry.get("original_value")
        if not other or len(other) < 2 or other == own:
            continue
        if own and other in (output or "") and own not in (output or "") and entry.get("wire_token") not in (output or ""):
            return "主体归属被改写为其他主体"
    role = fact_attr(fact, "subject_role")
    if role == "worker" and "用人单位" in (output or "") and "劳动者" not in (output or "") and fact.get("field") == "entity":
        return "劳动者与用人单位主体被互换"
    others = [item.get("value") for item in all_facts or [] if item.get("field") == "entity" and item.get("value") != own]
    if own and any(name and len(str(name)) >= 2 and name in output and own not in output for name in others):
        return "主体归属被改写为其他主体"
    return None


def _holder_flipped(holder, original, output, fact):
    labels = {"worker": "劳动者", "employer": "用人单位", "third_party": "第三人"}
    own = labels.get(holder)
    if not own or fact.get("field") not in {"evidence", "evidence_holder"}:
        return False
    others = [label for key, label in labels.items() if key != holder]
    return any(label in output for label in others) and own not in output and own in original


def apply_candidate_transform(value, kind, mappings):
    if kind == "original_precision":
        return transform(value, "pseudonymize", mappings)
    if kind == "tokenize":
        return transform(value, "pseudonymize", mappings)
    if kind == "moderate_generalize":
        return transform(value, "moderate_generalize", mappings)
    if kind == "delete":
        return ""
    return transform(value, kind, mappings)


def information_loss_note(kind, fact, output):
    original = fact.get("value") or ""
    if kind == "delete":
        return "本项不进入外发，任务可能失去该加班要件"
    if kind == "original_precision":
        return "主体已按映射替换，日期与数值精度未降"
    if kind == "tokenize":
        return "主体已令牌化，日期、小时数与争议状态未改"
    if kind == "moderate_generalize":
        if has_calendar_day(original) and has_calendar_day(output):
            return "隐去直接标识，日期保持日精度，未平移日历"
        return "隐去直接标识，保留小时数、工资基数与争议状态"
    return "精度变化待核对"


def preferred_kind(rule, fact, fallback_transform):
    if rule:
        preferred = rule.get("preferred_transform") or "original_precision"
        if fact.get("field") == "entity" and preferred == "original_precision":
            return "tokenize"
        return preferred
    return TRANSFORM_TO_KIND.get(fallback_transform, "delete")


def generate_candidates(fact, mappings, rule, pack, all_facts=None):
    allowed = list((rule or {}).get("allowed_transforms") or CANDIDATE_KINDS)
    kinds = [kind for kind in CANDIDATE_KINDS if kind in allowed] or list(CANDIDATE_KINDS)
    items = []
    for kind in kinds:
        output = apply_candidate_transform(fact.get("value") or "", kind, mappings)
        candidate = {
            "id": kind,
            "kind": kind,
            "transform": KIND_TO_TRANSFORM[kind],
            "output": output,
            "information_loss": information_loss_note(kind, fact, output),
        }
        reasons = constraint_reasons(fact, candidate, rule, mappings, all_facts)
        if kind != "delete" and registered_name_residuals(output, mappings):
            reasons.append("登记主体未替换，替换后仍有残留")
        candidate["block_reasons"] = reasons
        candidate["allowed"] = not reasons
        items.append(candidate)
    return items


def select_candidate(candidates, rule, fact, fallback_transform):
    preferred = preferred_kind(rule, fact, fallback_transform)
    allowed = [item for item in candidates if item.get("allowed")]
    for item in allowed:
        if item["kind"] == preferred:
            return item
    return allowed[0] if allowed else None


def legal_source_map(pack):
    return {item["id"]: item for item in pack.get("legal_sources") or []}


def build_processing_basis(fact, rule, selected, pack, unknown_conditions):
    necessity = (rule or {}).get("necessity") or "uncertain"
    if unknown_conditions:
        necessity_judgment = "review"
    elif necessity == "required":
        necessity_judgment = "necessary"
    elif necessity == "unnecessary":
        necessity_judgment = "not_necessary"
    elif necessity == "conditional":
        necessity_judgment = "necessary"
    else:
        necessity_judgment = "unknown"
    residual = "review"
    if selected:
        if selected["kind"] == "original_precision" and fact.get("field") == "entity":
            residual = "elevated"
        elif selected["kind"] == "delete":
            residual = "unverified"
        else:
            residual = "unverified"
    processability = "review"
    if pack.get("legal_status") != "reviewed" or not pack.get("dispatch_allowed"):
        processability = "review"
    return ProcessingBasis(
        subject_category=fact.get("subject_category") or "unknown",
        collection_source=fact.get("collection_source") or "案件材料",
        local_purpose=(rule or {}).get("sub_purpose") or GENERAL_SUB_PURPOSE,
        cloud_purpose="可选云端摘要，不等于办案必要",
        proposed_basis="待审草稿，非正式处理依据",
        necessity_note=(rule or {}).get("reason") or "",
        consent_or_other_evidence=fact.get("consent_evidence") or "",
        notice_status=fact.get("notice_status") or "unknown",
        review_conclusion="pending",
        necessity_judgment=necessity_judgment,
        processability_judgment=processability,
        residual_risk_judgment=residual,
    ).model_dump()


def build_confidentiality(fact, pack):
    source = legal_source_map(pack).get("lawyer_law_2026_09_01") or {}
    category = fact.get("confidentiality_category") or "unknown"
    cite = category in LAWYER_LAW_CATEGORIES
    return ConfidentialityRecord(
        case_level=fact.get("confidentiality_level") or "unknown",
        information_category=category,
        team_policy_block=bool(fact.get("team_policy_block")),
        statutory_duty_note="律师保密覆盖国家秘密、商业秘密、当事人隐私及其他不愿泄露的信息；与个人信息可处理性分别判断。",
        lawyer_law_article=LAWYER_LAW_ARTICLE if cite else None,
        lawyer_law_snapshot=source.get("snapshot") if cite else "",
        lawyer_law_mapping_note=LAWYER_LAW_MAPPING if cite else "",
        lawyer_law_text_date=LAWYER_LAW_DATE if cite else None,
    ).model_dump()


def normalize_sensitivity_label(value):
    if value in UNKNOWN:
        return None
    return SENSITIVITY_ALIASES.get(str(value).strip())


def apply_sensitivity_overlay(decision, fact, mappings):
    """Map annotation inventory labels onto disclosure. Not a published legal rule."""
    label = normalize_sensitivity_label(fact.get("sensitivity_label"))
    if not label:
        return decision
    overlay = SENSITIVITY_OVERLAY[label]
    decision["sensitivity_label"] = label
    decision["sensitivity_note"] = SENSITIVITY_NOTE
    if not overlay["cloud_eligible"]:
        reasons = list(decision.get("block_reasons") or [])
        if label == "forbid_outbound":
            reasons.append("清单类别禁止外发，不进入云端事实")
        elif label == "human_review":
            reasons.append("清单类别转人工，披露停住等人核验")
        else:
            reasons.append("清单类别默认删除或不确定，不进入云端事实")
        decision.update(
            transform="delete",
            output="",
            forbidden=bool(overlay["forbidden"]),
            necessity=overlay["necessity"],
            status=overlay.get("status") or "candidate",
            block_reasons=list(dict.fromkeys(reasons)),
        )
        return decision
    if decision.get("rule_id"):
        return decision
    method = overlay["transform"]
    decision.update(
        necessity=overlay["necessity"],
        transform=method,
        forbidden=False,
        output="" if method == "delete" else transform(fact.get("value") or "", method, mappings),
        status=overlay.get("status") or ("review" if overlay["necessity"] == "uncertain" else "candidate"),
    )
    return decision


def fallback_decision(fact, fallback, mappings):
    method = "delete" if fallback.get("forbidden") else fallback.get("transform") or "delete"
    necessity = fallback.get("necessity") or "uncertain"
    output = transform(fact.get("value") or "", method, mappings)
    return {
        "necessity": necessity,
        "transform": method,
        "reason": fallback.get("reason") or "未定义适用规则",
        "forbidden": bool(fallback.get("forbidden")),
        "status": "restricted" if necessity == "uncertain" else "candidate",
        "output": "" if method == "delete" else output,
        "retain_reason": fallback.get("reason") or "",
        "information_loss": "本项按缺省限制输出，不进入披露候选" if method == "delete" else "未适用条件规则",
        "block_reasons": ["条件或必要性未确定，限制输出，不默许进入披露候选"] if necessity == "uncertain" else [],
        "unknown_conditions": [],
        "rule_id": None,
        "disclosure_rule": None,
        "sub_purpose": None,
        "min_precision": "",
        "legal_source_ids": [],
        "selected_candidate_id": None,
        "candidates": [],
    }


def build_disclosure_decision(fact, pack, task_type, mappings, fallback, sub_purpose=None, all_facts=None):
    resolved = resolve_conditional_rule(pack, fact, task_type, sub_purpose)
    if resolved is None:
        decision = fallback_decision(fact, fallback, mappings)
        decision.update(
            fact_id=fact["id"],
            field=fact["field"],
            processing_basis=build_processing_basis(fact, None, None, pack, []),
            confidentiality=build_confidentiality(fact, pack),
        )
        return apply_sub_purpose_limits(
            apply_sensitivity_overlay(apply_material_restrictions(decision, fact), fact, mappings),
            fact,
            sub_purpose,
        )
    rule = resolved["rule"]
    unknown = resolved["unknown_conditions"]
    candidates = generate_candidates(fact, mappings, rule, pack, all_facts)
    selected = select_candidate(candidates, rule, fact, fallback.get("transform") or "delete")
    if unknown:
        necessity = rule.get("necessity") or fallback.get("necessity") or "conditional"
        reason = "条件未知，限制输出，不默许进入披露候选"
        block_reasons = [f"条件未知：{item}" for item in unknown]
        strategy = rule.get("unknown_condition_strategy") or "restrict"
        if strategy in {"review", "restrict"}:
            status = "restricted"
            output = ""
            transform_name = "delete"
            selected = next((item for item in candidates if item["kind"] == "delete"), selected)
        else:
            status = "restricted"
            output = selected["output"] if selected else ""
            transform_name = selected["transform"] if selected else "delete"
    else:
        necessity = rule.get("necessity") or fallback.get("necessity") or "uncertain"
        status = "restricted" if necessity == "uncertain" else "candidate"
        reason = rule.get("reason") or fallback.get("reason") or ""
        block_reasons = []
        if selected is None:
            status = "restricted"
            output = ""
            transform_name = "delete"
            block_reasons.append("有界候选全部被硬约束淘汰，限制输出")
        else:
            output = selected["output"]
            transform_name = selected["transform"]
    if selected and not selected.get("allowed"):
        status = "restricted"
        block_reasons.extend(selected.get("block_reasons") or [])
    retain = rule.get("reason") or ""
    if rule.get("min_precision"):
        retain = (retain + " 最低精度：" + rule["min_precision"]).strip()
    sources = rule.get("legal_source_ids") or []
    if sources:
        retain = (retain + " 法源草稿：" + "、".join(sources)).strip()
    decision = {
        "fact_id": fact["id"],
        "field": fact["field"],
        "necessity": necessity,
        "transform": transform_name,
        "reason": reason,
        "forbidden": bool(fallback.get("forbidden")),
        "status": status,
        "output": output if transform_name != "delete" else "",
        "retain_reason": retain,
        "information_loss": selected["information_loss"] if selected else "无可用候选",
        "block_reasons": list(dict.fromkeys(block_reasons)),
        "unknown_conditions": unknown,
        "rule_id": rule.get("id"),
        "disclosure_rule": rule,
        "sub_purpose": rule.get("sub_purpose") or sub_purpose,
        "min_precision": rule.get("min_precision") or "",
        "legal_source_ids": sources,
        "selected_candidate_id": selected["id"] if selected else None,
        "candidates": candidates,
        "processing_basis": build_processing_basis(fact, rule, selected, pack, unknown),
        "confidentiality": build_confidentiality(fact, pack),
    }
    limited = apply_sub_purpose_limits(
        apply_sensitivity_overlay(apply_material_restrictions(decision, fact), fact, mappings),
        fact,
        sub_purpose,
    )
    return limited


def apply_sub_purpose_limits(decision, fact, sub_purpose):
    purpose = sub_purpose or decision.get("sub_purpose")
    value = str(fact.get("value") or "")
    field = fact.get("field")
    reasons = list(decision.get("block_reasons") or [])
    if purpose == WAGE_COMP_SUB_PURPOSE and field in W_OFF_WIRE_FIELDS:
        reasons.append("W 首版不算金额，金额不上云")
        decision.update(
            transform="delete", output="", necessity="unnecessary", status="restricted",
            reason="W 首版不算金额", block_reasons=list(dict.fromkeys(reasons)),
        )
        return decision
    if purpose == WAGE_COMP_SUB_PURPOSE and any(marker in value for marker in LIMITATION_MARKERS):
        reasons.append("W 首版期限判断不上云，留在本地")
        decision.update(
            transform="delete", output="", status="restricted",
            reason="W 首版期限判断不上云", block_reasons=list(dict.fromkeys(reasons)),
        )
        return decision
    if purpose == WAGE_COMP_SUB_PURPOSE and "待岗" in value and (field == "date" or year_inverted(value)):
        reasons.append("待岗年份冲突只留本地，不进入 W 事实卡")
        decision.update(
            transform="delete", output="", status="restricted",
            reason="待岗年份冲突只留本地", block_reasons=list(dict.fromkeys(reasons)),
        )
        return decision
    if purpose == INJURY_SUB_PURPOSE and any(marker in value for marker in INJURY_OMIT_MARKERS):
        reasons.append("工伤病历或精细诊断默认不上云")
        decision.update(
            transform="delete", output="", forbidden=True, status="restricted",
            reason="工伤病历或精细诊断默认不上云", block_reasons=list(dict.fromkeys(reasons)),
        )
    return decision


def apply_material_restrictions(decision, fact):
    reasons = list(decision.get("block_reasons") or [])
    value = fact.get("value") or ""
    if fact.get("confidentiality_category") in RESTRICTED_CONFIDENTIALITY:
        reasons.append("国家秘密或明确保密限制不进入普通模型处理路径")
        decision.update(transform="delete", output="", status="restricted", forbidden=True, block_reasons=list(dict.fromkeys(reasons)))
        return decision
    if any(marker in value for marker in INSTRUCTION_MARKERS):
        reasons.append("材料内嵌指令按不可信内容处理，不执行、不写入业务摘要")
        decision.update(transform="delete", output="", status="restricted", block_reasons=list(dict.fromkeys(reasons)))
    return decision


def apply_decision_choice(decision, fact, pack, mappings, method, necessity, custom_output=None, candidate_id=None, all_facts=None):
    overtime = decision.get("sub_purpose") == "核对加班" or decision.get("rule_id")
    rule = decision.get("disclosure_rule")
    if rule is None and decision.get("rule_id"):
        rule = next((item for item in pack.get("disclosure_rules") or [] if item.get("id") == decision["rule_id"]), None)
    candidates = decision.get("candidates") or generate_candidates(fact, mappings, rule, pack, all_facts)
    selected = None
    if candidate_id:
        selected = next((item for item in candidates if item["id"] == candidate_id), None)
        if selected is None:
            raise ValueError("披露候选不存在")
        if not selected.get("allowed"):
            raise ValueError("该候选已被硬约束淘汰")
        method = selected["transform"]
        output = selected["output"]
    else:
        if method == "generalize" and overtime:
            kind = "moderate_generalize"
            output = apply_candidate_transform(fact.get("value") or "", "moderate_generalize", mappings)
        else:
            kind = TRANSFORM_TO_KIND.get(method, method)
            output = transform(fact.get("value") or "", method, mappings)
        selected = next((item for item in candidates if item["kind"] == kind and item.get("allowed")), None)
    if custom_output is not None:
        output = custom_output
        probe = {"id": "custom", "kind": selected["kind"] if selected else TRANSFORM_TO_KIND.get(method, "original_precision"),
                 "transform": method, "output": output}
        illegal = constraint_reasons(fact, probe, rule, mappings, all_facts)
        if illegal:
            raise ValueError("自定义披露文本违反硬约束：" + "；".join(illegal))
    if method == "delete":
        output = ""
    status = "restricted" if necessity == "uncertain" or decision.get("unknown_conditions") else "candidate"
    block_reasons = list(decision.get("unknown_conditions") and [f"条件未知：{item}" for item in decision["unknown_conditions"]] or [])
    if selected and not selected.get("allowed"):
        status = "restricted"
        block_reasons.extend(selected.get("block_reasons") or [])
    decision.update(
        transform=method,
        necessity=necessity,
        status=status,
        output=output,
        selected_candidate_id=selected["id"] if selected else candidate_id,
        information_loss=selected["information_loss"] if selected else decision.get("information_loss"),
        block_reasons=list(dict.fromkeys(block_reasons)),
        candidates=candidates,
        processing_basis=build_processing_basis(fact, rule, selected, pack, decision.get("unknown_conditions") or []),
        confidentiality=decision.get("confidentiality") or build_confidentiality(fact, pack),
    )
    return apply_sub_purpose_limits(apply_sensitivity_overlay(decision, fact, mappings), fact, decision.get("sub_purpose"))
