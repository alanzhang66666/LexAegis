# SPDX-License-Identifier: Apache-2.0
# Modified for LexAegis from the Ianvs compliance/risk structure at 8150672e.
"""Provider, protocol and compliance governance helpers."""
from datetime import datetime, timezone

from .util import digest, now, uid


REQUIRED_ATTACKS = ("identity", "candidate_set", "sensitive_inference", "cross_round")


def provider_checks(profile: dict | None, *, domain: str, task_type: str, fields: set[str]) -> list[dict]:
    checks = []

    def add(name, passed, detail, basis=None):
        checks.append({"id": uid("check"), "name": name, "status": "pass" if passed else "fail", "basis": basis or [], "detail": detail})

    if not profile:
        add("服务商档案", False, "未选择服务商档案")
        return checks
    known = profile.get("role") not in (None, "unknown") and bool(profile.get("processing_regions"))
    known = known and profile.get("training_use") != "unknown" and profile.get("human_access") != "unknown"
    add("关键处理条件", known, "角色、处理地区、训练使用和人工访问必须人工登记")
    valid = profile.get("status") == "reviewed" and bool(profile.get("contract_reference")) and bool(profile.get("impact_assessment_reference"))
    if profile.get("valid_until"):
        try:
            expires = datetime.fromisoformat(profile["valid_until"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            valid = valid and expires > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            valid = False
    add("合同与影响评估", valid, "档案须经复核且合同、影响评估在有效期内")
    add("任务范围", task_type in profile.get("allowed_tasks", []), "任务必须在允许清单内")
    add("案由范围", domain in profile.get("allowed_domains", []), "案由必须在允许清单内")
    add("字段范围", fields <= set(profile.get("allowed_fields", [])), "全部披露字段必须在允许清单内")
    add("传输方式", "cloud" in profile.get("allowed_transports", []), "正式外发仅接受登记的 cloud 传输")
    return checks


def protocol_content_hash(protocol: dict) -> str:
    return digest({key: value for key, value in protocol.items() if key != "content_hash"})


def protocols_for_pack(repo, pack: dict) -> list[dict]:
    """Resolve the exact frozen protocols referenced by a pack."""
    references = {(item["id"], item["version"]) for item in pack.get("risk_protocols", [])}
    protocols = []
    for protocol in repo.list("risk_protocol"):
        if (protocol.get("id"), protocol.get("version")) not in references:
            continue
        if protocol.get("status") != "frozen" or protocol.get("content_hash") != protocol_content_hash(protocol):
            continue
        protocols.append(protocol)
    by_kind = {protocol["kind"]: protocol for protocol in protocols}
    missing = [kind for kind in REQUIRED_ATTACKS if kind not in by_kind]
    if missing:
        raise ValueError("案由包未绑定四类有效冻结协议：" + "、".join(missing))
    return [by_kind[kind] for kind in REQUIRED_ATTACKS]


def frozen_protocol_runs(repo, task_id: str, attack_input_hash: str, pack: dict) -> list[dict]:
    try:
        protocols = {p["id"]: p for p in protocols_for_pack(repo, pack)}
    except ValueError:
        return [{"kind": kind, "outcome": "not_run"} for kind in REQUIRED_ATTACKS]
    latest = {}
    for run in repo.list("attack_run", task_id):
        protocol = protocols.get(run.get("protocol_id"))
        if (protocol and run.get("protocol_hash") == protocol["content_hash"]
                and run.get("attack_input_hash") == attack_input_hash):
            latest[protocol["kind"]] = {**run, "kind": protocol["kind"]}
    return [latest.get(kind, {"kind": kind, "outcome": "not_run"}) for kind in REQUIRED_ATTACKS]


def validate_formal_gate(pack: dict, provider_results: list[dict], attacks: list[dict], isolation_verified: bool) -> list[str]:
    blockers = []
    if pack.get("schema_version") != 2 or pack.get("status") != "published" or not pack.get("content_hash"):
        blockers.append("适用规则尚未正式发布")
        blockers.append("适用的 V2 法学规则包尚未冻结并正式发布")
    if any(check["status"] != "pass" for check in provider_results):
        blockers.append("服务商处理条件或影响评估不完整")
    outcomes = {attack.get("kind"): attack.get("outcome") for attack in attacks}
    if any(outcomes.get(kind) != "resisted" for kind in REQUIRED_ATTACKS):
        blockers.append("四类冻结攻击未全部达到 resisted")
    if not isolation_verified:
        blockers.append("隔离部署自检未通过")
    return blockers


def publish_pack_record(pack: dict, actor: str) -> dict:
    if pack.get("status") != "reviewed":
        raise ValueError("只有 reviewed 案由包可以发布")
    if not pack.get("review_record") or not pack.get("reviewer") or not pack.get("references"):
        raise ValueError("发布前必须具有法源、审核人和审核记录")
    if (pack.get("legal_status") != "reviewed" or not pack.get("dispatch_allowed")
            or not pack.get("published_scope") or len(pack.get("risk_weights", {})) != 5):
        raise ValueError("发布前必须冻结法学状态、适用范围、外发许可和五类风险权重")
    frozen = dict(pack)
    frozen.update(status="published", reviewed_at=pack.get("reviewed_at") or now(), frozen_at=now())
    frozen["content_hash"] = digest({key: value for key, value in frozen.items() if key != "content_hash"})
    frozen["published_by"] = actor
    return frozen
