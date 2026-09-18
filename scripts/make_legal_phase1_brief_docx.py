"""Export remaining legal-side phase-1 blanks only. Already-submitted items are omitted."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = Path(__file__).resolve().parent / "make_legal_evidence_docx.py"
OUT = ROOT / "docs" / "legal" / "法计交接" / "案隐盾_法学阶段一先交材料与填写说明_2026-09-15.docx"
DOC_ID = "LEX-LG-PHASE1-2026-09-15"

spec = importlib.util.spec_from_file_location("cs_brief", HELPER)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def add_footer(section):
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"{DOC_ID}  ·  仅未交空栏  ·  已提交内容不重复  ·  填表≠pass≠可发送  ·  第 ")
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


def new_doc():
    doc = cs.Document()
    section = doc.sections[0]
    cs.set_cell_margins(section)
    add_footer(section)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = cs.Pt(11)
    normal._element.rPr.rFonts.set(cs.qn("w:eastAsia"), "宋体")
    return doc


def bullet(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = cs.Pt(0)
    p.paragraph_format.space_after = cs.Pt(4)
    p.paragraph_format.left_indent = cs.Cm(0.74)
    p.paragraph_format.first_line_indent = cs.Cm(0)
    p.paragraph_format.line_spacing = 1.25
    run = p.add_run("·  " + text)
    cs.set_run_font(run, size=10.5)
    return p


def sign_block(doc, roles):
    cs.add_p(doc, "签署栏（纸质或扫描件入受控库；正文不进 git）", size=10, bold=True, first_line=False, space_after=6)
    cs.add_table(
        doc,
        ["角色", "姓名", "日期", "签字"],
        [[role, "", "", ""] for role in roles],
        col_cm=[5.6, 3.4, 3.2, 4.0],
    )


def cover(doc):
    title = doc.add_paragraph()
    title.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = cs.Pt(18)
    title.paragraph_format.space_after = cs.Pt(6)
    r = title.add_run("案隐盾 · 法学阶段一未交材料")
    cs.set_run_font(r, name="微软雅黑", size=20, bold=True, color=cs.FOREST)

    sub = doc.add_paragraph()
    sub.alignment = cs.WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = cs.Pt(14)
    r = sub.add_run("只列尚未提交的空栏　·　已登记项不重复、不要求重交")
    cs.set_run_font(r, name="微软雅黑", size=11, color=cs.MUTED)

    cs.add_table(
        doc,
        ["项", "内容"],
        [
            ["材料编号", DOC_ID],
            ["产品版本", "V1.0（1.0.0，非正式发行）"],
            ["适用三元组", "LA-001 × R_fact_summary × D_DeepSeek_official_API"],
            ["性质", "未交空栏 + 填写格式。不是已签署、不是 pass、不是发送许可。"],
            ["编制规则", "已提交内容一律忽略：不摘录、不预填、不要求重写。空栏保持空。"],
            ["交回位置", "受控库；技 07 只登文件名与 SHA-256。签署正文不进 git。"],
        ],
        col_cm=[3.4, 12.8],
    )

    cs.add_heading(doc, "本册故意忽略（已提交，不要重交）", 1)
    cs.add_p(
        doc,
        "下列材料已经交出或已登记。本册不摘其正文，不要求法学再写一遍。落签法计交接空表时，不要把这些结论重新论证一遍。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["已提交/已登记", "位置（只作索引，勿抄回本册）", "本册因此不列"],
        [
            ["A1–A6、B1–B2、C1–C5、D", "docs/legal/法学交付清单-2026-09-12.md；LEX-LG-AI-2026-09-12-01", "合成用途、四路径是否允许、A5 对象级期限规则、演示设计层、G1–G5 AI 意见、10 行内部使用、截月阻断、Path C 预期"],
            ["一对一当面确认", "docs/legal/法学一对一确认-2026-09-12.md", "必写句、权重口述、处理角色/地区口述、口头人审主张、口头「允许使用」"],
            ["公开检索摘录与档案草案", "docs/legal/D路径-DeepSeek公开检索摘录-2026-09-14.md；D路径-DeepSeek档案草案.json", "开放平台/隐私政策全文对照、草案可写字段"],
            ["规则正文与 G 指南", "docs/legal/案隐盾_系统法学规则与验收标准_v1.0.md；G-2026-09-12-v1.0.md", "规则内容、G1–G5 工程摘录"],
            ["计算机侧事实 / 须填表 / 交接稿", "LEX-CS-EVID、LEX-LG-REQ、LEX-LG-HANDOFF", "已发出的旧表；REQ 空栏若与下表重复，以下表为准只填一次"],
            ["隔离栈工程基线 / D 走一遍", "docs/legal/隔离栈攻击实跑-2026-09-12.md；十案D路径走一遍记录-2026-09-14.md", "工程结果。非法学 resisted，不是本阶段先交项"],
        ],
        col_cm=[3.8, 6.2, 6.2],
    )
    cs.add_note(doc, "口述与 AI 意见不是 reviewed、不是人类会签、不是本案 PIPIA。忽略它们的正文，不等于这些门已经过。")

    cs.add_heading(doc, "现在只要交这些", 1)
    cs.add_table(
        doc,
        ["页", "未交项（仅此）", "已有但不算本页已交"],
        [
            ["法 02", "组织授权：机关、文件、范围、期限、具名", "一对一必写句；10 案口述「允许使用」"],
            ["法 03", "本账号书面四项 + 审核人 + 评估引用 + 有效期", "公开 TOS 摘录；口头训练/留存/分包占位"],
            ["法 01", "采用集、使用条件、运行 pass、副本对照", "口头「人工核查成功」；正式页未命中检索"],
            ["法 06", "本三元组双人标注 A/B、分歧、第三人仲裁", "C4 驳回的评测人类双标；标注模板本身"],
            ["配 01", "四路径处理依据 / 必要性 / 告知；主体是否同一依据", "A1 用途、A2「路径允许」、A5 期限规则"],
            ["配 02", "演示 01/02/03 实际运行验收表", "A6 设计层意见；C3 截月阻断口径"],
            ["法 04（续）", "本案 PIPIA 全文（法 01、03 齐后）", "LEX-LG-AI §4 内部意见"],
            ["法 05（续）", "会签、权重冻结、写死 published_scope", "B1 AI 意见；一对一「各 0.2」口述"],
        ],
        col_cm=[2.4, 7.0, 6.8],
    )


def chapter_fa02(doc):
    doc.add_page_break()
    cs.add_heading(doc, "法 02 · 未交：真实材料组织授权", 1)
    cs.add_p(
        doc,
        "一对一已写本次必写句，10 案口述「允许使用」。本页不重拟那句话，也不重开十案授权表。仍缺：授权机关/组织、授权文件、覆盖范围、期限、具名人签。主体与期限未写、未具名，本页视为未交。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["授权机关 / 组织（全称）", ""],
            ["授权文件位置 / SHA-256", ""],
            ["授权覆盖的材料范围", "须含本次工作副本；勿写真名、案号全文"],
            ["试点范围（案 × 子目的 × 接收方 × 期限）", "只写本三元组。不要扩九案"],
            ["是否允许入库评测主库", "□ 否（默认）　　□ 是（须另文；现行主库禁止真案）"],
            ["是否允许真实云端发送", "□ 否　　□ 是（仍须十门全过；本句不是发送许可）"],
            ["签署人姓名 / 职务", ""],
            ["签署日期", ""],
            ["组织授权", "□ 已交　　□ 未交"],
        ],
        col_cm=[6.2, 10.0],
    )
    sign_block(doc, ["组织授权签署人"])
    cs.add_heading(doc, "可选检索（只核文件位置，不抄已登记结论）", 2)
    cs.add_table(
        doc,
        ["资料", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/法02_门2_本次授权与真实材料授权.md", "只填「真实材料组织授权」节。必写句节不要重写。"],
            ["待办 D 行「组织授权」", "docs/legal/法学待办完整清单-2026-09-12.md 第 D 节该行", "对照「主体/期限未写、未具名」。不要抄口述「允许」。"],
        ],
        col_cm=[4.2, 6.2, 5.8],
    )


def chapter_fa03(doc):
    doc.add_page_break()
    cs.add_heading(doc, "法 03 · 未交：本账号书面证据（硬卡点）", 1)
    cs.add_p(
        doc,
        "公开检索摘录和档案草案已交，本页不摘协议条文。一对一口头训练/留存/分包/「默认合法」已登记，一律忽略，不得写入本页结论。缺下列书面项则不得标 reviewed，也不得发送。",
        first_line=False,
        size=10.5,
    )
    cs.add_heading(doc, "一对一已点名、仍未写出", 2)
    cs.add_table(
        doc,
        ["项", "证据位置 / SHA-256", "法学结论（查不到写未知）"],
        [
            ["本账号合同引用 + 版本（可打开的链接或合同编号）", "", "本账号点击同意的是否即该版："],
            ["签约及实际提供 API 的主体全称", "", "是否即本 API 合同抬头："],
            ["服务商侧删除渠道是否覆盖本次请求正文", "", "与「本地管理员同意」不是同一件事"],
            ["分包 / 转委托真实名单", "", "□ 无　　□ 有名单　　□ unknown（阻断）。不要填甲/乙公司"],
        ],
        col_cm=[5.6, 5.4, 5.2],
    )
    cs.add_heading(doc, "档案要 reviewed 仍空的其余项", 2)
    cs.add_table(
        doc,
        ["项", "证据位置 / SHA-256", "法学结论"],
        [
            ["实际使用的 API 账号标识（无 Key）", "", ""],
            ["本账号点击同意 / 控制台截图（无 Key）", "", ""],
            ["本账号训练或优化书面证（输入/输出/日志）", "", "□ 不用于　　□ 用于　　□ unknown（阻断）"],
            ["人工访问条件与审计（是否读请求正文）", "", "□ 已核　　□ unknown（阻断）"],
            ["审核人姓名（可核身份，勿用张三/李四）", "", ""],
            ["impact_assessment_reference", "", "勿填 LEX-LG-AI §4"],
            ["valid_until", "", ""],
            ["系统操作", "", "□ 未点「具名复核」　　□ 已点且系统接受（写时间）"],
            ["本页结论", "", "□ 可标 reviewed　　□ 维持 draft，保持阻断"],
        ],
        col_cm=[5.6, 5.4, 5.2],
    )
    sign_block(doc, ["取证 / 材料提交（法学方）", "法学复核人（legal_reviewer）"])
    cs.add_heading(doc, "可选检索（取本账号证，不打开已摘协议当结论）", 2)
    cs.add_table(
        doc,
        ["资料", "路径或动作", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/法03_门3_本账号服务商证据包.md", "只填上列空栏。不要把摘录表抄进结论。"],
            ["本账号控制台", "实际登录的 DeepSeek 开放平台账号（无 Key 截图）", "核点击同意版本、账号标识、有无训练开关。"],
            ["企业合同（若有）", "本组织与服务商的纸质/电子合同", "抄编号与抬头全称。没有就写未知，不要发明编号。"],
            ["删除询证", "api-service@deepseek.com 或合同载明渠道", "问清是否含本次请求正文。询证不要附事实卡或 Key。"],
        ],
        col_cm=[3.4, 6.6, 6.2],
    )
    cs.add_note(doc, "备槽不纳入本次 D 批准目标。不要为百炼补本页。")


def chapter_fa01(doc):
    doc.add_page_break()
    cs.add_heading(doc, "法 01 · 未交：采用集、使用条件、运行 pass", 1)
    cs.add_p(
        doc,
        "口头「目前依据人工核查成功」已登记，只是主张。正式页未命中检索已记在安排稿。本页不重复那些结论。仍缺：拟上云采用集、使用条件、工作副本对照、运行层面 pass。",
        first_line=False,
        size=10.5,
    )
    cs.add_heading(doc, "核验头表（只填仍空项）", 2)
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["工作副本路径", ""],
            ["版本（人审日或文件 SHA-256）", "哈希 ≠ 人审通过"],
            ["与解析副本是否同一份", "□ 是　　□ 否　　□ 无法核对"],
            ["运行层面 pass", "□ 已登记　　□ 未给"],
        ],
        col_cm=[5.4, 10.8],
    )
    cs.add_heading(doc, "拟上云事实采用集（勿写真名、案号全文）", 2)
    cs.add_table(
        doc,
        ["事实 ID", "主张 / 法院认定 / 程序结果", "拟上云表述", "不采用理由", "不得改写的限制"],
        [
            ["", "", "□ 采用　□ 不采用", "", ""],
            ["", "", "□ 采用　□ 不采用", "", ""],
            ["", "", "□ 采用　□ 不采用", "", ""],
            ["", "", "□ 采用　□ 不采用", "", ""],
            ["", "", "□ 采用　□ 不采用", "", ""],
            ["", "", "□ 采用　□ 不采用", "", ""],
        ],
        col_cm=[2.2, 4.4, 3.2, 3.2, 3.2],
    )
    cs.add_heading(doc, "使用条件（本案结论，非法条目录）", 2)
    cs.add_table(
        doc,
        ["项", "结论", "依据（页码或条款，勿贴原文隐私）"],
        [
            ["撤回 / 下架", "□ 未见　□ 有（停用）　□ 未核清", ""],
            ["使用 / 传播限制", "□ 无额外限制　□ 有（说明）　□ 未核清", ""],
            ["订阅库许可", "□ 不适用　□ 已核可　□ 不可用", ""],
            ["仍可识别的个人 / 第三人 / 敏感信息", "", "组合判断另页，此处只登记"],
            ["处理依据", "", ""],
            ["是否「合理范围」", "□ 是　□ 否　□ 须另评", ""],
            ["向该接收方发送是否「重大影响」", "□ 是（须同意）　□ 否　□ 未决（阻断）", ""],
            ["用途", "", ""],
            ["本地整理期限 / 发送有效期（分开写）", "", ""],
            ["本页结论", "□ 人审完成，采用集可进冻结核范围　□ 未完成，保持阻断", ""],
            ["运行 pass", "□ 已补　□ 未补", ""],
        ],
        col_cm=[5.2, 5.8, 5.2],
    )
    sign_block(doc, ["核查人（法学主签）"])
    cs.add_heading(doc, "可选检索", 2)
    cs.add_table(
        doc,
        ["资料", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/法01_门1_来源核验与人工审查.md", "只填采用集与使用条件。不要重写检索未命中。"],
            ["本机工作副本", ".data/real_cases/（不入库）", "对照解析副本。sourced ≠ 已人审。"],
            ["法源对照", "legal/sources/", "写依据时用法条号，勿贴原文隐私。"],
        ],
        col_cm=[3.4, 6.4, 6.4],
    )


def chapter_fa06(doc):
    doc.add_page_break()
    cs.add_heading(doc, "法 06 · 未交：本三元组双人标注与仲裁", 1)
    cs.add_p(
        doc,
        "C4 已驳回「评测必须人类双标」。本页不重开那项争论。法计交接仍要求：本次真实材料（LA-001 × R × D）双人标注 + 第三人仲裁。技术兼任 approver 不能省略本项。标注模板已有，不算已标注。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["标注指南 / 工作簿版本（本次实际使用的副本）", ""],
            ["本三元组双人标注人 A / B", ""],
            ["分歧项与处理", ""],
            ["第三人仲裁人 / 日期", ""],
            ["材料位置 / SHA-256（受控库）", ""],
            ["10 案双人校准", "□ 未做，另档待办（不打开九案）　　□ 已另档（写位置）"],
            ["本页结论", "□ 本次材料校准可支撑法 01 采用集　　□ 未交"],
        ],
        col_cm=[6.4, 9.8],
    )
    cs.add_heading(doc, "单条标注字段（写入工作簿副本，勿发明新法源）", 2)
    cs.add_table(
        doc,
        ["字段", "填写说明"],
        [
            ["annotator", "具名；A 与 B 不得为同一人"],
            ["fact_id", "对应记录内事实 id；勿写真名"],
            ["field", "entity / relation / event / date / amount / evidence"],
            ["necessity", "required / conditional / unnecessary / uncertain"],
            ["transform", "keep / pseudonymize / generalize / delete"],
            ["notes", "可选；不得写入真实身份"],
            ["adjudication", "仅第三人裁定分歧"],
        ],
        col_cm=[3.6, 12.6],
    )
    sign_block(doc, ["标注人 A", "标注人 B", "第三人仲裁人"])
    cs.add_heading(doc, "可选检索（模板，不是已完成记录）", 2)
    cs.add_table(
        doc,
        ["资料", "路径", "本页用法"],
        [
            ["标注指南 / 工作簿", "legal/templates/案隐盾_法律标注指南_v0.1.docx；案隐盾_法律标注工作簿_v0.1.xlsx", "复制副本填写。填完入受控库。"],
            ["本页空表", "docs/legal/法计交接/法06_真实材料双人标注与仲裁.md", "只登本三元组。"],
        ],
        col_cm=[3.6, 6.8, 5.8],
    )


def chapter_pei01(doc):
    doc.add_page_break()
    cs.add_heading(doc, "配 01 · 未交：依据 / 必要性 / 告知（落到人和行为）", 1)
    cs.add_p(
        doc,
        "A1 用途、A2「四路径允许」、A5 对象级期限规则已登记。本页不重写那些口径。仍空：各路径的处理依据、必要性、告知/同意；劳动者 / 用人单位联系人 / 证人 / 家属是否同一依据。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["路径", "处理依据", "必要性", "告知 / 同意", "是否与劳动者同一依据"],
        [
            ["本地整理（解析 / OCR / 人工事实）", "", "", "", "对方：　　证人：　　家属："],
            ["本地确定性任务", "", "", "", "对方：　　证人：　　家属："],
            ["边侧抽取", "", "", "", "对方：　　证人：　　家属："],
            ["可选云端摘要（仅 D）", "", "", "", "对方：　　证人：　　家属："],
        ],
        col_cm=[3.4, 3.2, 2.8, 3.2, 3.6],
    )
    cs.add_note(doc, "「履行合同所必需」不能自动覆盖对方和证人，也不能自动证明可选云端必要。查不到写未知。")
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["本页结论", "□ 依据已写到人和行为　　□ 未写"],
        ],
        col_cm=[5.4, 10.8],
    )
    sign_block(doc, ["法学口径主签"])
    cs.add_heading(doc, "可选检索", 2)
    cs.add_table(
        doc,
        ["资料", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/配01_法学_处理与数据治理口径.md", "只填依据/必要性/告知。不要重填用途和 A5 规则。"],
            ["待办 A2 空栏", "docs/legal/法学待办完整清单-2026-09-12.md A2 表「未写」列", "与本表同一批空栏，只填一次。"],
        ],
        col_cm=[3.4, 6.4, 6.4],
    )


def chapter_pei02(doc):
    doc.add_page_break()
    cs.add_heading(doc, "配 02 · 未交：演示三案实际运行验收", 1)
    cs.add_p(
        doc,
        "A6 设计层意见已交；工程拒绝把三案记成实际验收通过（未读取完整实际输出）。C3 截月阻断已登记，本页不重写输出对错口径。仍缺：对着实际界面/输出填的验收表。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["案", "须评什么（实际输出，不是设计）", "等级", "说明", "复核人"],
        [
            ["DEMO-01", "主体关系、日期、金额与主张、证据归属、不应披露的线索。来源必须是模拟拼接，不是模型生成。", "□ 阻断 □ 必须改 □ 建议改 □ 可接受", "", ""],
            ["DEMO-02", "组合线索批准是否 409；阻断原因是否成立。无摘要。", "□ 阻断 □ 必须改 □ 建议改 □ 可接受", "", ""],
            ["DEMO-03", "材料不完整是否主动停止；阻断原因是否成立。无摘要。", "□ 阻断 □ 必须改 □ 建议改 □ 可接受", "", ""],
        ],
        col_cm=[2.2, 5.4, 3.2, 2.8, 2.6],
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["验收记录位置 / SHA-256", ""],
            ["是否用这三案给云端模型打质量分", "□ 否（应选）　　□ 是（无效）"],
        ],
        col_cm=[5.4, 10.8],
    )
    sign_block(doc, ["法学验收人"])
    cs.add_heading(doc, "可选检索", 2)
    cs.add_table(
        doc,
        ["资料", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/配02_法学_输出与演示验收.md", "只填演示验收位置。不要重填主张/截月口径。"],
            ["LEX-LG-REQ 第 8 节", "docs/legal/LEX-LG-REQ-2026-09-10-01.docx", "若该节细表仍空，与本表合并只填一次。"],
        ],
        col_cm=[3.6, 6.4, 6.2],
    )


def chapter_fa04_fa05(doc):
    doc.add_page_break()
    cs.add_heading(doc, "续交 · 法 04 本案 PIPIA（法 01、法 03 齐后）", 1)
    cs.add_p(
        doc,
        "LEX-LG-AI §4 已作为内部意见交出，不能替代本案评估，本页不摘该节。接收方条件仍为 unknown 时不得选「可用」。法 03 书面项未齐时不要先签本页。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["内部案号 / 子目的 / 接收方", ""],
            ["事实卡版本（门 6 哈希或草案编号）", "尚未冻结则写草案号；冻结后重评"],
            ["处理对象（类别，勿写真名）", ""],
            ["信息类别与必要性（逐项：删后任务是否仍可完成）", ""],
            ["处理依据（接法 01）", ""],
            ["接收方条件（接法 03；unknown 不得选可用）", ""],
            ["主要风险", ""],
            ["已实施措施（只写已核为真的）", ""],
            ["替代方案（本地摘要 / 不外发）", ""],
            ["残余风险是否接受及理由（禁止只写「低风险」）", ""],
            ["告知或例外、异议 / 删除、联系人、事故处理", ""],
            ["报告保存位置、三年保留起点", ""],
            ["最终结论", "□ 可用　　□ 附条件可用　　□ 不可用"],
            ["条件（列完且已落实才算）", ""],
            ["变化后", "□ 已重评　　□ 未重评（原结论失效）"],
        ],
        col_cm=[6.4, 9.8],
    )
    sign_block(doc, ["实施人", "复核人"])
    cs.add_table(
        doc,
        ["可选检索", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/法04_门4_PIPIA.md", "只填本案空栏。"],
            ["个保法对照", "legal/sources/个人信息-个保法-处理方式对应表.xlsx", "写类别与必要性。"],
        ],
        col_cm=[3.4, 6.8, 6.0],
    )

    cs.add_heading(doc, "续交 · 法 05 规则会签（未签项）", 1)
    cs.add_p(
        doc,
        "B1 AI 意见与一对一「各 0.2」已登记。本页不摘 G 条、不预填权重。仍缺人类会签、五类冻结、写死 published_scope、审核记录编号。仓库草稿保持 draft。",
        first_line=False,
        size=10.5,
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["子目的与允许上云字段（required / optional / forbidden）", ""],
            ["明确不上云的字段", ""],
            ["条件规则（待审草稿不得直接当已发布）", ""],
            ["法源与指南版本 + 文本日期", ""],
            ["entity / density / context / combination / cross_round", ""],
            ["五类是否冻结", "□ 是　　□ 否"],
            ["published_scope（须写死本三元组；写入十案则本页作废）", ""],
            ["审核记录编号", ""],
            ["会签人 / 日期", ""],
            ["本页结论", "□ 法学签署齐，可交技 02　　□ 未齐，保持阻断"],
        ],
        col_cm=[6.4, 9.8],
    )
    sign_block(doc, ["规则会签人"])
    cs.add_table(
        doc,
        ["可选检索", "路径", "本页用法"],
        [
            ["本页空表", "docs/legal/法计交接/法05_门5_规则发布法学签署.md", "只填未签栏。不要抄 AI 意见当会签。"],
            ["仓库草稿包", "packs/labor_v2_draft.json", "对照字段。不要改成 published。"],
        ],
        col_cm=[3.4, 6.8, 6.0],
    )


def chapter_return(doc):
    doc.add_page_break()
    cs.add_heading(doc, "交回清单（只登未交件）", 1)
    cs.add_table(
        doc,
        ["编号", "未交材料", "受控文件名", "SHA-256（技术填）", "状态"],
        [
            ["法 02", "组织授权（具名；主体/期限）", "", "", ""],
            ["法 03", "本账号书面证据包 + 无 Key 截图", "", "", ""],
            ["法 01", "采用集 + 使用条件 + 运行 pass", "", "", ""],
            ["法 06", "本三元组双人标注 / 仲裁", "", "", ""],
            ["配 01", "依据 / 必要性 / 告知分主体表", "", "", ""],
            ["配 02", "演示三案实际验收记录", "", "", ""],
            ["法 04", "本案 PIPIA（01、03 齐后）", "", "", ""],
            ["法 05", "规则会签（未签栏）", "", "", ""],
        ],
        col_cm=[1.6, 5.0, 3.6, 3.6, 2.4],
    )
    cs.add_table(
        doc,
        ["项", "填写"],
        [
            ["提交人 / 职务", ""],
            ["提交日期", ""],
            ["附件件数", ""],
            ["是否含已提交材料的复印件充数", "□ 无（应选）　　□ 有（撤出重交）"],
            ["是否含 API Key 或真名/案号全文", "□ 无（应选）　　□ 有（撤回重交）"],
            ["接收技术方 / 日期", ""],
        ],
        col_cm=[6.4, 9.8],
    )
    sign_block(doc, ["法学提交人", "技术接收人（仅收存，不代签结论）"])
    cs.add_note(
        doc,
        "本册写于 2026-09-15。只覆盖当时仍空的法学先交项。已登记内容以交付清单与一对一为准，不要把本册没有的旧结论当成未交。",
    )


def build():
    doc = new_doc()
    cover(doc)
    chapter_fa02(doc)
    chapter_fa03(doc)
    chapter_fa01(doc)
    chapter_fa06(doc)
    chapter_pei01(doc)
    chapter_pei02(doc)
    chapter_fa04_fa05(doc)
    chapter_return(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
