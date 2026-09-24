"""Import existing legal assets without implying review or dispatch approval.

The historical no-argument mode still refreshes the repository draft pack. Use
``--registry-db`` to atomically import the complete content-addressed registry.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from lexaegis.legal_assets import import_existing_legal_assets
from lexaegis.registry import validate_pack
from lexaegis.storage import Store

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "packs" / "labor_v2_draft.json"
CATALOG = ROOT / "legal" / "sources" / "总法源目录_合并版.json"
PI_XLSX = ROOT / "legal" / "sources" / "个人信息-个保法-处理方式对应表.xlsx"
OTHER_XLSX = ROOT / "legal" / "sources" / "其他敏感客体-相应法条-处理方式对照表.xlsx"
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

DETECTORS = {
    "姓名": ["姓名"],
    "身份证件号码": ["身份证号"],
    "手机号": ["手机号"],
    "电子邮箱": ["电子邮箱"],
    "银行账号/银行卡号": ["银行卡或长编号"],
}

REVIEW_CONDITIONS = [
    {
        "id": "pack_sources_unfrozen", "trigger": "法源未冻结",
        "why_machine_cannot": "案由包法学状态未冻结，不能把草稿引用写成已发布法源。",
        "what_to_verify": ["法学审核是否完成", "citation_status 是否仍为 draft_reference"],
        "gate_id": "G5", "blocking": True,
    },
    {
        "id": "rule_necessity_uncertain", "trigger": "规则必要性不确定",
        "why_machine_cannot": "字段必要性为 uncertain 时，机器不能自行决定保留或删除。",
        "what_to_verify": ["该字段是否为当前任务必要事实", "能否用更低精度替代"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "attack_protocol_incomplete", "trigger": "攻击协议未完成",
        "why_machine_cannot": "四类冻结攻击未全部 resisted，工程检验未完成。",
        "what_to_verify": ["是否已按冻结协议跑完四类攻击", "结果是否仅为工程基线"],
        "gate_id": "G8", "blocking": True,
    },
    {
        "id": "interp2_effective_unknown", "trigger": "解释（二）适用时间不明",
        "why_machine_cannot": "案件日期不明时不能自动适用解释（二）。",
        "what_to_verify": ["争议事实发生时间", "是否落入 2025-09-01 施行范围"],
        "legal_source_ids": ["spc_labor_interp_2"], "gate_id": "G5", "blocking": True,
    },
    {
        "id": "unknown_condition_restricted", "trigger": "条件未知已限制输出而非默许外发",
        "why_machine_cannot": "未知条件必须限制输出，不能默许外发。",
        "what_to_verify": ["缺失条件能否补全", "限制后的输出是否仍能完成任务"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "special_law_unconfirmed", "trigger": "特别法是否适用无法确认",
        "why_machine_cannot": "同一事实可能同时涉及劳动法、个保法、传染病防治等规则。",
        "what_to_verify": ["具体法条", "适用对象", "适用行为", "事实是否满足构成要件"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "authority_unconfirmed", "trigger": "处分权限不明确",
        "why_machine_cannot": "能够查看、复制案件材料不当然意味着可以向任意第三方提供。",
        "what_to_verify": ["授权人", "授权范围", "是否包含第三方提供或委托处理", "是否存在相反限制"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "confidentiality_scope_unconfirmed", "trigger": "保密义务范围不明确",
        "why_machine_cannot": "NDA 或合同可能只限制公开披露，也可能限制所有第三方处理。",
        "what_to_verify": ["是否禁止向当前 AI 服务商提供", "是否允许受托处理", "是否有例外"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "court_order_unconfirmed", "trigger": "司法或仲裁保密措施不明确",
        "why_machine_cannot": "仅有不公开审理等描述不足以判断是否限制当前第三方。",
        "what_to_verify": ["具体决定", "保密令或承诺书", "限制接触或复制的范围"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "provider_role_unconfirmed", "trigger": "AI 服务商处理关系不明确",
        "why_machine_cannot": "委托处理与向其他处理者提供适用规则不同。",
        "what_to_verify": ["服务商法律角色", "处理目的", "保存、训练、人工访问、再委托"],
        "gate_id": "G3", "blocking": True,
    },
    {
        "id": "cross_border_unconfirmed", "trigger": "是否发生跨境处理无法确认",
        "why_machine_cannot": "境外公司或品牌不等于当前数据已经跨境。",
        "what_to_verify": ["数据实际流向", "存储和访问地点", "适用跨境机制"],
        "gate_id": "G3", "blocking": True,
    },
    {
        "id": "rule_conflict", "trigger": "规则之间存在真实冲突",
        "why_machine_cannot": "不同规则可能约束不同主体或不同处理行为，不能机械从严。",
        "what_to_verify": ["各规范效力", "适用范围", "特别法关系", "能否通过最小化协调"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "reidentification_unconfirmed", "trigger": "去标识化后能否重新识别无法确认",
        "why_machine_cannot": "删除姓名不代表组合信息一定无法识别。",
        "what_to_verify": ["直接标识符", "准标识符", "组合识别风险", "信息主体归属"],
        "gate_id": "G7", "blocking": True,
    },
    {
        "id": "decisive_fact_missing", "trigger": "决定性事实缺失",
        "why_machine_cannot": "法律结论所需的关键事实没有出现在当前材料中。",
        "what_to_verify": ["补充何种事实才能完成法律判断"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "state_secret_unconfirmed", "trigger": "是否属于国家秘密无法确认",
        "why_machine_cannot": "内部、重要、涉政等标签不足以证明法定秘密属性。",
        "what_to_verify": ["秘密属性", "定密依据", "涉密等级", "当前处理环境是否满足保密要求"],
        "gate_id": "G0", "blocking": True,
    },
    {
        "id": "anonymization_unconfirmed", "trigger": "去标识化是否达到匿名化无法确认",
        "why_machine_cannot": "去标识化后仍可能属于个人信息；匿名化要求无法识别且不能复原。",
        "what_to_verify": ["是否达到无法识别且不能复原", "是否仍需适用个保法"],
        "gate_id": "G0", "blocking": True,
    },
]


def xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in si.iter() if node.tag.endswith("}t")) for si in root]
        sheet = next(name for name in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name))
        rows = []
        for row in ET.fromstring(archive.read(sheet)).iter(MAIN + "row"):
            cells = []
            for cell in row:
                node = cell.find(MAIN + "v")
                if cell.get("t") == "s" and node is not None:
                    cells.append(shared[int(node.text)].strip())
                else:
                    cells.append((node.text or "").strip() if node is not None else "")
            rows.append(cells)
        return [row for row in rows if any(row)]


def seed_fields(item: dict) -> dict:
    item = dict(item)
    item.setdefault("tier", "司法解释" if "解释" in item.get("title", "") else "法律")
    item.setdefault("provision_text", "")
    item.setdefault("norm_summary", item.get("snapshot") or "")
    item.setdefault("applies_to", "")
    item.setdefault("trigger", "")
    item.setdefault("consequence", "")
    item.setdefault("review_required", False)
    item.setdefault("review_trigger", "")
    item["rule_nature"] = "statutory"
    item["granularity"] = "article"
    item["merged_from"] = "pack_seed"
    item["citation_status"] = "draft_reference"
    return item


def object_id(prefix: str, index: int, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", f"{prefix}_{index:02d}")
    return slug[:80]


def split_carriers(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[、，,；;]", text or "") if part.strip()][:12]


ARTICLE_SPAN = re.compile(r"第\s*([\d、，,.\-—～~至到]+)\s*条")
BOOK_TITLE = re.compile(r"《([^》]+)》")
INTERP1_MARKERS = ("解释（一）", "解释(一)", "解释一")

NOT_HARD_BAN = [
    {"id": "nhb_01", "category": "不满14周岁未成年人个人信息",
     "why_not_automatic_ban": "属于敏感个人信息并受特别保护，但法律并未规定所有未成年人信息绝对不得由第三方处理。",
     "what_to_judge": ["年龄", "处理基础", "监护人同意或其他法定依据", "必要性", "是否有特别司法或行政限制"]},
    {"id": "nhb_02", "category": "医疗健康、职业病资料",
     "why_not_automatic_ban": "属于敏感个人信息；职业健康档案有专门保存和本人获取规则，但并非一律禁止为合法目的处理。",
     "what_to_judge": ["是否为案件必要事实", "特别法限制", "能否删去无关病历细节", "授权和访问范围"]},
    {"id": "nhb_03", "category": "严重传染病相关信息",
     "why_not_automatic_ban": "只有满足特定主体、受保护信息和披露行为等构成，才能适用明确禁止。",
     "what_to_judge": ["是否属于患者、携带者或疑似患者", "信息是否来源于传染病防治或应急工作", "当前提供是否构成泄露"]},
    {"id": "nhb_04", "category": "商业秘密",
     "why_not_automatic_ban": "法律禁止的是特定非法获取、披露、使用以及违反保密义务等行为，并非规定商业秘密绝对不能由受托第三方处理。",
     "what_to_judge": ["商业秘密构成", "保密义务", "具体保密措施", "第三方处理权限"]},
    {"id": "nhb_05", "category": "工资、社保、银行账户",
     "why_not_automatic_ban": "可能属于个人信息或敏感个人信息，但法律允许在具有合法基础、充分必要性和保护措施的条件下处理。",
     "what_to_judge": ["任务必要性", "合法处理基础", "是否需要完整账号", "最小化程度"]},
    {"id": "nhb_06", "category": "诉讼/仲裁材料",
     "why_not_automatic_ban": "案件材料可能有保密属性，但有权查阅或复制与有权向第三方提供不同。",
     "what_to_judge": ["具体保密措施", "材料来源", "授权范围", "外部接收方角色"]},
    {"id": "nhb_07", "category": "律师执业中知悉的信息",
     "why_not_automatic_ban": "律师负有保密义务，但不能仅凭律师保密条款推导出任何技术服务商均不得接触。",
     "what_to_judge": ["办案必要性", "委托或提供关系", "授权", "保密安排", "是否另有特别限制"]},
    {"id": "nhb_08", "category": "公开裁判文书或公开信息",
     "why_not_automatic_ban": "已经公开并不等于可无限制二次处理。",
     "what_to_judge": ["是否属于合法公开", "处理是否在合理范围", "是否对个人权益有重大影响"]},
    {"id": "nhb_09", "category": "境外AI或境外品牌",
     "why_not_automatic_ban": "境外主体身份本身不等于发生个人信息出境。",
     "what_to_judge": ["实际数据流向", "存储地点", "境外访问", "出境豁免、评估、标准合同或认证路径"]},
    {"id": "nhb_10", "category": "工作秘密",
     "why_not_automatic_ban": "工作秘密不同于国家秘密，本身不当然适用国家秘密的绝对禁止。",
     "what_to_judge": ["是否确属工作秘密", "具体管理制度", "外部提供限制是否明确"]},
]

REPLY_TEMPLATES = [
    {"id": "reply_needs_verification", "disposition": "needs_verification", "title": "法律依据或决定性事实不确定",
     "body": "当前材料是否可以进行外部处理暂不能确定。待核实事项须写明法律适用、处分权限、保密义务、外部处理关系、跨境情况或其他决定性事实。可能涉及依据须写法源名称和具体条款。目前无法确认的关键事实须逐项列明。在上述事项核实完成前，不将相关原始材料提交外部模型。本段只展示，不自动填入结论。"},
    {"id": "reply_prohibited", "disposition": "prohibited", "title": "已经确认当前行为存在明确禁止",
     "body": "经核实，当前材料属于具体保护对象，具体法律条款、法院或仲裁保密措施或具有约束力的明确保密义务直接限制当前向外部第三方提供、传输或处理的行为。现有删除、打码、加密或范围缩减措施不能消除该限制。不得向当前外部模型提交。本段只展示，不自动填入结论。"},
    {"id": "reply_needs_minimization", "disposition": "needs_minimization", "title": "信息敏感，但并未形成硬性禁止",
     "body": "当前材料包含敏感信息，但现有信息不足以支持法律明确禁止外部处理的结论。请先执行任务必要性审查和最小化处理。处理后如合法基础、权限及外部处理条件均明确，可继续处理；如出现决定性不确定事项，再转人工复核。本段只展示，不自动填入结论。"},
    {"id": "reply_allowed", "disposition": "allowed", "title": "规则存在表面冲突时不得直接从严禁止",
     "body": "多项规则可能同时适用。当前不能仅以从严原则直接判断禁止。请分别核实保护对象、处理行为、义务主体、处分权限和规范关系。如通过最小化或调整处理方式可以同时满足各项规则，应优先采用可满足任务目的的最小处理方案。本段只展示，不自动放行。"},
]

CONFLICT_CHECKLIST = [
    {"id": "conflict_01", "step": 1, "prompt": "先确定保护对象：是个人信息、敏感个人信息、隐私、商业秘密、国家秘密，还是受到具体程序保密措施保护的材料。"},
    {"id": "conflict_02", "step": 2, "prompt": "再确定处理行为：是本地存储、委托处理、向其他个人信息处理者提供、公开披露，还是跨境提供。"},
    {"id": "conflict_03", "step": 3, "prompt": "再确定义务主体：该规则约束的是律师、律所、客户、法院或仲裁机构、AI服务商，还是其他主体。"},
    {"id": "conflict_04", "step": 4, "prompt": "再判断处分权限：查阅权、复制权、使用权、委托处理权和向第三方提供权不能混为一谈。"},
    {"id": "conflict_05", "step": 5, "prompt": "再确定规范关系：判断一般法、特别法、司法解释、程序规则、行政规范与合同约定各自解决什么问题。"},
    {"id": "conflict_06", "step": 6, "prompt": "最后判断能否通过删除无关信息、去除直接标识符、减少数据范围等方式同时满足不同规则。不能因为存在疑问就直接把疑问写成法律禁止。"},
]


def article_numbers(text: str) -> set[int]:
    found: set[int] = set()
    for match in ARTICLE_SPAN.finditer(text or ""):
        for part in re.split(r"[、，,]", match.group(1)):
            part = part.strip()
            bounds = [item for item in re.split(r"[.\-—－～~至到]+", part) if item.isdigit()]
            if len(bounds) == 2:
                start, end = int(bounds[0]), int(bounds[1])
                if 0 < end - start <= 80:
                    found.update(range(start, end + 1))
                else:
                    found.update({start, end})
            elif len(bounds) == 1:
                found.add(int(bounds[0]))
    return found


def strip_title(text: str) -> str:
    title = (text or "").strip().strip("《》").replace("〈", "").replace("〉", "")
    title = re.sub(r"^中华人民共和国", "", title)
    title = re.sub(r"(相关规定|的规定)$", "", title)
    return re.sub(r"\s+", "", title)


def title_score(catalog_title: str, cited: str) -> int:
    catalog = strip_title(catalog_title)
    cited_title = strip_title(cited)
    if not catalog or not cited_title:
        return 0
    if catalog == cited_title:
        return 100
    if cited_title in catalog:
        return 80 + min(len(cited_title), 19)
    if catalog in cited_title:
        return 70 + min(len(catalog), 19)
    return 0


def citation_chunks(text: str, default_title: str | None = None) -> list[tuple[str | None, str]]:
    raw = (text or "").strip()
    if not raw:
        return []
    if default_title and "《" not in raw:
        return [(default_title, raw)]
    parts = re.split(r"(《[^》]+》)", raw)
    chunks: list[tuple[str | None, str]] = []
    current = default_title
    pending = ""
    for part in parts:
        if not part.strip():
            continue
        match = BOOK_TITLE.fullmatch(part.strip())
        if match:
            if current and pending.strip():
                chunks.append((current, pending.strip()))
                pending = ""
            current = match.group(1)
            continue
        pending += part
    if current and pending.strip():
        chunks.append((current, pending.strip()))
    elif pending.strip():
        chunks.append((default_title, pending.strip()))
    elif current and not chunks:
        chunks.append((current, ""))
    return chunks


def match_citations(text: str, catalog: list[dict], default_title: str | None = None) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    unresolved: list[str] = []
    for title, body in citation_chunks(text, default_title):
        wanted = article_numbers(body)
        label = f"{title or ''}{body}".strip()
        if not title:
            unresolved.append(label)
            continue
        scored = []
        for item in catalog:
            score = title_score(item.get("title") or "", title)
            if score < 70:
                continue
            item_articles = article_numbers(" ".join(item.get("articles") or []))
            overlap = wanted & item_articles if wanted else set()
            if wanted and not overlap:
                continue
            if not wanted and score < 100:
                continue
            scored.append((score, len(overlap), item))
        if not scored:
            unresolved.append(label)
            continue
        if any(item.get("granularity") == "article" for _score, _overlap, item in scored):
            scored = [row for row in scored if row[2].get("granularity") == "article"]
        scored.sort(key=lambda row: (-row[0], -row[1], len(" ".join(row[2].get("articles") or [])), row[2].get("id") or ""))
        for _score, _overlap, item in scored:
            source_id = item.get("id")
            if not source_id or source_id in matched:
                continue
            if source_id == "spc_labor_interp_1" and not any(marker in (text or "") for marker in INTERP1_MARKERS):
                continue
            matched.append(source_id)
    return matched, unresolved


def nature_from_sources(matched_ids: list[str], catalog: list[dict], nature_cell: str) -> str:
    by_id = {item.get("id"): item for item in catalog}
    natures = {(by_id.get(source_id) or {}).get("rule_nature") for source_id in matched_ids}
    if "statutory" in natures:
        return "statutory"
    if "standard_reference" in natures or "国家标准" in (nature_cell or "") or "GB/T" in (nature_cell or ""):
        return "standard_reference"
    return "project_control"


def mapping_rules(catalog: list[dict]) -> list[dict]:
    items = []
    pi_rows = xlsx_rows(PI_XLSX)[1:]
    for index, row in enumerate(pi_rows, start=1):
        name = row[0]
        citation = row[3] if len(row) > 3 else ""
        matched, unresolved = match_citations(citation, catalog, default_title="个人信息保护法")
        items.append({
            "id": object_id("pi", index, name),
            "object_type": name,
            "object_group": "personal_information",
            "carriers": split_carriers(row[1] if len(row) > 1 else ""),
            "is_sensitive_pi": (row[2] if len(row) > 2 else "").startswith("是") or "敏感" in (row[2] or ""),
            "default_handling": row[6] if len(row) > 6 else "",
            "provision_text": row[4] if len(row) > 4 else "",
            "norm_summary": row[5] if len(row) > 5 else "",
            "detector_categories": DETECTORS.get(name, []),
            "review_condition_ids": ["special_law_unconfirmed"] if (row[8] if len(row) > 8 else "").startswith("是") else [],
            "legal_source_ids": matched,
            "unresolved_citations": unresolved,
            "rule_nature": nature_from_sources(matched, catalog, row[7] if len(row) > 7 else ""),
        })
    other_rows = xlsx_rows(OTHER_XLSX)[1:]
    for index, row in enumerate(other_rows, start=1):
        name = row[0]
        citation = row[2] if len(row) > 2 else ""
        review = (row[7] if len(row) > 7 else "").startswith("是")
        matched, unresolved = match_citations(citation, catalog)
        items.append({
            "id": object_id("obj", index, name),
            "object_type": name,
            "object_group": "other_sensitive_object",
            "carriers": split_carriers(row[1] if len(row) > 1 else ""),
            "is_sensitive_pi": False,
            "default_handling": row[5] if len(row) > 5 else "",
            "provision_text": row[3] if len(row) > 3 else "",
            "norm_summary": row[4] if len(row) > 4 else "",
            "detector_categories": [],
            "review_condition_ids": ["special_law_unconfirmed", "confidentiality_scope_unconfirmed"] if review else [],
            "legal_source_ids": matched,
            "unresolved_citations": unresolved,
            "rule_nature": nature_from_sources(matched, catalog, row[6] if len(row) > 6 else ""),
        })
    return items


def update_draft_pack() -> None:
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    existing = []
    for item in pack["legal_sources"]:
        if item.get("merged_from") == "pack_seed" or item.get("id") in {
            "spc_labor_interp_1", "spc_labor_interp_2", "lawyer_law_2026_09_01",
        }:
            existing.append(seed_fields(item))
        else:
            existing.append(item)
    existing_ids = {item["id"] for item in existing}
    added = [item for item in catalog if item["id"] not in existing_ids]
    pack["legal_sources"] = existing + added
    pack["manual_review_conditions"] = [
        {**item, "legal_source_ids": item.get("legal_source_ids") or []}
        for item in REVIEW_CONDITIONS
    ]
    pack["sensitive_object_rules"] = mapping_rules(pack["legal_sources"])
    pack["not_hard_ban_categories"] = NOT_HARD_BAN
    pack["reply_templates"] = REPLY_TEMPLATES
    pack["conflict_checklist"] = CONFLICT_CHECKLIST
    pack["dispatch_allowed"] = False
    pack["legal_status"] = "pending_legal_review"
    pack["status"] = "draft"
    validate_pack(pack)
    PACK.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unresolved = sum(len(item.get("unresolved_citations") or []) for item in pack["sensitive_object_rules"])
    print(
        "legal_sources", len(pack["legal_sources"]),
        "review", len(pack["manual_review_conditions"]),
        "objects", len(pack["sensitive_object_rules"]),
        "unresolved_citations", unresolved,
        "dispatch_allowed", pack["dispatch_allowed"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入仓库现有法学资产")
    parser.add_argument(
        "--registry-db",
        type=Path,
        help="原子写入内容寻址法律资产注册表的 SQLite 路径；不提供时保留原有 pack 刷新行为",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=ROOT,
        help="只读取该仓库根目录内的既有资产",
    )
    args = parser.parse_args()
    if args.registry_db is None:
        update_draft_pack()
        return
    report = import_existing_legal_assets(Store(args.registry_db), args.repository_root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
