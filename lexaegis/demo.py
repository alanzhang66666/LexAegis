"""Only these bundled synthetic facts can enter demo runs. No user uploads."""
SCENARIOS = {
    "success": {
        "name": "合成案例 · 乔安工资争议",
        "facts": [
            ("entity", "乔安"),
            ("entity", "云岑示例商贸有限公司"),
            ("relation", "乔安与云岑示例商贸有限公司建立劳动关系。"),
            ("event", "乔安主张云岑示例商贸有限公司未支付2025年5月工资。"),
            ("date", "双方于2025年1月8日签署劳动合同。"),
            ("amount", "劳动者主张未支付工资9800元。"),
            ("evidence", "劳动合同、2025年5月工资核算表和工资支付记录用于支持劳动关系及工资请求。"),
        ],
        "note": "所有名称、金额与经过均为合成示例；不对应真实案件。",
    },
    "linkage": {
        "name": "合成案例 · 组合线索风险",
        "facts": [("entity", "顾舟"), ("entity", "晨岛示例研究所"), ("event", "顾舟是虚构月港镇唯一的深海机器人夜班检修员，并于2025年2月17日公开获奖。"), ("relation", "顾舟与晨岛示例研究所存在劳动关系。")],
        "note": "唯一岗位、地点、日期组合构成演示风险；替换姓名仍不足。",
    },
    "human_veto": {
        "name": "合成案例 · 人工复核否决",
        "facts": [("entity", "林澄"), ("entity", "星桥示例科技有限公司"),
                  ("relation", "林澄与星桥示例科技有限公司建立劳动关系。"),
                  ("event", "林澄在桥湾园区从事夜班设备检修，于2025年4月16日参加技术表彰活动。"),
                  ("amount", "劳动者主张未支付工资12000元。"),
                  ("evidence", "劳动合同与工资表用于支持劳动关系及工资金额。")],
        "note": "合成复核情境；初检不包含补充公开资料。技术提请和法学否决均由具名人员实际操作。",
        "supplemental_evidence": [
            {"id": "synthetic_public_record", "title": "合成公开资料 · 技术表彰记录",
             "text": "合成记录：林澄，桥湾园区夜班设备检修人员，2025年4月16日参加技术表彰活动。三条线索对应同一记录。",
             "data_origin": "bundled_synthetic"},
            {"id": "synthetic_processing_scope", "title": "合成处理范围说明",
             "text": "本次目的为工资争议事实摘要。具体园区、夜班岗位和表彰日期不是本次摘要的必要内容，需复核后调整披露。",
             "data_origin": "bundled_synthetic"},
        ],
    },
    "stop": {
        "name": "合成案例 · 主动停止",
        "facts": [("entity", "许宁"), ("event", "关键证据扫描不清，劳动关系及争议金额无法核实。")],
        "note": "合成材料故意不完整，用于展示阻断。",
    },
}


def synthetic_protocols():
    """Fixed engineering protocols, never formal red-team attestations."""
    from .contracts import RiskProtocol
    from .governance import protocol_content_hash
    result = []
    for kind in ("identity", "candidate_set", "sensitive_inference", "cross_round"):
        protocol = RiskProtocol(
            id=f"synthetic-{kind}-v1", kind=kind, version="1.0-synthetic",
            status="frozen", attacker_view=["wire_payload", "disclosed_history"],
            auxiliary_data=[], query_budget=3, time_budget_seconds=30,
            success_criteria={"operator": "gte", "note": "合成工程基线；无独立证据时返回不确定"},
            threshold=0.5, random_seed=20260919,
        ).model_dump()
        protocol["content_hash"] = protocol_content_hash(protocol)
        result.append(protocol)
    return result


def seed_synthetic_protocols(repo):
    protocols = synthetic_protocols()
    for protocol in protocols:
        try:
            old = repo.get(protocol["id"], "risk_protocol")
        except KeyError:
            old = None
        if old is not None and old != protocol:
            raise ValueError("合成协议版本冲突，拒绝覆盖")
        repo.put("risk_protocol", protocol)
    for pack in repo.list("pack"):
        if pack.get("status") == "demo":
            pack["risk_protocols"] = [{"id": p["id"], "version": p["version"]} for p in protocols]
            repo.put("pack", pack)


# Exact, reviewed recording attachments. This identifies facts, never an approval.
RECORDING_DOCUMENTS = {
    "41d51e9339f76a183f347928d3a6a342de0425717ce6b19db63e08d9097d25ba": "linkage",
    "4e2a3e0a0d5c2068ceb86b75636f0ea241d31cfefd8eb11e44f12c9315c05496": "human_veto",
    "25600e56fe86830971fe053085a106481319cde67753725d83d3d0537a439976": "success",
}


def _load_local_recording_bundle():
    """Load a reviewed offline bundle; original case materials stay outside Git."""
    import hashlib
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / 'data/recording_adapted/scenarios.json'
    if not path.exists():
        return
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != 'cdf14ba5244d4fa9ef23127d97064611cbb45d7e85831fdf0afbd1e1ff15e542':
        raise ValueError('本地案例事实包校验失败，请恢复已登记版本')
    bundle = json.loads(data)
    if set(bundle['scenarios']) & set(SCENARIOS):
        raise ValueError('本地案例不得覆盖既有案例')
    SCENARIOS.update(bundle['scenarios'])
    RECORDING_DOCUMENTS.update(bundle['documents'])


_load_local_recording_bundle()
