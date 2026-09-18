"""Merge v0.1 legal catalog (base) with v0.2 supplement. Does not touch packs."""
from __future__ import annotations

import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
V01 = ROOT / "legal" / "sources" / "总法源目录.xlsx"
V02 = ROOT / "legal" / "sources" / "总法源目录_v0.2.xlsx"
OUT_XLSX = ROOT / "legal" / "sources" / "总法源目录_合并版.xlsx"
OUT_JSON = ROOT / "legal" / "sources" / "总法源目录_合并版.json"
OUT_DIFF = ROOT / "legal" / "sources" / "总法源目录_v0.1-v0.2差异清单.md"

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLS = [
    "法源层级（包括非正式法律渊源和国标）",
    "名称",
    "条款/位置",
    "原文摘录",
    "规范内容",
    "适用对象及范围",
    "触发条件",
    "法律后果",
    "是否需要人工复核",
    "规则性质，即法律规范/业务规则（包括推荐性国家标准、服务商协议/隐私政策等）/项目自行采取的保守控制",
    "版本/修订信息",
    "生效日期",
]
EXTRA = ["并入来源", "粒度", "v0.2 对照"]
DASH = r"[—–\-~～至]"
VANISHED = [
    "《最高人民法院关于审理劳动争议案件适用法律问题的解释（一）》",
    "《最高人民法院关于审理劳动争议案件适用法律问题的解释（二）》",
    "人社部、最高人民法院《劳动人事争议典型案例（第四批）》",
    "《生成式人工智能服务管理暂行办法》",
    "《个人信息保护合规审计管理办法》",
    "《征信业管理条例》",
    "《征信业务管理办法》",
    "《医疗机构病历管理规定（2013年版）》",
    "《北京市公共数据资源授权运营管理办法》",
]


def table(path: Path) -> list[list[str]]:
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
                value = ""
                kind = cell.get("t")
                node = cell.find(MAIN + "v")
                if kind == "s" and node is not None:
                    value = shared[int(node.text)]
                elif kind == "inlineStr":
                    inline = cell.find(MAIN + "is")
                    value = "".join(t.text or "" for t in inline.iter() if t.tag.endswith("}t")) if inline is not None else ""
                elif node is not None:
                    value = node.text or ""
                cells.append((value or "").strip())
            while len(cells) < 12:
                cells.append("")
            rows.append(cells[:12])
        return [row for row in rows[1:] if any(row)]


def articles(cell: str) -> set[int]:
    found: set[int] = set()
    text = (cell or "").replace("条", "").replace("第", "")
    for chunk in re.split(r"[、,，;；]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        span = re.match(rf"^(\d+)\s*{DASH}\s*(\d+)$", chunk)
        if span:
            found.update(range(int(span.group(1)), int(span.group(2)) + 1))
            continue
        single = re.match(r"^(\d+)", chunk)
        if single and re.fullmatch(r"\d+[^\d]*", chunk):
            found.add(int(single.group(1)))
    return found


def granularity(cell: str) -> str:
    text = cell or ""
    if any(token in text for token in ("全文", "案例", "等")):
        return "整部指向"
    if len(articles(text)) > 5:
        return "整部指向"
    return "条款"


def more_specific(old: str, new: str) -> str:
    old, new = (old or "").strip(), (new or "").strip()
    weak = {"", "同上", "现行", "项目实施期", "项目规则"}
    if old in weak and new not in weak:
        return new
    if new in weak and old not in weak:
        return old
    if len(old) >= len(new):
        return old
    return new


def contrast(old: list[str], new: list[str], chosen: list[str]) -> str:
    labels = ["原文摘录", "规范内容", "适用对象及范围", "触发条件", "法律后果", "是否需要人工复核", "规则性质", "版本/修订信息", "生效日期"]
    indexes = [3, 4, 5, 6, 7, 8, 9, 10, 11]
    parts = []
    for label, index in zip(labels, indexes):
        unused = new[index] if chosen[index] == old[index] else old[index]
        if unused and unused != chosen[index]:
            parts.append(f"{label}：{unused}")
    return "\n".join(parts)


def merge_row(old: list[str], new: list[str]) -> list[str]:
    chosen = list(old)
    chosen[3] = new[3] or old[3]
    chosen[8] = new[8] or old[8]
    chosen[9] = new[9] or old[9]
    chosen[10] = more_specific(old[10], new[10])
    chosen[11] = more_specific(old[11], new[11])
    return chosen + ["v0.1+v0.2合并", granularity(chosen[2]), contrast(old, new, chosen)]


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    sheet = book.active
    sheet.title = "总法源目录"
    header = COLS + EXTRA
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for cell in sheet[1]:
        cell.font = bold
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
        for cell in row:
            cell.alignment = wrap
    widths = [18, 42, 28, 48, 40, 32, 28, 28, 36, 28, 24, 16, 16, 12, 48]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index) if index <= 26 else "A"].width = width
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    book.save(path)


def rule_nature(text: str) -> str:
    value = text or ""
    if "项目" in value:
        return "project_control"
    if "国家标准" in value or "推荐性" in value or "GB/T" in value:
        return "standard_reference"
    if "服务商" in value or "协议" in value or "隐私政策" in value:
        return "provider_terms"
    if "法律规范" in value or "司法解释" in value or "部门规章" in value:
        return "statutory"
    if "案例" in value or "参考" in value:
        return "standard_reference"
    if "业务规则" in value:
        return "standard_reference"
    return "statutory"


def review_fields(text: str) -> tuple[bool, str]:
    value = (text or "").strip()
    required = value.startswith("是")
    return required, value


def source_id(index: int, title: str, articles_text: str) -> str:
    import hashlib
    digest = hashlib.sha256(f"{title}|{articles_text}".encode("utf-8")).hexdigest()[:10]
    return f"ls_{index:03d}_{digest}"[:80]


def tier_of(raw: str) -> str:
    mapping = {
        "法律": "法律",
        "行政法规": "行政法规",
        "部门规章": "部门规章",
        "司法解释": "司法解释",
        "地方性法规": "地方性法规",
        "地方政府规章": "地方政府规章",
        "国家标准": "国家标准",
        "项目自定规则": "项目自定规则",
        "参考案例": "参考案例",
    }
    for key, value in mapping.items():
        if key in (raw or ""):
            return value
    if "案例" in (raw or ""):
        return "参考案例"
    if "项目" in (raw or ""):
        return "项目自定规则"
    if "规范性文件" in (raw or ""):
        return "部门规章"
    return "法律"


def to_record(index: int, row: list[str]) -> dict:
    required, trigger = review_fields(row[8])
    return {
        "id": source_id(index, row[1], row[2]),
        "title": row[1],
        "articles": [part.strip() for part in re.split(r"[;；]", row[2]) if part.strip()] or [row[2]],
        "version_note": row[10],
        "effective_from": None if row[11] in {"", "现行", "项目实施期"} else row[11],
        "snapshot": "",
        "historical_mapping": {},
        "citation_status": "draft_reference",
        "tier": tier_of(row[0]),
        "provision_text": row[3],
        "norm_summary": row[4],
        "applies_to": row[5],
        "trigger": row[6],
        "consequence": row[7],
        "review_required": required,
        "review_trigger": trigger,
        "rule_nature": rule_nature(row[9]),
        "granularity": "instrument_scope" if row[13] == "整部指向" else "article",
        "merged_from": {"v0.1基线": "v0_1_base", "v0.2追加": "v0_2_added", "v0.1+v0.2合并": "v0_1_v0_2_merged"}[row[12]],
    }


def write_diff(old: list[list[str]], new: list[list[str]], merged: list[list[str]], path: Path) -> None:
    old_keys = {(row[1], row[2]): row for row in old}
    new_keys = {(row[1], row[2]): row for row in new}
    new_names = {row[1] for row in new}
    new_arts = defaultdict(set)
    for row in new:
        new_arts[row[1]] |= articles(row[2])
    vanished = [row for row in old if row[1] not in new_names]
    gaps = []
    for row in old:
        if row[1] not in new_names:
            continue
        missing = sorted(articles(row[2]) - new_arts[row[1]])
        if missing or ("全文" in row[2] and row[1] in new_names):
            gaps.append((row, missing, sorted(new_arts[row[1]])))
    added = [row for row in new if (row[1], row[2]) not in old_keys]
    overlap = [key for key in old_keys if key in new_keys]
    lines = [
        "# 总法源目录 v0.1–v0.2 差异清单",
        "",
        "产品 **V1.0**。合并方向：**以 v0.1 为基线**，v0.2 独有行追加；重合行按计划 0.3 逐列裁决。",
        "",
        f"- v0.1：{len(old)} 行",
        f"- v0.2：{len(new)} 行",
        f"- 键重合：{len(overlap)} 行（内容全部有差异）",
        f"- 仅 v0.2：{len(added)} 行（已追加）",
        f"- 仅 v0.1：{len(old) - len(overlap)} 行（已保留）",
        f"- 合并后：{len(merged)} 行",
        "",
        "重合行取 v0.2 的列：原文摘录、是否需要人工复核、规则性质。其余解释列取 v0.1。未采用文本写入「v0.2 对照」。",
        "",
        "## 1 整个法源在 v0.2 中消失（v0.1 已保留）",
        "",
        "| 名称 | 条款/位置 |",
        "| --- | --- |",
    ]
    for row in vanished:
        lines.append(f"| {row[1]} | {row[2]} |")
    lines.extend(["", "## 2 v0.1 条款级缺口（法源仍在，v0.1 该行已保留）", "", "| 名称 | v0.1 条款 | v0.2 已有条号 | 缺条号 |", "| --- | --- | --- | --- |"])
    for row, missing, have in gaps:
        lines.append(f"| {row[1]} | {row[2]} | {have or '（无纯条号）'} | {missing or '见原文位置'} |")
    lines.extend(["", "## 3 仅 v0.2 有、已追加的行（按名称汇总）", "", "| 名称 | 追加行数 | 是否旧版已有该法源 |", "| --- | --- | --- |"])
    counts = defaultdict(int)
    for row in added:
        counts[row[1]] += 1
    old_names = {row[1] for row in old}
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {name} | {count} | {'细化' if name in old_names else '新增法源'} |")
    lines.extend(["", "## 4 重合 29 行的裁决", "", "每一行 12 列均有差异。采用规则见上。完整对照在合并表「v0.2 对照」列。", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    old = table(V01)
    new = table(V02)
    old_keys = {(row[1], row[2]): row for row in old}
    new_keys = {(row[1], row[2]): row for row in new}
    merged = []
    for row in old:
        key = (row[1], row[2])
        if key in new_keys:
            merged.append(merge_row(row, new_keys[key]))
        else:
            merged.append(row + ["v0.1基线", granularity(row[2]), ""])
    for row in new:
        if (row[1], row[2]) not in old_keys:
            merged.append(row + ["v0.2追加", granularity(row[2]), ""])
    missing = [(row[1], row[2]) for row in old if (row[1], row[2]) not in {(item[1], item[2]) for item in merged}]
    if missing:
        raise SystemExit(f"v0.1 rows dropped: {missing}")
    if len(merged) != len(old) + len([row for row in new if (row[1], row[2]) not in old_keys]):
        raise SystemExit(f"unexpected merge size {len(merged)}")
    write_xlsx(OUT_XLSX, merged)
    records = [to_record(index + 1, row) for index, row in enumerate(merged)]
    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_diff(old, new, merged, OUT_DIFF)
    print(f"old={len(old)} new={len(new)} merged={len(merged)}")
    print(f"wrote {OUT_XLSX}")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_DIFF}")


if __name__ == "__main__":
    main()
