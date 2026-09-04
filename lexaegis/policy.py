import re
from .util import digest

ATTACKS = ["identity", "candidate_set", "sensitive_inference", "cross_round"]
PATTERNS = {
    "身份证号": r"(?<!\d)\d{17}[\dXx](?!\d)",
    "手机号": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "电子邮箱": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "银行卡或长编号": r"(?<!\d)\d{16,19}(?!\d)",
}


def detect(text):
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, text)]


def transform(value, method, mappings):
    if method == "delete":
        return ""
    if method in ("pseudonymize", "generalize"):
        for original, alias in sorted(mappings.items(), key=lambda p: -len(p[0])):
            value = value.replace(original, alias)
        for name, pattern in PATTERNS.items():
            value = re.sub(pattern, f"[{name}已隐去]", value)
    if method == "generalize":
        value = re.sub(r"(\d{4})年(\d{1,2})月\d{1,2}日", r"\1年\2月", value)
        value = re.sub(r"(\d{4})[-/](\d{1,2})[-/]\d{1,2}", r"\1-\2", value)
    return value


def ensure_mappings(case, facts):
    mapping = case.setdefault("mapping", {})
    for fact in facts:
        if fact["field"] == "entity" and fact["value"] not in mapping:
            # Case-specific namespace also prevents accidentally treating aliases as cross-case identity.
            mapping[fact["value"]] = f"主体{len(mapping)+1}（{case['id'][-4:]}）"
    return mapping


def assess(case, pack, facts, decisions, docs, ledger, transport):
    findings, blockers = [], []
    emitted = "\n".join(d["output"] for d in decisions if d["output"])
    detected = detect(emitted)
    if detected:
        blockers.append("仍包含直接标识：" + "、".join(detected))
    for original in case.get("mapping", {}):
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
        findings.append(f"已纳入 {len(ledger)} 条已发送或结果不明的历史披露；完整跨轮攻击尚未实现。")
    demo = case["mode"] == "demo"
    if case.get("scenario") == "stop":
        blockers.append("合成示例关键证据不完整，主动停止")
    if not demo:
        if pack["status"] != "published" or not pack.get("review_record"):
            blockers.append("适用规则尚未正式发布")
        blockers.append("正式案件所需四类风险攻击策略尚未实现，禁止外发")
    if transport == "mock" and not demo:
        blockers.append("正式案件不能使用模拟调用")
    attacks = [{"kind": name, "capability": "unimplemented", "outcome": "not_run"} for name in ATTACKS]
    findings.append("确定性检测不是完整再识别测试；未执行的攻击不计为通过。")
    if demo:
        findings.append("仅允许固定合成数据演示；完整风险检验仍未完成。")
    return {"completion": "incomplete", "findings": findings, "blockers": list(dict.fromkeys(blockers)), "attacks": attacks, "ledger_version": case["ledger_version"], "approval_allowed": not blockers, "demo_exception": demo}


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
        issues = []
        if not ids or not valid:
            issues.append("引用不存在或指向未披露事实")
        if any(n not in support for n in re.findall(r"\d+(?:\.\d+)?", text)):
            issues.append("日期或金额存在未在引用事实中出现的数字")
        if text not in support:
            issues.append("改写或新增陈述需要人工核实语义与证据归属")
        if not text.strip():
            issues.append("陈述为空")
        anchors = [s for i in ids if i in by_id for s in by_id[i]["source_ids"]]
        results.append({"id": digest(item)[:16], "text": text, "source_ids": ids, "anchors": anchors, "issues": issues, "status": "needs_review" if issues else "source_matched", "reviewed": False})
    if not results:
        raise ValueError("模型未返回任何事实陈述")
    return results
