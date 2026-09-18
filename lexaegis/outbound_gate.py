"""Single formal-cloud outbound gate. Not a send authorization by itself."""
from .d_path import combination_blockers, combination_input_hash, layer_b_blockers, ledger_corpus, same_recipient_ledger
from .governance import REQUIRED_ATTACKS, pack_content_hash

G0 = "G0"
G2 = "G2"
G3 = "G3"
G5 = "G5"
G7 = "G7"
G8 = "G8"
G9 = "G9"
G_PRODUCT = "G-product"

PACK_UNPUBLISHED = "适用规则尚未正式发布"
PACK_LEGAL_UNFROZEN = "案由包尚未冻结法学状态、外发许可或适用范围"
WEIGHTS_UNFROZEN = "五类风险信号权重尚未冻结"
PROVIDER_INCOMPLETE = "服务商处理条件或影响评估不完整"
ATTACKS_NOT_RESISTED = "四类冻结攻击未全部达到 resisted"
ISOLATION_UNVERIFIED = "隔离部署自检未通过"
CLOUD_SLOT_MISSING = "云端服务或模型未配置"

FROZEN_WEIGHTS = frozenset({"entity", "density", "context", "combination", "cross_round"})
DEMO_COMBINATION_TERMS = frozenset({"唯一", "公开获奖"})
DEMO_COMBINATION_BLOCKER = "组合线索风险：唯一岗位或公开事件仍保留"

PRODUCT_DISPATCH_BLOCKED = "blocked"


def product_dispatch_state():
    """Product latch. Isolation-library publish is not an opening."""
    return PRODUCT_DISPATCH_BLOCKED


def attacks_all_resisted(attacks) -> bool:
    outcomes = {item.get("kind"): item.get("outcome") for item in (attacks or [])}
    return all(outcomes.get(kind) == "resisted" for kind in REQUIRED_ATTACKS)


def forbidden_term_blocker(matched):
    if set(matched) <= DEMO_COMBINATION_TERMS:
        return DEMO_COMBINATION_BLOCKER
    return "组合线索风险：" + "、".join(matched) + "仍保留"


def combination_binding_hash(emitted, ledger, *, prompt="", recipient=None):
    scoped = same_recipient_ledger(ledger, recipient)
    return combination_input_hash(emitted or "", ledger_corpus(scoped), prompt or "")


KIND_PROHIBITION = "prohibition"
KIND_VERIFICATION = "verification"
KIND_MINIMIZATION = "minimization"
KIND_ENGINEERING = "engineering"

_MESSAGE_KIND = {
    PACK_UNPUBLISHED: KIND_ENGINEERING,
    PACK_LEGAL_UNFROZEN: KIND_ENGINEERING,
    WEIGHTS_UNFROZEN: KIND_ENGINEERING,
    PROVIDER_INCOMPLETE: KIND_ENGINEERING,
    ATTACKS_NOT_RESISTED: KIND_ENGINEERING,
    ISOLATION_UNVERIFIED: KIND_ENGINEERING,
    CLOUD_SLOT_MISSING: KIND_ENGINEERING,
    "命中规则硬性禁止项": KIND_PROHIBITION,
    "仍包含未替换的登记主体": KIND_MINIMIZATION,
    "存在尚未解决的字段复核事项或已被规则限制的字段": KIND_VERIFICATION,
    "必要内容被删光，不能按零泄露计成功": KIND_VERIFICATION,
    "没有可发送的事实": KIND_VERIFICATION,
    "事实尚未确认或来源版本已更新": KIND_VERIFICATION,
    "材料解析、OCR 或转写复核未完成": KIND_VERIFICATION,
    "跨轮外发已超过工程预算（字符或条数）": KIND_ENGINEERING,
    "合成示例关键证据不完整，主动停止": KIND_VERIFICATION,
    "正式案件不能使用模拟调用": KIND_ENGINEERING,
}

_PREFIX_KIND = (
    ("仍包含直接标识：", KIND_MINIMIZATION),
    ("组合线索仍含准标识：", KIND_MINIMIZATION),
    ("组合线索风险：", KIND_VERIFICATION),
    ("硬性禁止四要件未完成确认", KIND_VERIFICATION),
)


def classify_kind(gate_id, message):
    if message in _MESSAGE_KIND:
        return _MESSAGE_KIND[message]
    for prefix, kind in _PREFIX_KIND:
        if (message or "").startswith(prefix):
            return kind
    if gate_id == G2:
        return KIND_ENGINEERING
    if gate_id == G5:
        return KIND_ENGINEERING
    if gate_id == G8:
        return KIND_ENGINEERING
    if gate_id == G9:
        return KIND_ENGINEERING
    return KIND_VERIFICATION


def _hit(gate_id, message, kind=None):
    return {"id": gate_id, "message": message, "kind": kind or classify_kind(gate_id, message)}


def _dedupe(hits):
    seen = set()
    ordered = []
    for hit in hits:
        key = (hit["id"], hit["message"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(hit)
    return ordered


def _pack_unpublished(pack):
    pack = pack or {}
    return (
        pack.get("schema_version") != 2
        or pack.get("status") != "published"
        or not pack.get("content_hash")
        or pack.get("content_hash") != pack_content_hash(pack)
    )


def _pack_legal_unfrozen(pack):
    pack = pack or {}
    return (
        pack.get("legal_status") != "reviewed"
        or not pack.get("dispatch_allowed")
        or not pack.get("published_scope")
    )


def collect_outbound_blockers(
    case,
    pack,
    *,
    emitted="",
    ledger=None,
    provider_results=None,
    attacks=None,
    isolation_verified=False,
    prompt="",
    recipient=None,
):
    """Formal cloud G2/G3/G5/G7/G8/G9. G0 stays in assess; G1/G6/G10 are paper or other phases."""
    hits = []
    pack = pack or {}
    if _pack_unpublished(pack):
        hits.append(_hit(G5, PACK_UNPUBLISHED))
    if _pack_legal_unfrozen(pack):
        hits.append(_hit(G5, PACK_LEGAL_UNFROZEN))
    if set(pack.get("risk_weights") or {}) != FROZEN_WEIGHTS:
        hits.append(_hit(G5, WEIGHTS_UNFROZEN))
    if any(check.get("status") != "pass" for check in (provider_results or [])):
        hits.append(_hit(G3, PROVIDER_INCOMPLETE))
    if not attacks_all_resisted(attacks):
        hits.append(_hit(G8, ATTACKS_NOT_RESISTED))
    if not isolation_verified:
        hits.append(_hit(G9, ISOLATION_UNVERIFIED))
    terms = [term for term in pack.get("forbidden_terms") or [] if term]
    matched = [term for term in terms if term in (emitted or "")]
    if matched:
        hits.append(_hit(G7, forbidden_term_blocker(matched)))
    for message in combination_blockers(case, emitted, ledger, prompt=prompt, recipient=recipient):
        hits.append(_hit(G7, message))
    for message in layer_b_blockers(case):
        hits.append(_hit(G2, message))
    return _dedupe(hits)


def prohibition_hits(case, pack):
    hits = []
    sources = {item.get("id"): item for item in (pack or {}).get("legal_sources") or []}
    for finding in (case or {}).get("prohibition_findings") or []:
        missing = []
        if not finding.get("protected_object_confirmed"):
            missing.append("保护对象")
        if not finding.get("rule_prohibits_current_act"):
            missing.append("规范是否禁止当前行为")
        if not finding.get("applies_to_current_context"):
            missing.append("是否适用于当前主体、材料和处理方式")
        if not finding.get("minimization_insufficient"):
            missing.append("最小化是否仍不能脱离禁止范围")
        statutory = any(
            (sources.get(source_id) or {}).get("rule_nature") == "statutory"
            for source_id in finding.get("legal_source_ids") or []
        )
        if missing or not statutory:
            detail = "、".join(missing) if missing else "缺少条款级法律规范"
            hits.append(_hit(G0, "硬性禁止四要件未完成确认：" + detail))
        else:
            hits.append(_hit(G0, "命中规则硬性禁止项", KIND_PROHIBITION))
    return hits


def derive_disposition(gates):
    kinds = [hit.get("kind") or classify_kind(hit.get("id"), hit.get("message")) for hit in (gates or [])]
    if KIND_PROHIBITION in kinds:
        disposition = "prohibited"
    elif KIND_VERIFICATION in kinds:
        disposition = "needs_verification"
    elif KIND_MINIMIZATION in kinds:
        disposition = "needs_minimization"
    else:
        disposition = "allowed"
    readiness = "not_ready" if KIND_ENGINEERING in kinds else "ready"
    return disposition, readiness


def attach_disposition(risk):
    disposition, readiness = derive_disposition(risk.get("gates") or [])
    risk["disposition"] = disposition
    risk["system_readiness"] = readiness
    return risk


def validate_formal_gate(pack, provider_results, attacks, isolation_verified) -> list[str]:
    """Subset used by pack-integrity tests: G3/G5-hash/G8/G9. Weights and legal freeze stay in collect."""
    hits = []
    pack = pack or {}
    if _pack_unpublished(pack):
        hits.append(_hit(G5, PACK_UNPUBLISHED))
    if any(check.get("status") != "pass" for check in (provider_results or [])):
        hits.append(_hit(G3, PROVIDER_INCOMPLETE))
    if not attacks_all_resisted(attacks):
        hits.append(_hit(G8, ATTACKS_NOT_RESISTED))
    if not isolation_verified:
        hits.append(_hit(G9, ISOLATION_UNVERIFIED))
    return [hit["message"] for hit in _dedupe(hits)]
