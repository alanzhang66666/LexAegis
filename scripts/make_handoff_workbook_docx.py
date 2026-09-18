"""Export docs/legal/法计交接 empty forms to a signable Word booklet."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "legal" / "法计交接"
OUT = SRC / "案隐盾_法计交接签署册.docx"
HELPER = Path(__file__).resolve().parent / "make_legal_evidence_docx.py"
DOC_ID = "LEX-LG-HANDOFF-BOOK-2026-09-14"

ORDER = [
    "00_先读.md",
    "法01_门1_来源核验与人工审查.md",
    "法02_门2_本次授权与真实材料授权.md",
    "法03_门3_本账号服务商证据包.md",
    "法04_门4_PIPIA.md",
    "法05_门5_规则发布法学签署.md",
    "法06_真实材料双人标注与仲裁.md",
    "法07_门6_冻结请求范围确认.md",
    "法08_门7_组合判断法学主签.md",
    "法09_门8_四类攻击法学认可.md",
    "法10_门9_当次隔离收据确认.md",
    "技01_门3_运行库与主槽配置.md",
    "技02_门5_运行规则包发布.md",
    "技03_门6_冻结请求与request_hash.md",
    "技04_门7_组合安全测试.md",
    "技05_门8_四类攻击实跑.md",
    "技06_门9_当次隔离与目标环境.md",
    "技07_交付包汇总.md",
    "技08_门10_approver批准.md",
    "配01_法学_处理与数据治理口径.md",
    "配02_法学_输出与演示验收.md",
    "配03_技术_运行能力核实.md",
    "配04_技术_工作树与发布验证.md",
    "配05_首次获准发送后结果.md",
]

spec = importlib.util.spec_from_file_location("cs_brief", HELPER)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
CODE = re.compile(r"`([^`]+)`")


def clean(text):
    text = LINK.sub(r"\1", text or "")
    text = BOLD.sub(r"\1", text)
    text = CODE.sub(r"\1", text)
    return text.replace("\\", "").strip()


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [clean(cell) for cell in line.split("|")]


def is_sep(cells):
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "") or "") for cell in cells)


def parse_blocks(text):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            fence = []
            lang = line.strip().lstrip("`").strip()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                fence.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            if lang == "mermaid":
                blocks.append(("note", "流程图见本夹 Markdown「双方交接流程」；纸质签署以各页表格为准。"))
            elif fence:
                blocks.append(("p", " ".join(clean(x) for x in fence if clean(x))))
            continue
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_row(lines[i])
                if not is_sep(cells):
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append(("table", rows))
            continue
        if line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            blocks.append(("h", min(hashes, 3), clean(line.lstrip("#").strip())))
            i += 1
            continue
        para = [clean(line)]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("|"):
            para.append(clean(lines[i]))
            i += 1
        blocks.append(("p", " ".join(part for part in para if part)))
    return blocks


def add_footer(section, label=None):
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    mark = label or DOC_ID
    run = p.add_run(f"{mark}  ·  空表  ·  填表≠pass≠可发送  ·  第 ")
    cs.set_run_font(run, name="微软雅黑", size=8, color=cs.MUTED)
    fld1 = cs.OxmlElement("w:fldChar")
    fld1.set(cs.qn("w:fldCharType"), "begin")
    instr = cs.OxmlElement("w:instrText")
    instr.set(cs.qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld2 = cs.OxmlElement("w:fldChar")
    fld2.set(cs.qn("w:fldCharType"), "end")
    run2 = p.add_run()
    run2._r.append(fld1)
    run2._r.append(instr)
    run2._r.append(fld2)
    cs.set_run_font(run2, name="微软雅黑", size=8, color=cs.MUTED)
    run3 = p.add_run(" 页")
    cs.set_run_font(run3, name="微软雅黑", size=8, color=cs.MUTED)


def col_widths(n):
    if n == 1:
        return [16.2]
    if n == 2:
        return [5.4, 10.8]
    if n == 3:
        return [4.4, 5.9, 5.9]
    if n == 4:
        return [3.2, 4.4, 4.3, 4.3]
    if n == 5:
        return [2.6, 3.4, 3.4, 3.4, 3.4]
    if n == 6:
        return [2.2, 2.8, 2.8, 2.8, 2.8, 2.8]
    return [round(16.2 / n, 2)] * n


def add_sign_lines(doc):
    cs.add_p(doc, "签署栏（纸质或扫描件入受控库；正文不进 git）", size=10, bold=True, first_line=False, space_after=6)
    cs.add_table(
        doc,
        ["角色", "姓名", "日期", "签字"],
        [
            ["法学主签 / 会签 / legal_reviewer", "", "", ""],
            ["技术实测 / 交付", "", "", ""],
            ["approver（换角色；门 1–9 齐后）", "", "", ""],
        ],
        col_cm=[5.6, 3.4, 3.2, 4.0],
    )


def new_doc(label):
    doc = cs.Document()
    section = doc.sections[0]
    cs.set_cell_margins(section)
    add_footer(section, label)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = cs.Pt(11)
    normal._element.rPr.rFonts.set(cs.qn("w:eastAsia"), "宋体")
    return doc


def render_file(doc, path, *, page_break, sign=True):
    if page_break:
        doc.add_page_break()
    blocks = parse_blocks(path.read_text(encoding="utf-8"))
    first_heading = True
    for block in blocks:
        kind = block[0]
        if kind == "h":
            level, title = block[1], block[2]
            if first_heading:
                cs.add_heading(doc, title, 1)
                first_heading = False
            else:
                cs.add_heading(doc, title, min(level, 3))
        elif kind == "note":
            cs.add_note(doc, block[1])
        elif kind == "p":
            text = block[1]
            if not text:
                continue
            if text.startswith("空表") or text.startswith("禁止预填") or text.startswith("硬约束"):
                cs.add_note(doc, text)
            else:
                cs.add_p(doc, text, first_line=False, space_after=6)
        elif kind == "table":
            rows = block[1]
            header, body = rows[0], rows[1:]
            if not body:
                body = [[""] * len(header)]
            unknown = set()
            if any("签署" in h or "姓名" in h or "签字" in h for h in header):
                unknown = set(range(len(header)))
            elif any("填写" in h or "结论" in h or "SHA-256" in h or "位置" in h for h in header):
                unknown = set(i for i, h in enumerate(header) if i > 0 or "填写" in h)
            cs.add_table(doc, header, body, col_cm=col_widths(len(header)), unknown_cols=unknown)
    if sign:
        add_sign_lines(doc)


def export_one(name):
    src = SRC / name
    dest = SRC / (src.stem + ".docx")
    doc = new_doc(src.stem)
    render_file(doc, src, page_break=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dest)
    return dest


def build_booklet():
    missing = [name for name in ORDER if not (SRC / name).exists()]
    if missing:
        raise FileNotFoundError("缺少交接页：" + "、".join(missing))
    doc = new_doc(DOC_ID)

    title = doc.add_paragraph()
    title.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = cs.Pt(12)
    title.paragraph_format.space_after = cs.Pt(4)
    r = title.add_run("案隐盾 · 法计交接签署册")
    cs.set_run_font(r, name="微软雅黑", size=20, bold=True, color=cs.FOREST)

    sub = doc.add_paragraph()
    sub.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = cs.Pt(14)
    r = sub.add_run("空表  ·  便于纸质签署与核对  ·  填表不是 pass，不是发送许可")
    cs.set_run_font(r, name="微软雅黑", size=11, color=cs.MUTED)

    cs.add_table(
        doc,
        ["项", "内容"],
        [
            ["材料编号", DOC_ID],
            ["适用三元组", "LA-001 × R_fact_summary × D_DeepSeek_official_API"],
            ["产品版本", "V1.0（1.0.0，非正式发行）"],
            ["人员", "法学：账号对接、取证、法学判断。技术：工程安全、运行证据；同一人换 approver 做最后批准。"],
            ["性质", "待办空表。不预填结论。签署正文入受控库；gate_status.json 只登文件名与 SHA-256。"],
            ["Markdown 底稿", "docs/legal/法计交接/"],
        ],
        col_cm=[3.6, 12.6],
    )
    cs.add_note(doc, "以下各页由 Markdown 空表导出。浅底格便于手写。门 7–9 必须对应门 6 哈希；门 10 须等门 1–9 齐备。")

    for index, name in enumerate(ORDER):
        render_file(doc, SRC / name, page_break=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


def build():
    pages = [export_one(name) for name in ORDER]
    booklet = build_booklet()
    return booklet, pages


if __name__ == "__main__":
    booklet, pages = build()
    print(booklet)
    for page in pages:
        print(page)
