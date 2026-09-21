# -*- coding: utf-8 -*-
"""Generate the illustrated V1.0 operation manual from existing workbench screenshots."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

ROOT = Path(r"E:\LexAegis")
SHOT = ROOT / "deliverables" / "系统截图" / "功能页面"
OUT_DIR = ROOT / "docs" / "操作说明"
PREP_DIR = OUT_DIR / "_prepared_images"
OUTPUT = OUT_DIR / "案隐盾法律隐私工作台_操作说明_V1.0.docx"
DOWNLOADS = Path(r"C:\Users\Alanz\Downloads") / "案隐盾法律隐私工作台_操作说明_V1.0.docx"

GREEN = "174C43"
INK = "20332F"
MUTED = "66706D"
GOLD = "A66800"
WHITE = "FFFFFF"
CALL_BG = "FFF4DD"
ROW_ALT = "F4F8F6"
HEADER_BG = "174C43"
FONT = "Arial Unicode MS"


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def set_east_asia(run, name: str = FONT) -> None:
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)
    rFonts.set(qn("w:eastAsia"), name)


def style_run(run, size=10.5, bold=False, color=INK, name=FONT) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = rgb(color)
    set_east_asia(run, name)


def shade_cell(cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def set_cell_margins(cell, top=60, bottom=60, left=80, right=80) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for key, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{key}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def set_table_borders(table, color="C5D2CD") -> None:
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblPr.append(borders)


def prevent_row_split(row) -> None:
    tr = row._tr
    trPr = tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    trPr.append(cant)


def add_page_field(paragraph, kind: str = "PAGE") -> None:
    run = paragraph.add_run()
    style_run(run, size=9, color=MUTED)
    r = run._r
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {kind} "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r.append(begin)
    r.append(instr)
    r.append(end)


def crop_png(src: Path, dest: Path, box) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    left, top, right, bottom = box
    right = min(right, w)
    bottom = min(bottom, h)
    im.crop((left, top, right, bottom)).save(dest, "PNG", optimize=True)


def prepare_images() -> dict[str, Path]:
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    mapping = {
        "login": SHOT / "00-公共功能页面" / "00-登录功能页.png",
        "workbench": SHOT / "00-公共功能页面" / "01-案件工作台功能页.png",
        "facts": SHOT / "01-完整披露流程" / "02-材料与事实功能页.png",
        "disclosure": SHOT / "01-完整披露流程" / "03-披露方案功能页.png",
        "edge_risk": SHOT / "03-组合线索风险" / "04-第一层次-边侧风险门禁功能页.png",
        "review_wait": SHOT / "02-人工复核否决" / "05-人工复核功能页.png",
        "review_reject_top": SHOT / "02-人工复核否决" / "06-第二层次-人工复核否决功能页.png",
        "review_reject_form": SHOT / "02-人工复核否决" / "06-第二层次-人工复核否决功能页.png",
        "dual_pass": SHOT / "01-完整披露流程" / "07-第三层次-模型与人工均允许功能页.png",
        "stop": SHOT / "04-主动停止" / "09-主动停止功能页.png",
        "summary": SHOT / "01-完整披露流程" / "08-摘要与来源回链功能页.png",
        "rules": SHOT / "00-公共功能页面" / "10-法学规则中心功能页.png",
        "evidence": SHOT / "00-公共功能页面" / "11-法学证据登记功能页.png",
        "vendor": SHOT / "00-公共功能页面" / "12-服务商治理功能页.png",
        "isolation": SHOT / "00-公共功能页面" / "13-隔离实验功能页.png",
        "runtime": SHOT / "00-公共功能页面" / "14-运行配置功能页.png",
        "users": SHOT / "00-公共功能页面" / "15-本地用户与角色功能页.png",
    }
    crops = {
        "facts": (0, 0, 1600, 1481),
        "edge_risk": (0, 0, 1600, 1680),
        "review_wait": (0, 0, 1600, 1680),
        "review_reject_top": (0, 0, 1600, 1480),
        "review_reject_form": (0, 3920, 1600, 5462),
        "dual_pass": (0, 0, 1600, 1480),
        "stop": (0, 0, 1600, 1680),
        "summary": (0, 0, 1600, 1750),
        "runtime": (0, 0, 1600, 1986),
    }
    prepared: dict[str, Path] = {}
    for key, src in mapping.items():
        dest = PREP_DIR / f"{key}.png"
        if key in crops:
            crop_png(src, dest, crops[key])
        else:
            Image.open(src).convert("RGB").save(dest, "PNG", optimize=True)
        prepared[key] = dest
    return prepared


class Manual:
    def __init__(self, images: dict[str, Path]) -> None:
        self.images = images
        self.doc = Document()
        self._setup_page()
        self._setup_styles()
        self._setup_header_footer()

    def _setup_page(self) -> None:
        section = self.doc.sections[0]
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(2.4)
        section.right_margin = Cm(2.4)
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.0)
        section.header_distance = Cm(1.0)
        section.footer_distance = Cm(1.0)

    def _setup_styles(self) -> None:
        styles = self.doc.styles
        normal = styles["Normal"]
        normal.font.name = FONT
        normal.font.size = Pt(10.5)
        normal.font.color.rgb = rgb(INK)
        normal.paragraph_format.space_after = Pt(6)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.line_spacing = 1.15
        rPr = normal.element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:eastAsia"), FONT)
        rFonts.set(qn("w:ascii"), FONT)
        rFonts.set(qn("w:hAnsi"), FONT)

    def _setup_header_footer(self) -> None:
        header = self.doc.sections[0].header
        header.is_linked_to_previous = False
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = hp.add_run("LexAegis  案隐盾法律隐私工作台  ·  操作说明 V1.0")
        style_run(run, size=8.5, color=MUTED)
        footer = self.doc.sections[0].footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        left = fp.add_run("截图取自演示工作台，使用合成材料  ·  第 ")
        style_run(left, size=8.5, color=MUTED)
        add_page_field(fp, "PAGE")
        mid = fp.add_run(" 页")
        style_run(mid, size=8.5, color=MUTED)

    def add_text(
        self,
        text: str,
        *,
        size=10.5,
        bold=False,
        color=INK,
        align=WD_ALIGN_PARAGRAPH.LEFT,
        space_before=0,
        space_after=6,
        first_line=0,
    ):
        p = self.doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.15
        if first_line:
            p.paragraph_format.first_line_indent = Cm(first_line)
        run = p.add_run(text)
        style_run(run, size=size, bold=bold, color=color)
        return p

    def h1(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(10)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        style_run(run, size=18, bold=True, color=GREEN)

    def h2(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        style_run(run, size=13.5, bold=True, color=GREEN)

    def h3(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        style_run(run, size=12, bold=True, color=INK)

    def body(self, text: str) -> None:
        self.add_text(text, size=10.5, first_line=0.74, space_after=6)

    def plain(self, text: str, space_after=6) -> None:
        self.add_text(text, size=10.5, space_after=space_after)

    def bullet(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.75)
        p.paragraph_format.first_line_indent = Cm(-0.37)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run("•  " + text)
        style_run(run, size=10.5)

    def step_flow(self, title: str, detail: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(title)
        style_run(run, size=10.5, bold=True, color=GREEN)
        self.plain(detail, space_after=8)

    def numbered(self, items: list[str]) -> None:
        for i, item in enumerate(items, 1):
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.4)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.space_before = Pt(0)
            run = p.add_run(f"{i}.  {item}")
            style_run(run, size=10.5)

    def callout(self, title: str, body: str) -> None:
        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.cell(0, 0)
        shade_cell(cell, CALL_BG)
        set_cell_margins(cell, 80, 80, 120, 120)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r1 = p.add_run(title)
        style_run(r1, size=10, bold=True, color=GOLD)
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_after = Pt(0)
        r2 = p2.add_run(body)
        style_run(r2, size=9.5, color=GOLD)
        set_table_borders(table, "E6D3A3")
        self.doc.add_paragraph().paragraph_format.space_after = Pt(8)

    def add_table(self, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None) -> None:
        table = self.doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        set_table_borders(table)
        for i, head in enumerate(headers):
            cell = table.rows[0].cells[i]
            shade_cell(cell, HEADER_BG)
            set_cell_margins(cell, 50, 50, 70, 70)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(head)
            style_run(run, size=9.5, bold=True, color=WHITE)
        for r_i, row in enumerate(rows):
            for c_i, value in enumerate(row):
                cell = table.rows[r_i + 1].cells[c_i]
                if r_i % 2 == 1:
                    shade_cell(cell, ROW_ALT)
                set_cell_margins(cell, 50, 50, 70, 70)
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(value)
                style_run(run, size=9)
            prevent_row_split(table.rows[r_i + 1])
        prevent_row_split(table.rows[0])
        if col_widths:
            for row in table.rows:
                for i, width in enumerate(col_widths):
                    row.cells[i].width = Cm(width)
        spacer = self.doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(8)

    def add_images(self, keys: list[str], caption: str, max_height=16.2) -> None:
        for key in keys:
            path = self.images[key]
            im = Image.open(path)
            w, h = im.size
            max_w = 15.5
            width = max_w
            height = width * h / w
            if height > max_height:
                height = max_height
                width = height * w / h
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_together = True
            run = p.add_run()
            run.add_picture(str(path), width=Cm(width), height=Cm(height))
        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_before = Pt(2)
        cap.paragraph_format.space_after = Pt(8)
        run = cap.add_run(caption)
        style_run(run, size=10, bold=True, color=GREEN)

    def page_break(self) -> None:
        self.doc.add_page_break()

    def build(self) -> None:
        self._cover()
        self._part1()
        self._part2()
        self.page_break()
        self._part3()
        self.page_break()
        self._part4()
        self._appendix()

    def _cover(self) -> None:
        for _ in range(3):
            p = self.doc.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
        self.add_text("LexAegis", size=18, bold=True, color=GREEN, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
        self.add_text("案隐盾法律隐私工作台", size=26, bold=True, color=INK, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
        self.add_text("操作说明", size=20, bold=True, color=GREEN, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=14)
        self.add_text(
            "材料与事实  ·  披露方案  ·  风险与审批  ·  摘要与回链",
            size=11,
            color=MUTED,
            align=WD_ALIGN_PARAGRAPH.CENTER,
            space_after=18,
        )
        self.add_table(
            ["项目", "内容"],
            [
                ["产品版本", "1.0"],
                ["文档性质", "系统操作说明"],
                ["发布日期", "2026 年 9 月"],
                ["配图来源", "演示工作台功能页面截图，后台为合成示例材料"],
            ],
            col_widths=[4.5, 11.5],
        )
        self.callout(
            "阅读提示",
            "本说明按系统通用功能编写，不以特定真实案件或预设处理结论为前提。文中截图用于标明页面位置与操作顺序；演示工作台使用完全合成材料，页面出现“已完成”“可进入人工复核”或本地预置结果，均不表示生产环境正式外发已经开通。",
        )
        self.plain(
            "本说明面向案隐盾法律隐私工作台的实际使用人员，介绍从案件建立、材料导入、事实核对、逐项披露、风险检查、人工复核、审批执行到结果回链的完整操作方法。"
        )

    def _part1(self) -> None:
        self.h1("一、核心模块")
        self.body(
            "系统以案件工作台为主入口，并把一次处理拆成四个功能边界：材料与事实、披露方案、风险与审批、摘要与回链。法学规则、法学证据、服务商档案、隔离实验、运行配置和本地用户为案件流程提供规则、证据、服务条件和权限，不替代当前请求的具名复核与批准。"
        )
        self.add_table(
            ["模块", "主要用途", "形成结果"],
            [
                ["案件工作台", "管理案件、材料、事实、披露任务、风险检查和结果", "可继续处理的案件工作空间"],
                ["材料与事实", "上传、解析、分段、抽取、人工校对和来源定位", "带原文锚点的事实清单"],
                ["披露方案", "逐项判断必要性、选择处理动作并说明信息损失和残余风险", "可解释的最小披露内容"],
                ["风险与审批", "冻结完整请求，检查系统门禁，完成具名复核与批准", "允许继续或明确阻断的当前请求"],
                ["摘要与回链", "查看任务结果、引用关系、缺口和未使用事实，并回到原文", "经人工核对的结果与审计关联"],
                ["法学与治理", "维护规则、法学证据、服务商档案、隔离实验和运行配置", "供请求检查使用的治理依据"],
                ["本地用户", "维护账号、角色和启停状态", "具名权限与操作主体"],
            ],
            col_widths=[3.4, 7.4, 5.2],
        )
        self.h3("四个功能边界")
        self.add_table(
            ["序号", "功能边界", "主要操作", "进入下一阶段前的完成标志"],
            [
                ["01", "材料与事实", "导入材料、检查解析、核对事实、查看来源", "事实可回到对应原文位置"],
                ["02", "披露方案", "逐项选择必要性、精度和处理动作", "披露文本及理由可解释"],
                ["03", "风险与审批", "冻结请求、查看门禁、复核、审批、执行", "满足当前任务的复核与批准条件"],
                ["04", "摘要与回链", "识别结果来源、逐句对照、确认或退回", "结果可回链且人工确认完成"],
            ],
            col_widths=[1.6, 3.0, 6.0, 5.4],
        )
        self.h3("适用人员")
        self.add_table(
            ["角色", "主要职责", "本说明重点"],
            [
                ["案件操作人员", "建立案件、导入材料、核对事实、形成披露方案、执行获准任务", "标准流程第 1—8、10 步；功能说明中的工作台与四个边界"],
                ["法学复核人员", "复核事实、规则依据、披露必要性、残余风险及结果表达", "风险与审批、摘要与回链、法学规则与证据"],
                ["审批人员", "阅读完整请求快照，批准或拒绝当前版本", "风险与审批中的独立批准"],
                ["管理员与运维人员", "维护账号、规则、法学证据、服务商和运行配置", "法学与治理、系统设置"],
            ],
            col_widths=[3.4, 7.2, 5.4],
        )
        self.callout(
            "请先确认职责",
            "同一人员可以在授权范围内承担多个系统角色，但操作记录仍应使用具名账号。批准当前请求与执行任务是两个独立动作。",
        )
        self.h3("使用原则")
        for item in [
            "原始材料、身份映射和内部复核信息默认保留在本地工作区；只有经过逐项确认的披露内容进入请求。",
            "事实、披露方案、风险检查、批准和执行均绑定当前材料与配置版本；关键输入变化后应新建任务并重新检查。",
            "未运行、未完成、不确定、待复核和不可用均不等同于通过。",
            "系统输出用于材料整理、隐私控制和审查辅助，不替代律师判断、组织授权或正式审批责任。",
        ]:
            self.bullet(item)

    def _part2(self) -> None:
        self.h1("二、标准使用流程")
        self.body("以下流程适用于需要把案件材料整理为可控披露请求，并对结果进行来源核对的日常工作。")
        flows = [
            (
                "第一步，登录并确认账号角色。",
                "使用管理员分配的本地账号登录。查看页面右上角的账号与角色，确认当前角色具备本次操作权限。",
            ),
            (
                "第二步，建立案件工作空间。",
                "在“案件工作台”选择“新建案件”，填写便于内部识别的案件名称，并按业务要求设置案件信息。每个案件的材料、事实、身份映射和任务记录相互独立。",
            ),
            (
                "第三步，导入材料并检查解析。",
                "上传支持的文件，等待解析完成；检查材料版本、页段数量、识别提示和异常。解析完成只代表材料可读取，不代表事实已经核验。",
            ),
            (
                "第四步，核对事实与来源。",
                "运行边侧提取或人工添加事实。逐项核对主体、关系、事件、日期、金额和证据，使用“查看原文依据”确认上下文。",
            ),
            (
                "第五步，形成披露方案。",
                "选择“生成披露方案”。按任务目的为每项事实选择必要性和处理动作，检查披露文本、保留理由、信息损失及残余风险。",
            ),
            (
                "第六步，冻结请求并检查风险。",
                "选择“检验风险并冻结请求”。展开完整请求，核对目标、模型、规则版本、材料版本、配置版本和实际披露正文。",
            ),
            (
                "第七步，完成具名人工复核。",
                "由法学复核人员阅读事实依据、披露必要性、残余风险和系统提示，提交允许、否决或暂停意见。否决仅针对当前请求。",
            ),
            (
                "第八步，批准并执行当前版本。",
                "由审批人员批准当前完整请求。审批完成后，由案件操作人员执行任务。审批事件不等同于请求已经离开本地。",
            ),
            (
                "第九步，核对结果并回链。",
                "在“摘要与回链”中确认结果来源，对照使用事实、未使用事实、缺口和来源标识；必要时返回前一阶段修改并新建任务。",
            ),
            (
                "第十步，确认、导出与归档。",
                "完成逐句复核后确认结果，并按权限导出云端视图、内部复核包或审计记录。含身份与锚点的内部复核包应按系统提示再次具名确认。",
            ),
        ]
        for title, detail in flows:
            self.step_flow(title, detail)
        self.plain("其他基础功能：左侧导航可进入法学规则中心、法学证据登记、服务商治理、隔离实验、运行配置和本地用户。点击右上角账号可确认当前角色；角色变更对后续请求生效。")

    def _part3(self) -> None:
        self.h1("三、功能使用说明")
        self.body(
            "本章按页面组织。每一节先给出界面截图和图注，再按编号说明如何进入、看什么、点哪里。截图中的案件名称、事实内容和处理结论均为合成示例。"
        )

        self.h2("登录")
        self.add_images(["login"], "图3-1 登录")
        self.numbered(
            [
                "在受控浏览器中打开部署方提供的工作台地址。建议使用较新的 Chromium 内核浏览器，并保持页面缩放为 100%。",
                "登录页展示产品名称“案隐盾 LexAegis”和提示“让案件信息，留在合适的边界。”页面标明这是本地工作空间：输入启动终端显示的本地访问口令后，进入云边协同工作台。",
                "在“用户名”中填写管理员分配的本地账号，在“本地访问口令”中填写对应口令，点击“进入工作台”。不要在说明文档、截图或聊天记录中保存账号口令。",
                "页面底部提示“原始材料在边侧处理，云端请求经人工审批”。账号认证在本地完成，页面不展示模型服务密钥。",
                "登录后查看右上角账号名称和角色。若页面提示会话失效，重新登录后再继续；浏览器刷新不会改变已保存的案件记录。",
            ]
        )

        self.h2("案件工作台")
        self.add_images(["workbench"], "图3-2 案件工作台")
        self.numbered(
            [
                "登录成功后进入“案件工作台”。左侧导航用于切换案件工作台、法学规则中心、法学证据登记、服务商治理、隔离实验、运行配置和本地用户。",
                "主区域顶部显示工作台标题和“新建案件”。空白工作台会提示“从第一份案件材料开始”，并提供“导入 Word 材料”入口。",
                "点击右上角“新建案件”，填写清晰、便于内部识别的案件名称后进入案件详情。名称用于工作台检索和审计识别，不应代替正式案号或材料版本。",
                "页面中部的“全部案件”列出已建立案件。选择案件后，主区域显示四个功能边界；左侧或侧栏显示材料与原文，右侧上下文区域显示任务、审计和发送尝试。",
                "页面底部固定展示四个功能边界卡片：01 材料与事实、02 披露方案、03 风险与审批、04 摘要与回链。这四个卡片对应一次完整处理的阶段，而不是四个互不相关的子系统。",
                "若同一案件存在多个任务，应以任务编号、材料版本和请求版本区分，不要仅凭列表顺序判断先后。",
            ]
        )
        self.callout(
            "版本绑定规则",
            "材料、事实、披露正文、目标服务、模型、规则或运行配置发生变化时，历史请求可以保留用于追溯，但不应继续作为当前批准和执行依据。",
        )

        self.h2("功能中心")
        self.h3("（一）材料与事实")
        self.add_images(["facts"], "图3-3 材料与事实")
        self.numbered(
            [
                "进入目标案件后，打开顶部阶段页签“01 材料与事实”。页面分为三栏：左侧“原始材料”，中部“事实与证据”，右侧“依据与运行边界”。",
                "在左侧选择“导入 Word 材料”，按页面提示选择 DOCX、PDF、TXT、XLSX、CSV、图片或音视频。实际可用格式以当前构建提示为准。上传后系统建立材料版本；不要通过覆盖同名文件来替代版本管理。",
                "查看解析状态、页段数量、OCR 或转写提示。上传成功、解析完成、事实抽取完成是三个不同状态。截图中的“已解析”只说明材料可读取。",
                "可使用边侧提取整理材料，也可选择“添加事实”人工录入。中部事实卡按主体、关系、事件、日期、金额、证据分列，并显示确认状态。",
                "点击事实卡片中的“查看原文依据”，在材料侧栏定位对应段落、页码、单元格或时间码，确认事实未脱离上下文。材料表述不准确时选择“编辑”；与任务无关且不应保留的人工事实可删除。",
                "右侧“依据与运行边界”标明原文始终留在边侧，身份映射、内部理由和评分真值不会自动进入云端请求。底部可运行“本地生成时间线”“本地整理证据清单”“本地生成争点候选”，或点击“生成披露方案”进入下一阶段。",
            ]
        )
        self.add_table(
            ["材料类型", "系统处理", "人工核对重点"],
            [
                ["DOCX / PDF / TXT", "解析、分段、来源定位", "页码、表格、脚注、漏段及阅读顺序"],
                ["XLSX / CSV", "按记录或单元格定位", "列含义、公式结果、空值和版本"],
                ["PNG / JPEG", "按配置执行本地 OCR", "页序、遮挡、识别错误和低置信内容"],
                ["音频 / 视频", "本地转写后形成文本", "说话人、时间码、漏转和误转"],
                ["人工事实", "录入事实并关联来源", "主张与认定、主体、日期、金额和证据归属"],
            ],
            col_widths=[3.6, 5.2, 7.2],
        )
        self.add_table(
            ["工具", "用途", "使用边界"],
            [
                ["本地生成时间线", "按日期整理事件顺序", "仅重排已确认事实，不补造未知日期"],
                ["本地整理证据清单", "按证据类别和归属整理清单", "不判断证据能力或证明力"],
                ["本地生成争点候选", "按事实字段形成争点线索", "属于候选整理，不构成法律结论"],
            ],
            col_widths=[3.6, 5.2, 7.2],
        )
        self.callout(
            "完成标志",
            "事实清单中的关键内容均已核对，并且每项事实能够回到有效原文位置；无法确认的信息保持待确认或未知。",
        )

        self.h3("（二）披露方案")
        self.add_images(["disclosure"], "图3-4 披露方案")
        self.numbered(
            [
                "在材料与事实核对完成后，点击“生成披露方案”，进入顶部页签“02 披露方案”。原文和身份映射继续保留在本地。",
                "先确认本次任务的目的和子目的，避免为了通用摘要而过度披露。页面提示仅下方披露内容会进入请求，原文和身份映射保留在边侧。",
                "系统按事实显示必要性、候选处理动作、披露文本、保留理由、信息损失、残余风险和来源入口。截图中可见“条件必要”、稳定代号如 [[LEX-P0001]]、以及“查看依据”。",
                "阅读系统给出的规则说明和未知条件，选择与当前任务相符的必要性；在已校验候选中选择保持精度、代号替换、适度模糊化或删除。没有已校验候选时，不自行构造绕过规则的文本。",
                "确认披露文本只包含获选内容，没有原文、身份映射、未选事实或可反向定位的组合。必要时使用“编辑披露文本”调整表述，并通过“查看依据”回到对应事实和材料。",
                "披露方案生成只完成最小化准备，仍须经过风险检验、人工复核和独立审批，不能把本页理解为已经允许外发。",
            ]
        )
        self.add_table(
            ["项目", "选项", "操作含义"],
            [
                ["必要性", "必须 / 条件必要 / 不必要 / 不确定", "判断该事实是否为当前任务所需；不确定时进入复核，不按通过处理"],
                ["保持精度", "保留业务判断所需精度", "直接身份仍应使用稳定代号一致替换"],
                ["用代号替换", "以稳定代称替换直接身份", "保留同一主体之间的关系，不等于匿名化"],
                ["适度模糊化", "降低日期、地点、金额等精度", "保留任务需要的区间或类别"],
                ["删除", "不进入请求", "适用于与任务无关或处理条件不满足的事实"],
            ],
            col_widths=[3.0, 5.4, 7.6],
        )
        self.callout(
            "隐私提示",
            "代号替换用于隐藏直接身份并保持同一主体的稳定关联，但不能自动消除地点、时间、金额、职业、案号等组合线索形成的再识别风险。",
        )

        self.h3("（三）风险与审批")
        self.plain(
            "本阶段把目标、模型、规则、材料版本、配置版本和实际披露正文冻结为同一请求对象，并完成系统检查、人工复核、审批和执行。下面按四类常见页面状态分别说明。"
        )

        self.add_text("1. 边侧风险门禁", size=11, bold=True, color=INK, space_before=6, space_after=4)
        self.add_images(["edge_risk"], "图3-5 边侧风险门禁")
        self.numbered(
            [
                "在披露方案底部选择“检验风险并冻结请求”后，系统进入“03 风险与审批”，并生成完整请求快照。",
                "页面顶部的当前操作状态、系统初检结果和阻断原因是首先要阅读的内容。截图示例中，边侧模型识别到“唯一岗位或公开事件仍残留”，当前请求不可继续。",
                "展开“完整请求快照”，逐项核对目标地址、模型、任务、规则版本、材料版本、配置版本、提示内容和实际披露正文。",
                "删除直接标识不等于匿名化。组合线索风险未消除前，不能进入审批或外发流程。如需继续处理，应调整材料或披露后创建关联后继任务，不要把旧审批套用于新内容。",
            ]
        )

        self.add_text("2. 人工复核", size=11, bold=True, color=INK, space_before=8, space_after=4)
        self.add_images(["review_wait"], "图3-6 人工复核")
        self.numbered(
            [
                "当系统未直接阻断但需要具名判断时，当前操作状态显示“待人工复核，本次请求暂不可继续”。模型初检允许进入复核，不等于授予发送权。",
                "由具有 legal_reviewer 权限的具名账号进入同一案件和当前任务。阅读事实来源、披露必要性、规则依据、系统阻断项、残余关联风险和实际请求正文。",
                "页面会展示完整请求快照、四类攻击运行状态以及“依据与运行边界”。四类攻击或网络隔离显示“待开发”“未完成”时，应保持未完成，不应把配置展示解释为当前请求已经通过。",
                "在人工复核表单中填写允许、否决或暂停的理由，并引用相应事实或证据。技术状态不能替代法学判断。提交后，结论只作用于当前请求。",
            ]
        )

        self.add_text("3. 人工复核否决", size=11, bold=True, color=INK, space_before=8, space_after=4)
        self.add_images(["review_reject_top", "review_reject_form"], "图3-7 人工复核否决")
        self.numbered(
            [
                "法学复核人员选择“否决本次请求”并提交后，页面顶部记录“已记录法律复核结论：否决会阻断本次请求，允许结论仍不授予发送权。”",
                "当前操作状态变为“人工复核已否决，本次请求不可继续”。后续审批与执行入口关闭。",
                "复核表单需填写解决依据、事实前提、权限判断、外部处理条件、最小化措施、最终依据和适用边界，并勾选已阅读风险提示。",
                "否决针对当前冻结请求。如需继续处理，必须调整材料后创建并重新检验新的请求；历史初检记录继续保留。",
            ]
        )

        self.add_text("4. 双重门禁通过，等待独立审批", size=11, bold=True, color=INK, space_before=8, space_after=4)
        self.add_images(["dual_pass"], "图3-8 双重门禁通过")
        self.numbered(
            [
                "当模型初检未直接阻断、人工复核允许继续当前演示流程时，页面显示人工复核已完成，当前操作状态进入待审批。",
                "截图中的“法律层面未形成禁止”只说明本次法律层面检查未形成禁止结论，不自动代表全部门禁通过。四类攻击运行若仍为“待开发”，完整风险检验应保持未完成。",
                "由 approver 账号核对接收方、处理目的、模型、规则版本、材料版本和披露正文，批准或拒绝当前完整请求。审批人员不能替代案件操作人员执行发送。",
                "批准后由 case_operator 或管理员进入任务，根据任务类型选择“执行任务”“生成本地摘要草稿”或“发送至已批准云端”。按钮文案反映当前任务的实际执行方式。演示环境可能以本地预置结果模拟后续处理，不表示生产环境正式外发已开通。",
            ]
        )

        self.add_text("5. 主动停止", size=11, bold=True, color=INK, space_before=8, space_after=4)
        self.add_images(["stop"], "图3-9 主动停止")
        self.numbered(
            [
                "材料不足或处理条件不满足时，案件操作人员可在风险与审批页选择“停止任务”。",
                "当前操作状态变为“任务已主动停止，本次请求不可继续”。系统保留请求哈希、风险结果和操作记录。",
                "停止后的原请求不可继续执行。如需恢复处理，应补齐材料并新建任务重新检验。",
            ]
        )

        self.add_table(
            ["页面状态", "含义", "应采取的操作"],
            [
                ["待人工复核", "系统未直接阻断，但需要具名人员判断", "由法学复核人员检查并提交结论"],
                ["已暂停 / 已阻断", "当前请求不能继续", "阅读原因；修改材料或披露后创建关联后继任务"],
                ["人工复核已否决", "法学复核人员不允许当前请求继续", "保留意见；调整内容后新建任务"],
                ["已批准", "审批人员批准当前冻结版本", "由案件操作人员执行；批准不等于已发送"],
                ["排队 / 执行中", "任务已进入执行链路", "等待状态更新，不重复执行"],
                ["完成", "执行任务已结束并产生结果", "进入摘要与回链完成人工确认"],
                ["状态不明 / 失败", "执行结果无法确定或任务失败", "先查事件和账本，不盲目重发"],
                ["依据已变化", "材料、规则或配置与任务快照不一致", "新建任务并重新完成检查与审批"],
            ],
            col_widths=[3.4, 6.0, 6.6],
        )
        self.callout(
            "未完成即保持关闭",
            "风险攻击或网络隔离在当前部署中未运行、未配置、不可用或仍待建设时，应保持未完成状态，不应把配置展示或历史记录解释为当前请求已经通过。正式外部处理除当前请求的人工复核与批准外，还可能要求有效规则、法学证据、服务商档案、风险检查、隔离验证和一次性许可。",
        )

        self.h3("（四）摘要与回链")
        self.add_images(["summary"], "图3-10 摘要与来源回链")
        self.numbered(
            [
                "任务完成后选择“查看摘要与回链”，或直接打开“04 摘要与回链”。",
                "确认页面标注的是本地确定性结果、外部服务回写结果或其他运行来源。不同来源的结果不得混写。演示截图中可见“本地预置结果”和“云边回写 / 外发事实项已被引用”等来源标记。",
                "逐条查看云端陈述、边侧复原、实际外发支持事实、原文锚点和材料段落。结果缺少来源时，不应直接确认。",
                "点击“回到原文”，定位原文段落、页码、单元格或时间码，核对主体、时间、金额、立场和程序结果。",
                "验收时应确保主体没有互换，稳定代称没有在不同主体之间复用；当事人主张、对方否认、法院认定和程序结果保持原有层级；未知信息继续保持未知。",
                "默认导出面向披露结果的云端视图。包含真实身份、映射和原文锚点的内部复核包仅用于受控本地复核，并应按系统提示完成逐项确认和具名二次确认。",
            ]
        )
        self.add_table(
            ["检查项", "通过标准", "不通过时"],
            [
                ["事实一致性", "主体、关系、事件、日期、金额与来源一致", "返回事实卡修订并新建任务"],
                ["表达层级", "主张、否认、认定和程序结果区分明确", "修改披露或结果，不合并表述"],
                ["来源完整性", "每条关键陈述可回到事实和原文", "保留缺口，不确认最终结果"],
                ["披露边界", "结果未带回未批准的原文或身份信息", "停止确认并复核请求与执行记录"],
            ],
            col_widths=[3.2, 6.4, 6.4],
        )

        self.h2("法学与治理")
        self.plain("这些模块为案件流程提供规则、证据、服务条件、环境能力和账号权限。入口是否可见取决于当前角色。")

        self.h3("（一）法学规则中心")
        self.add_images(["rules"], "图3-11 法学规则中心")
        self.numbered(
            [
                "在左侧导航选择“法学规则中心”。页面展示当前案件使用的字段处理规则、人工复核条件与攻击协议。",
                "上方“任务能力”列出事实摘要、时间线、证据整理、争点提取等任务及其版本状态。规则命中只形成提示或门禁结果，不能代替具名人工复核与审批。",
                "下方“案由知识包”显示适用案件类型、字段矩阵覆盖率和规则配置状态。准备、法学复核和发布是独立操作；规则发布仅使规则进入后续门禁，不批准任何具体请求。",
                "规则未达到当前任务要求时，正式请求保持关闭。",
            ]
        )

        self.h3("（二）法学证据登记")
        self.add_images(["evidence"], "图3-12 法学证据登记")
        self.numbered(
            [
                "在左侧导航选择“法学证据登记”，为正式案件保存受控法学表格、签署材料或其他依据。",
                "上传只登记文件和哈希，不自动表示已经核验、已经发布或允许外部处理。复核人员可将记录标记为待补正或证据已核齐，并保留意见。",
                "若页面显示“暂无正式案件”，应先在案件工作台建立正式案件，再登记法学表格。演示截图只展示登记能力，不将合成材料表述为真实验收证据。",
            ]
        )

        self.h3("（三）服务商治理")
        self.add_images(["vendor"], "图3-13 服务商治理")
        self.numbered(
            [
                "在左侧导航选择“服务商治理”，登记外部服务的合同主体、处理地区、留存期限、删除机制、训练用途、人工访问、分包和允许任务。",
                "点击“新建档案”创建服务商记录，或打开已有档案查看与编辑。档案关键字段变化后应重新复核。",
                "页面中的“已配置”只表示档案字段存在。服务商档案可用不等于具体案件获得授权，也不自动授予外发权限。",
            ]
        )

        self.h3("（四）隔离实验")
        self.add_images(["isolation"], "图3-14 隔离实验")
        self.numbered(
            [
                "在左侧导航选择“隔离实验”。该模块用于在受控环境中组织身份恢复、候选集合缩小、敏感事实推断和跨轮关联等检查。",
                "实验必须绑定当前请求、环境和输入；历史结果不能自动替代本次检查。",
                "截图所示部署中，网络隔离、独立风险攻击与研究工具标记为“待开发”。尚未完成的能力应按页面状态如实对待，不以普通规则检验冒充独立隔离实验。",
            ]
        )

        self.h2("系统设置")
        self.h3("（一）运行配置")
        self.add_images(["runtime"], "图3-15 运行配置")
        self.numbered(
            [
                "管理员进入左侧“运行配置”，查看边侧小模型、云端网关、本地 OCR、本机转写、风险攻击、网络隔离等能力状态。",
                "“已开发”表示该能力在当前构建中存在；“待开发”必须保持未完成，不能把状态卡片当作本次请求的通过证明。",
                "在下方核对边侧处理服务地址、云端主备模型、服务商档案、处理预算等参数。界面中的 API 密钥应为掩码；云端密钥只应配置在外发网关或受控环境变量中。",
                "修改后点击“保存运行配置”。配置变化会使引用旧配置的任务失效，需要重新创建任务。",
            ]
        )

        self.h3("（二）本地用户与角色")
        self.add_images(["users"], "图3-16 本地用户与角色")
        self.numbered(
            [
                "管理员进入“本地用户”，查看人员、用户名、角色和启停状态。系统保护最后一个管理员账号，避免失去管理入口。",
                "可创建账号、调整角色并启用或停用用户。角色变更和停用对后续请求生效；已有审计记录继续保留原操作主体。",
                "案件操作、法学复核、独立审批和执行发送应使用对应角色完成，避免由同一普通角色越权走完整条链路。",
            ]
        )
        self.add_table(
            ["角色", "典型权限"],
            [
                ["admin", "管理账号、运行配置和治理模块；可执行受控管理操作"],
                ["case_operator", "建立案件、上传材料、整理事实、建立任务和执行获准任务"],
                ["technical_reviewer", "维护技术检查、风险与隔离相关记录"],
                ["legal_reviewer", "复核规则、法学证据、披露必要性和结果表达"],
                ["approver", "阅读完整请求并批准或拒绝当前版本"],
            ],
            col_widths=[4.2, 11.8],
        )

    def _part4(self) -> None:
        self.h1("四、输出、留痕与异常处理")
        self.body("系统按阶段产生中间产物，并以事件记录重建一次完整处理过程。")
        self.h3("主要输入与输出")
        self.add_table(
            ["阶段", "主要输入", "主要输出"],
            [
                ["材料解析", "文档、表格、图片、音视频", "材料版本、段落、锚点、解析状态"],
                ["事实整理", "解析内容和人工补充", "事实卡、确认状态、来源列表"],
                ["披露控制", "事实、任务目的和规则", "必要性、处理动作、披露文本、残余风险"],
                ["请求冻结", "披露内容、目标和配置", "完整请求快照与请求哈希"],
                ["风险审批", "请求快照与治理状态", "阻断原因、复核记录、批准记录"],
                ["执行与回链", "获准请求及执行结果", "结果、引用关系、缺口、未使用事实"],
                ["审计导出", "案件事件", "事件编号、时间、主体、类型和元数据"],
            ],
            col_widths=[3.2, 6.4, 6.4],
        )
        self.h3("审计事件")
        self.add_table(
            ["字段", "含义", "核对要点"],
            [
                ["事件编号", "事件的唯一标识", "不能用列表顺序代替"],
                ["发生时间", "带时区的具体时间", "用于判断先后关系和有效期"],
                ["操作主体", "执行操作的用户或系统", "区分系统动作与具名业务角色"],
                ["事件类型", "发生了什么操作", "事件名称不等于业务结论"],
                ["元数据", "材料、任务、请求和版本上下文", "缺少关联字段时不得自行补齐"],
            ],
            col_widths=[3.2, 6.4, 6.4],
        )
        self.h3("常见异常及处理")
        self.add_table(
            ["现象", "处理建议", "应保留内容"],
            [
                ["上传成功但解析失败", "检查格式、截断、图片文字层和文件大小；修复后重试", "材料版本、错误信息、原始文件"],
                ["解析完成但事实抽取失败", "不要把解析完成当作事实完成；修复响应或格式后新建任务", "解析结果、抽取错误、任务编号"],
                ["事实来源显示已更新", "重新核对事实与新材料版本，生成新的披露任务", "旧事实、旧任务和变化记录"],
                ["风险检查未运行或不确定", "对当前请求重新执行检查；未运行不按通过", "协议、环境、输入和检查结果"],
                ["规则或服务商条件不完整", "由相应责任人补齐档案、复核或发布记录", "规则版本、档案版本和复核记录"],
                ["人工复核不通过", "按意见减少披露、降低精度或补充依据后新建后继任务", "复核人、意见、请求版本和时间"],
                ["执行超时或状态不明", "先查事件和网关账本，不盲目重发或切换目标", "请求标识、时间、状态及后续核验"],
                ["输出缺少来源或存在冲突", "返回事实与材料阶段复核，不确认结果", "冲突项、来源、人工处置"],
            ],
            col_widths=[4.0, 7.0, 5.0],
        )
        self.callout(
            "正式使用建议",
            "以当前部署说明、有效规则、已核验服务商档案和组织制度为准。遇到状态冲突时，以当前请求快照、具名复核记录和审计事件为依据。",
        )
        self.h3("适用范围")
        for item in [
            "法律文书、合同、证据清单和案件材料的本地整理与来源定位。",
            "围绕明确任务目的形成逐项披露方案并完成具名人工复核。",
            "在调用外部服务前检查规则、服务商、风险、隔离和审批状态。",
            "对本地结果或外部回写结果进行来源区分、逐句回链和人工确认。",
            "通过事件日志重建材料、事实、披露、风险、批准和执行过程。",
        ]:
            self.bullet(item)
        self.h3("使用限制")
        for item in [
            "系统不是自动法律裁判工具，输出不能替代律师意见、组织授权或审批责任。",
            "代号替换和适度模糊化可以降低直接识别风险，但不自动等于匿名化或零风险。",
            "页面状态反映当前材料、规则、配置和任务；关键输入变化会使历史任务失效。",
            "批准、执行完成和结果确认是不同事件，应分别核对。",
            "界面功能存在、服务已配置或单次任务成功，均不能直接推出长期可用率、准确率或风险为零。",
        ]:
            self.bullet(item)

    def _appendix(self) -> None:
        self.h1("附录 A  术语说明")
        self.add_table(
            ["术语", "说明"],
            [
                ["边侧", "保存原始材料、身份映射和内部复核信息的本地环境"],
                ["事实卡", "从材料中整理出的可独立核对命题，带有类型、确认状态和来源锚点"],
                ["披露方案", "对每项事实的必要性、精度、处理动作、理由和残余风险记录"],
                ["请求快照", "提交审批前冻结的目标、模型、披露正文、规则、材料和配置版本"],
                ["来源回链", "从结果或事实返回边侧原文位置的关联能力"],
                ["具名复核", "由具有相应角色的登录用户对当前版本提交可追溯意见"],
                ["后继任务", "当前请求修改或被否决后，基于保留记录重新建立的新任务"],
            ],
            col_widths=[3.4, 12.6],
        )
        self.h1("附录 B  快速操作清单")
        self.numbered(
            [
                "使用具名账号登录并确认角色。",
                "新建案件，确认案件名称和当前工作空间。",
                "上传材料，检查材料版本、解析状态和识别提示。",
                "逐项核对事实，并使用“查看原文依据”确认上下文。",
                "运行本地时间线、证据清单或争点候选时，确认其不构成法律结论。",
                "生成披露方案，逐项选择必要性和处理动作。",
                "核对实际披露正文、信息损失和残余风险。",
                "检验风险并冻结请求，展开完整请求核对目标和版本。",
                "由法学复核人员提交当前请求的具名结论。",
                "由审批人员批准当前完整请求。",
                "由案件操作人员执行任务，并观察真实状态。",
                "在摘要与回链中逐句核对、确认、导出和归档。",
            ]
        )


def main() -> None:
    images = prepare_images()
    manual = Manual(images)
    manual.build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manual.doc.save(str(OUTPUT))
    DOWNLOADS.parent.mkdir(parents=True, exist_ok=True)
    manual.doc.save(str(DOWNLOADS))
    print(f"wrote {OUTPUT}")
    print(f"wrote {DOWNLOADS}")
    print(f"size={OUTPUT.stat().st_size}")


if __name__ == "__main__":
    main()
