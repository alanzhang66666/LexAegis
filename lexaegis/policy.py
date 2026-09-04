import re
from .detection import DEFAULT_PATTERNS, bind_source_spans, detect_text, risk_signals, sensitivity_signals
from .util import digest

ATTACKS = ["identity", "candidate_set", "sensitive_inference", "cross_round"]
PATTERNS = {item["category"]: item["pattern"] for item in DEFAULT_PATTERNS}
TOKEN = re.compile(r"\[\[LEX:P\d{4,}\]\]")


def detect(text, pack=None):
    return list(dict.fromkeys(finding["category"] for finding in detect_text(text, pack=pack)))


def transform(value, method, mappings):
    if method == "delete":
        return ""
    if method in ("pseudonymize", "generalize"):
        pairs = ((entry["original_value"], entry["wire_token"]) for entry in mappings) if isinstance(mappings, list) else mappings.items()
        for original, alias in sorted(pairs, key=lambda pair: -len(pair[0])):
            value = value.replace(original, alias)
        for name, pattern in PATTERNS.items():
            value = re.sub(pattern, f"[{name}已隐去]", value)
    if method == "generalize":
        value = re.sub(r"(\d{4})年(\d{1,2})月\d{1,2}日", r"\1年\2月", value)
        value = re.sub(r"(\d{4})[-/](\d{1,2})[-/]\d{1,2}", r"\1-\2", value)
    return value


def ensure_mappings(case, facts):
    entries = case.setdefault("mapping_entries", [])
    by_original = {entry["original_value"]: entry for entry in entries}
    mapping_version = int(case.get("mapping_version", 1))
    for fact in facts:
        if fact["field"] == "entity" and fact["value"] not in by_original:
            number = len(entries) + 1
            mapping_version += 1
            entry = {"entity_id": f"entity_{number:04d}", "wire_token": f"[[LEX:P{number:04d}]]",
                     "display_alias": f"主体{number}（{case['id'][-4:]}）", "original_value": fact["value"],
                     "source_ids": list(fact.get("source_ids", [])), "mapping_version": mapping_version}
            entries.append(entry)
            by_original[fact["value"]] = entry
        elif fact["field"] == "entity":
            current = by_original[fact["value"]]
            current["source_ids"] = sorted(set(current.get("source_ids", [])) | set(fact.get("source_ids", [])))
    # Compatibility projection for 0.1 readers. New code uses mapping_entries.
    case["mapping"] = {entry["original_value"]: entry["wire_token"] for entry in entries}
    case["mapping_version"] = mapping_version
    return entries


def assess(case, pack, facts, decisions, docs, ledger, transport, provider_results=None, attacks=None, isolation_verified=False):
    findings, blockers = [], []
    emitted = "\n".join(d["output"] for d in decisions if d["output"])
    fact_by_id = {fact["id"]: fact for fact in facts}
    detector_inputs = [(fact_by_id.get(decision["fact_id"], {}).get("source_ids", []),
                        decision["output"]) for decision in decisions if decision.get("output")]
    anchor_index = {block["id"]: block for document in docs for block in document.get("ir", {}).get("blocks", [])}
    detected_findings = [
        finding
        for source_ids, text in detector_inputs
        for finding in bind_source_spans(detect_text(text, pack=pack), source_ids, anchor_index)
    ]
    detected = list(dict.fromkeys(finding["category"] for finding in detected_findings))
    if detected:
        blockers.append("仍包含直接标识：" + "、".join(detected))
    for original in [entry["original_value"] for entry in case.get("mapping_entries", [])] or case.get("mapping", {}):
        if original and original in emitted:
            blockers.append("仍包含未替换的登记主体")
            break
    if any(d.get("forbidden") and d["output"] for d in decisions):
        blockers.append("命中规则硬性禁止项")
    if any(d["necessity"] == "uncertain" or d["status"] == "review" for d in decisions):
        blockers.append("存在尚未解决的字段复核事项")
    if not any(d["output"] for d in decisions):
        blockers.append("没有可发送的事实")
    if any(not f["confirmed"] or f.get("stale") for f in facts):
        blockers.append("事实尚未确认或来源版本已更新")
    if any(d["status"] != "ready" or d.get("ir", {}).get("needs_review") for d in docs):
        blockers.append("材料解析或 OCR 复核未完成")
    if "唯一" in emitted or "公开获奖" in emitted:
        blockers.append("组合线索风险：唯一岗位或公开事件仍保留")
    if ledger:
        findings.append(f"已纳入 {len(ledger)} 条已发送或结果不明的历史披露；须按冻结协议重新运行跨轮攻击。")
    demo = case["mode"] == "demo"
    if case.get("scenario") == "stop":
        blockers.append("合成示例关键证据不完整，主动停止")
    if not demo:
        from .governance import validate_formal_gate
        blockers.extend(validate_formal_gate(pack, provider_results or [], attacks or [], isolation_verified))
        if set(pack.get("risk_weights", {})) != {"entity", "density", "context", "combination", "cross_round"}:
            blockers.append("五类风险信号权重尚未冻结")
    if transport == "mock" and not demo:
        blockers.append("正式案件不能使用模拟调用")
    attacks = attacks or [{"kind": name, "capability": "available", "outcome": "not_run"} for name in ATTACKS]
    signals = risk_signals([(source_ids[0] if source_ids else None, text) for source_ids, text in detector_inputs],
                           pack, len(ledger), findings=detected_findings)
    findings.append("确定性检测不是完整再识别测试；未执行的攻击不计为通过。")
    if demo:
        findings.append("仅允许固定合成数据演示；完整风险检验仍未完成。")
    completion = "complete" if not blockers and all(a.get("outcome") == "resisted" for a in attacks) else "incomplete"
    return {"completion": completion, "findings": findings, "blockers": list(dict.fromkeys(blockers)), "attacks": attacks,
            "detection_findings": detected_findings, "sensitivity_signals": sensitivity_signals(detected_findings),
            "risk_signals": signals, "compliance_checks": provider_results or [], "ledger_version": case["ledger_version"],
            "approval_allowed": not blockers, "demo_exception": demo}


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
        valid = all(isinstance(i, str) and i in decisions and decisions[i]["output"] for i in ids)
        support = "\n".join(decisions[i]["output"] for i in ids) if valid else ""
        support_items = [decisions[i]["output"] for i in ids] if valid else []
        issues = []
        if not ids or not valid:
            issues.append("引用不存在或指向未披露事实")
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
        anchors = [s for i in ids if i in by_id for s in by_id[i]["source_ids"]]
        results.append({"id": digest(item)[:16], "text": text, "local_text": text, "source_ids": ids, "anchors": anchors,
                        "support": support_items, "issues": list(dict.fromkeys(issues)), "status": "needs_review" if issues else "source_matched",
                        "reviewer": None, "reviewed_at": None, "reviewed": False})
    if not results:
        raise ValueError("模型未返回任何事实陈述")
    return results
