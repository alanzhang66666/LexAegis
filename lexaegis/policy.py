import json
import os
import re
from .detection import DEFAULT_PATTERNS, bind_source_spans, detect_text, risk_signals, sensitivity_signals
from .outbound_gate import G0, attach_disposition, collect_outbound_blockers, forbidden_term_blocker, prohibition_hits, _hit as gate_hit
from .util import digest

DEFAULT_DISCLOSURE_BUDGET_CHARS = 50000
DEFAULT_DISCLOSURE_BUDGET_ENTRIES = 20

ATTACKS = ["identity", "candidate_set", "sensitive_inference", "cross_round"]
PATTERNS = {item["category"]: item["pattern"] for item in DEFAULT_PATTERNS}
TOKEN = re.compile(r"\[\[LEX:[POLC]\d{4,}\]\]")


def _fact_aliases(fact):
    raw = fact.get("aliases")
    if raw is None and isinstance(fact.get("model_suggestion"), dict):
        raw = fact["model_suggestion"].get("aliases")
    return [item for item in (raw or []) if isinstance(item, str) and item]


def _mapping_names(entry):
    names = [entry.get("original_value")]
    names.extend(entry.get("aliases") or [])
    return [name for name in names if name]


def _usable_name(name):
    return bool(name) and len(name) >= 2


def _replacement_pairs(mappings):
    if isinstance(mappings, list):
        pairs = []
        for entry in mappings:
            token = entry["wire_token"]
            original = entry.get("original_value")
            if _usable_name(original):
                pairs.append((original, token))
            pairs.extend((alias, token) for alias in entry.get("aliases") or [] if _usable_name(alias))
        return pairs
    return [(name, token) for name, token in mappings.items() if _usable_name(name)]


def registered_name_residuals(output, mappings):
    leftovers = []
    for original, token in sorted(_replacement_pairs(mappings), key=lambda pair: -len(pair[0])):
        if original and len(original) >= 2 and original != token and original in (output or ""):
            leftovers.append(original)
    return leftovers


def transform(value, method, mappings):
    if method == "delete":
        return ""
    if method in ("pseudonymize", "generalize", "moderate_generalize"):
        for original, alias in sorted(_replacement_pairs(mappings), key=lambda pair: -len(pair[0])):
            if original:
                value = value.replace(original, alias)
        for name, pattern in PATTERNS.items():
            value = re.sub(pattern, f"[{name}已隐去]", value)
    if method == "generalize":
        value = re.sub(r"(\d{4})年(\d{1,2})月\d{1,2}日", r"\1年\2月", value)
        value = re.sub(r"(\d{4})[-/](\d{1,2})[-/]\d{1,2}", r"\1-\2", value)
    return value


def ensure_mappings(case, facts):
    entries = case.setdefault("mapping_entries", [])
    tokens = [entry.get("wire_token") for entry in entries]
    originals = [entry.get("original_value") for entry in entries]
    entity_ids = [entry.get("entity_id") for entry in entries]
    claimed = [name for entry in entries for name in _mapping_names(entry)]
    if (len(tokens) != len(set(tokens)) or len(originals) != len(set(originals))
            or len(entity_ids) != len(set(entity_ids)) or len(claimed) != len(set(claimed))
            or any(not isinstance(token, str) or TOKEN.fullmatch(token) is None for token in tokens)):
        raise ValueError("本地身份映射存在 token、主体或原值冲突；禁止继续生成披露内容")
    by_original = {entry["original_value"]: entry for entry in entries}
    mapping_version = int(case.get("mapping_version", 1))
    skipped = []

    def others_names(current):
        names = set()
        for entry in entries:
            if entry is not current:
                names.update(_mapping_names(entry))
        return names

    def attach_aliases(current, aliases):
        accepted = list(current.get("aliases") or [])
        blocked = others_names(current)
        blocked.add(current["original_value"])
        for alias in aliases:
            if alias in accepted:
                continue
            if alias in blocked:
                skipped.append({"alias": alias, "entity_id": current["entity_id"],
                                "reason": "alias_conflicts_with_other_entity"})
                continue
            accepted.append(alias)
        current["aliases"] = accepted

    for fact in facts:
        if fact["field"] != "entity":
            continue
        value = (fact.get("value") or "").strip()
        if len(value) < 2:
            skipped.append({"alias": value, "entity_id": None, "reason": "entity_value_too_short"})
            continue
        aliases = _fact_aliases(fact)
        if value not in by_original:
            for entry in entries:
                existing = list(entry.get("aliases") or [])
                if value in existing:
                    entry["aliases"] = [item for item in existing if item != value]
                    skipped.append({"alias": value, "entity_id": entry["entity_id"],
                                    "reason": "alias_conflicts_with_other_entity"})
            number = len(entries) + 1
            mapping_version += 1
            entry = {"entity_id": f"entity_{number:04d}", "wire_token": f"[[LEX:P{number:04d}]]",
                     "display_alias": f"主体{number}（{case['id'][-4:]}）", "original_value": value,
                     "source_ids": list(fact.get("source_ids", [])), "mapping_version": mapping_version,
                     "aliases": []}
            entries.append(entry)
            by_original[value] = entry
            attach_aliases(entry, aliases)
        else:
            current = by_original[value]
            current["source_ids"] = sorted(set(current.get("source_ids", [])) | set(fact.get("source_ids", [])))
            attach_aliases(current, aliases)
    case["skipped_aliases"] = skipped
    case["mapping"] = {name: entry["wire_token"] for entry in entries for name in _mapping_names(entry)}
    case["mapping_version"] = mapping_version
    return entries


def _positive_int(value):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def resolve_disclosure_budget(chars=None, entries=None):
    env_chars = _positive_int(os.getenv("LEX_DISCLOSURE_BUDGET_CHARS"))
    env_entries = _positive_int(os.getenv("LEX_DISCLOSURE_BUDGET_ENTRIES"))
    resolved_chars = env_chars if env_chars is not None else _positive_int(chars)
    resolved_entries = env_entries if env_entries is not None else _positive_int(entries)
    if resolved_chars is None:
        resolved_chars = DEFAULT_DISCLOSURE_BUDGET_CHARS
    if resolved_entries is None:
        resolved_entries = DEFAULT_DISCLOSURE_BUDGET_ENTRIES
    return resolved_chars, resolved_entries


def _combination_blocker(matched):
    return forbidden_term_blocker(matched)


def ledger_usage(ledger):
    count = len(ledger or [])
    chars = 0
    for item in ledger or []:
        request = item.get("request") or {}
        payload = request.get("wire_payload")
        if payload is None:
            payload = request
        chars += len(json.dumps(payload, ensure_ascii=False)) if payload else 0
    return count, chars


def assess(case, pack, facts, decisions, docs, ledger, transport, provider_results=None, attacks=None, isolation_verified=False, budget_chars=None, budget_entries=None, frozen_request=None):
    findings, gates = [], []
    emitted = "\n".join(d["output"] for d in decisions if d["output"])
    fact_by_id = {fact["id"]: fact for fact in facts}
    detector_inputs = [(fact_by_id.get(decision["fact_id"], {}).get("source_ids", []),
                        decision["output"]) for decision in decisions if decision.get("output")]
    anchor_index = {block["id"]: block for document in docs for block in (document.get("ir") or {}).get("blocks", [])}
    detected_findings = [
        finding
        for source_ids, text in detector_inputs
        for finding in bind_source_spans(detect_text(text, pack=pack), source_ids, anchor_index)
    ]
    detected = list(dict.fromkeys(finding["category"] for finding in detected_findings))
    if detected:
        gates.append(gate_hit(G0, "仍包含直接标识：" + "、".join(detected)))
    registered = [name for entry in case.get("mapping_entries", []) for name in _mapping_names(entry) if name and len(name) >= 2]
    for original in registered or [name for name in (case.get("mapping") or {}) if name and len(str(name)) >= 2]:
        if original and original in emitted:
            gates.append(gate_hit(G0, "仍包含未替换的登记主体"))
            break
    if any(d.get("forbidden") and d["output"] for d in decisions):
        gates.append(gate_hit(G0, "命中规则硬性禁止项"))
    if any(d["necessity"] == "uncertain" or d["status"] in {"review", "restricted"} for d in decisions):
        gates.append(gate_hit(G0, "存在尚未解决的字段复核事项或已被规则限制的字段"))
    required = [item for item in decisions if item.get("necessity") == "required"]
    if required and not any(item.get("output") for item in required):
        gates.append(gate_hit(G0, "必要内容被删光，不能按零泄露计成功"))
    if not any(d["output"] for d in decisions):
        gates.append(gate_hit(G0, "没有可发送的事实"))
    if any(not f["confirmed"] or f.get("stale") for f in facts):
        gates.append(gate_hit(G0, "事实尚未确认或来源版本已更新"))
    if any(d.get("status") != "ready" or not isinstance(d.get("ir"), dict) or (d.get("ir") or {}).get("needs_review") for d in docs):
        gates.append(gate_hit(G0, "材料解析、OCR 或转写复核未完成"))
    demo = case["mode"] == "demo"
    terms = [term for term in (pack or {}).get("forbidden_terms") or [] if term]
    matched = [term for term in terms if term in emitted]
    if matched and (demo or transport == "local"):
        gates.append(gate_hit(G0, _combination_blocker(matched)))
    limit_chars, limit_entries = resolve_disclosure_budget(budget_chars, budget_entries)
    used_entries, used_chars = ledger_usage(ledger)
    if used_chars + len(emitted) > limit_chars or used_entries >= limit_entries:
        gates.append(gate_hit(G0, "跨轮外发已超过工程预算（字符或条数）"))
    if ledger:
        findings.append(f"已纳入 {len(ledger)} 条已发送或结果不明的历史披露；须按冻结协议重新运行跨轮攻击。")
    if case.get("scenario") == "stop":
        gates.append(gate_hit(G0, "合成示例关键证据不完整，主动停止"))
    gates.extend(prohibition_hits(case, pack))
    if not demo and transport != "local":
        prompt = ""
        recipient = None
        if isinstance(frozen_request, dict):
            prompt = frozen_request.get("prompt") or ""
            recipient = frozen_request.get("recipient")
            if not emitted:
                emitted = "\n".join(
                    str(item.get("text") or "") for item in (frozen_request.get("facts") or []) if isinstance(item, dict)
                )
        gates.extend(collect_outbound_blockers(
            case, pack, emitted=emitted, ledger=ledger, provider_results=provider_results or [],
            attacks=attacks, isolation_verified=isolation_verified, prompt=prompt, recipient=recipient,
        ))
    if transport == "mock" and not demo:
        gates.append(gate_hit(G0, "正式案件不能使用模拟调用"))
    attacks = attacks or [{"kind": name, "capability": "available", "outcome": "not_run"} for name in ATTACKS]
    signals = risk_signals([(source_ids[0] if source_ids else None, text) for source_ids, text in detector_inputs],
                           pack, len(ledger), findings=detected_findings)
    findings.append("确定性检测不是完整再识别测试；未执行的攻击不计为通过。")
    if demo:
        findings.append("仅允许固定合成数据演示；完整风险检验仍未完成。")
    blockers = list(dict.fromkeys(hit["message"] for hit in gates))
    completion = "complete" if not blockers and all(a.get("outcome") == "resisted" for a in attacks) else "incomplete"
    risk = {"completion": completion, "findings": findings, "blockers": blockers, "gates": gates, "attacks": attacks,
            "detection_findings": detected_findings, "sensitivity_signals": sensitivity_signals(detected_findings),
            "risk_signals": signals, "compliance_checks": provider_results or [], "ledger_version": case["ledger_version"],
            "approval_allowed": not blockers, "demo_exception": demo}
    return attach_disposition(risk)


def check_claims(raw, task, facts):
    if not isinstance(raw, dict) or not isinstance(raw.get("claims"), list) or len(raw["claims"]) > 200:
        raise ValueError("模型结果必须为有限长度的 claims 数组")
    decisions = {d["fact_id"]: d for d in task["decisions"]}
    by_id = {f["id"]: f for f in facts}
    results = []
    for item in raw["claims"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("source_ids"), list):
            raise ValueError("摘要条目格式无效")
        text = item["text"][:20000]
        ids = item["source_ids"]
        if not all(isinstance(i, str) for i in ids):
            raise ValueError("摘要引用必须是字符串标识")
        if len(ids) > 100:
            raise ValueError("单条摘要引用超过上限")
        valid = all(isinstance(i, str) and i in decisions and decisions[i]["output"] for i in ids)
        support = "\n".join(decisions[i]["output"] for i in ids) if valid else ""
        support_items = [decisions[i]["output"] for i in ids] if valid else []
        issues = []
        if not ids or not valid:
            issues.append("引用不存在或指向未披露事实")
        if len(ids) != len(set(ids)):
            issues.append("引用列表包含重复事实")
        if any(n not in support for n in re.findall(r"\d+(?:\.\d+)?", text)):
            issues.append("日期或金额存在未在引用事实中出现的数字")
        if text not in support:
            issues.append("改写或新增陈述需要人工核实语义与证据归属")
        if not text.strip():
            issues.append("陈述为空")
        known_tokens = set(TOKEN.findall(support))
        returned_tokens = set(TOKEN.findall(text))
        if not returned_tokens <= known_tokens:
            issues.append("包含未知或不属于引用事实的身份 token")
        if "[[LEX:" in text and len(returned_tokens) != text.count("[[LEX:"):
            issues.append("身份 token 已破损，禁止自动复原")
        leaked = [finding for finding in detect_text(text) if finding["value"] not in support]
        if leaked:
            issues.append("陈述包含未在引用事实中出现的直接标识")
        anchors = [s for i in ids if i in by_id for s in by_id[i]["source_ids"]]
        results.append({"id": digest(item)[:16], "text": text, "local_text": text, "source_ids": ids, "anchors": anchors,
                        "support": support_items, "issues": list(dict.fromkeys(issues)), "status": "needs_review" if issues else "source_matched",
                        "reviewer": None, "reviewed_at": None, "reviewed": False})
    if not results:
        raise ValueError("模型未返回任何事实陈述")
    return results


GAP_CODES = {"missing_field", "insufficient_support", "ambiguous_reference", "other"}
MAX_GAPS = 32
MAX_GAP_DETAIL = 500
MAX_GAP_FACTS = 20


def check_cloud_feedback(raw, task, claims):
    issues = []
    sent = [decision["fact_id"] for decision in task.get("decisions") or [] if decision.get("output")]
    sent_set = set(sent)
    cited = {source_id for claim in claims for source_id in claim.get("source_ids") or []}
    unused = [fact_id for fact_id in sent if fact_id not in cited]
    cloud_unused = raw.get("unused_fact_ids") if isinstance(raw, dict) else None
    if cloud_unused is not None:
        if not isinstance(cloud_unused, list) or any(not isinstance(item, str) for item in cloud_unused):
            issues.append("云端 unused_fact_ids 格式无效")
        else:
            if any(item not in sent_set for item in cloud_unused):
                issues.append("云端 unused_fact_ids 包含未外发事实")
            if set(cloud_unused) != set(unused):
                issues.append("云端 unused_fact_ids 与边侧计算不一致")
    raw_gaps = raw.get("gaps") if isinstance(raw, dict) else None
    if raw_gaps is None:
        raw_gaps = []
    gaps = []
    if not isinstance(raw_gaps, list):
        issues.append("云端 gaps 格式无效")
        raw_gaps = []
    elif len(raw_gaps) > MAX_GAPS:
        issues.append("云端 gaps 超过 32 条上限")
        raw_gaps = raw_gaps[:MAX_GAPS]
    support_all = "\n".join(decision["output"] for decision in task.get("decisions") or [] if decision.get("output"))
    for item in raw_gaps:
        if not isinstance(item, dict):
            issues.append("云端 gap 条目格式无效")
            continue
        code = item.get("code")
        detail = item.get("detail")
        fact_ids = item.get("fact_ids", [])
        if code not in GAP_CODES:
            issues.append("云端 gap 使用了未声明的 code")
            continue
        if not isinstance(detail, str) or not detail.strip():
            issues.append("云端 gap 缺少有效 detail")
            continue
        if len(detail) > MAX_GAP_DETAIL:
            issues.append("云端 gap detail 超出长度上限")
            continue
        if fact_ids is None:
            fact_ids = []
        if not isinstance(fact_ids, list) or any(not isinstance(fact_id, str) for fact_id in fact_ids):
            issues.append("云端 gap fact_ids 格式无效")
            continue
        if len(fact_ids) > MAX_GAP_FACTS:
            issues.append("云端 gap fact_ids 超过上限")
            continue
        if any(fact_id not in sent_set for fact_id in fact_ids):
            issues.append("云端 gap 引用了未外发事实")
            continue
        if any(finding["value"] not in support_all for finding in detect_text(detail)):
            issues.append("云端 gap 包含未在外发事实中出现的直接标识")
            continue
        gaps.append({"code": code, "detail": detail, "fact_ids": fact_ids})
    return {"unused_fact_ids": unused, "gaps": gaps, "feedback_issues": list(dict.fromkeys(issues))}
