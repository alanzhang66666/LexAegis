"""Recognize offline recording material by content, without trusting filenames."""
import hashlib
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .demo import RECORDING_DOCUMENTS, SCENARIOS


def _text(data: bytes) -> str | None:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            member = archive.getinfo('word/document.xml')
            if member.file_size > 4 * 1024 * 1024:
                return None
            xml = archive.read(member)
        if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
            return None
        root = ET.fromstring(xml)
        text = ''.join(node.text or '' for node in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        return re.sub(r'\s+', '', text)
    except (BadZipFile, KeyError, ET.ParseError, ValueError, RuntimeError):
        return None


def identify_recording(data: bytes) -> str | None:
    exact = RECORDING_DOCUMENTS.get(hashlib.sha256(data).hexdigest())
    if exact:
        return exact
    uploaded = _text(data)
    if not uploaded:
        return None
    directory = Path(__file__).resolve().parents[1] / 'data/recording_adapted'
    matches = set()
    for path in directory.glob('*.docx'):
        trusted = path.read_bytes()
        scenario = RECORDING_DOCUMENTS.get(hashlib.sha256(trusted).hexdigest())
        if not scenario or not SCENARIOS[scenario].get('offline_only'):
            continue
        full = _text(trusted)
        if not full:
            continue
        # The registered Word retains the complete supplied source after this heading.
        _, marker, original = full.partition('原始案件文书及标注')
        if uploaded == full or (marker and uploaded == original):
            matches.add(scenario)
    return next(iter(matches)) if len(matches) == 1 else None


# Search terms point to supplied text, never to a generated conclusion.
SOURCE_TERMS = {
    'la001_edge_block': [
        ['吾某'], ['鑫瑞通公司'], ['不构成事实劳动关系'],
        ['879号'], ['2021年6月8日', '2022年6月', '2022年9月'],
        ['业务提成', '柜台'], ['162000', '55862'], ['转账', '驳回上诉'],
    ],
    'la002_human_veto': [
        ['刘某'], ['某公司'], ['职务为店长', '劳动关系'],
        ['全某', '社会保险补贴'], ['87000'], ['2017年8月', '专柜撤柜'],
        ['2015年9月1日', '2015年9月25日', '驳回上诉'],
    ],
    'la003_review_release': [
        ['袁某'], ['某甲公司'], ['存在劳动关系'], ['早会', '请假', '代发'],
        ['收入账单', '站点交接协议', '服务合作合同'], ['封号', '移出工作群'],
        ['19387.81', '7355.7', '1596.38'], [],
    ],
}


# Curated local work products for the three supplied cases.  These entries only
# restate facts and holdings that are present in the attached Word material.
# They let the deterministic timeline, evidence and issue tools show useful,
# case-specific results without sending the source material to a model.
RECORDING_LOCAL_ARTIFACTS = {
    'la001_edge_block': {
        'timeline': [
            {'text': '2012年9月4日：劳动者主张开始在营业厅从事终端、配件销售。', 'source_terms': [('2012年9月4日',)]},
            {'text': '2021年6月8日：鑫瑞通公司登记设立，设立前后的用工主体资格需分段审查。', 'source_terms': [('2021年6月8日',)]},
            {'text': '2022年6月：一审认定公司开始入驻营业厅；公司另主张入驻时间为2022年9月。', 'source_terms': [('2022年6月', '2022年9月')]},
            {'text': '2024年8月20日：劳动者主张的工作期间截止，并主张被迫离职。', 'source_terms': [('2024年8月20日',)]},
            {'text': '2025年9月25日：劳动仲裁裁决驳回全部仲裁请求。', 'source_terms': [('2025年9月25日',)]},
            {'text': '2026年7月3日：二审公开开庭审理。', 'source_terms': [('2026年7月3日',)]},
        ],
        'evidence_inventory': [
            {'text': '工作牌、工作群聊天记录及工作照片', 'purpose': '核对工作地点、工作内容与劳动管理主体。', 'source_terms': [('工作牌', '工作群')]},
            {'text': '负责人个人账户转账、业务结算及提成记录', 'purpose': '判断款项属于工资、业务提成还是其他经营往来。', 'source_terms': [('个人', '转账'), ('业务提成',)]},
            {'text': '柜台分摊费与超市收益往来记录', 'purpose': '核对双方主张的合作关系和款项性质。', 'source_terms': [('柜台分摊费',), ('超市', '收益')]},
            {'text': '加班时段截图、审批、考勤及工作量材料', 'purpose': '核对法定节假日加班是否由用工主体安排并实际发生。', 'source_terms': [('加班审批',), ('在岗考勤',)]},
        ],
        'issue_extraction': [
            {'topic': 'employer_qualification', 'label': '用工主体与期间', 'text': '公司设立前后是否可由同一主体承担用工关系，以及主张期间应如何分段审查。', 'fields': ['relation', 'date'], 'source_terms': [('公司设立前',), ('用工主体资格',)]},
            {'topic': 'labor_management', 'label': '劳动管理与从属性', 'text': '营业厅经营秩序管理与鑫瑞通公司专属劳动管理应如何区分。', 'fields': ['relation', 'event'], 'source_terms': [('劳动管理', '营业厅')]},
            {'topic': 'payment_nature', 'label': '款项性质', 'text': '个人账户转账属于固定工资、业务提成、营销激励还是合作收益。', 'fields': ['event', 'evidence'], 'source_terms': [('业务提成', '工资')]},
            {'topic': 'compensation_overtime', 'label': '补偿与加班请求', 'text': '经济补偿与法定节假日加班工资是否具备劳动关系和证据基础。', 'fields': ['amount', 'evidence'], 'source_terms': [('经济补偿金', '加班工资')]},
        ],
    },
    'la002_human_veto': {
        'timeline': [
            {'text': '2015年9月1日：一审与仲裁采用的劳动关系起算日。', 'source_terms': [('2015年9月1日',)]},
            {'text': '2015年9月25日：二审说理采用的首次工资发放日，与一审主文起算日存在差异。', 'source_terms': [('2015年9月25日',)]},
            {'text': '2017年8月：企业主张劳动者开始在异地缴纳社会保险。', 'source_terms': [('2017年8月',)]},
            {'text': '2020年6月30日：双方认可专柜撤柜，劳动者不再工作。', 'source_terms': [('2020年6月30日', '专柜撤柜')]},
            {'text': '2025年6月19日：劳动者申请仲裁确认劳动关系。', 'source_terms': [('2025年6月19日',)]},
            {'text': '2025年8月28日：仲裁裁决确认部分期间存在劳动关系。', 'source_terms': [('2025年8月28日',)]},
        ],
        'evidence_inventory': [
            {'text': '法定代表人亲属个人账户的长期按月转账记录', 'purpose': '核对工资支付的持续性、周期性及付款人与企业的关系。', 'source_terms': [('银行流水显示', '每月支付')]},
            {'text': '店长岗位、业务组成及日常管理材料', 'purpose': '核对劳动者是否接受企业管理并从事企业业务组成部分。', 'source_terms': [('职务为店长',)]},
            {'text': '每月1500元社会保险补贴及58个月支付记录', 'purpose': '核对补贴约定的性质及其是否足以否定劳动关系。', 'source_terms': [('社会保险补贴1500元',)]},
            {'text': '2017年8月起异地参保及后续转移记录', 'purpose': '核对异地参保是否能证明另一劳动关系或兼职关系。', 'source_terms': [('2017年8月', '缴纳社会保险')]},
        ],
        'issue_extraction': [
            {'topic': 'start_date_conflict', 'label': '关系起算日差异', 'text': '一审主文的2015年9月1日与二审说理的2015年9月25日未统一，须人工核对。', 'fields': ['date', 'evidence'], 'source_terms': [('2015年9月1日', '2015年9月25日')]},
            {'topic': 'employment_status', 'label': '劳动关系或兼职', 'text': '店长岗位、企业管理、长期按月付款与企业提出的兼职抗辩如何评价。', 'fields': ['relation', 'event'], 'source_terms': [('兼职', '店长')]},
            {'topic': 'social_insurance', 'label': '补贴与异地参保', 'text': '社会保险补贴和异地参保记录是否足以证明双重劳动关系。', 'fields': ['amount', 'date', 'evidence'], 'source_terms': [('双重劳动关系',)]},
            {'topic': 'limitation_scope', 'label': '时效与请求范围', 'text': '确认劳动关系之诉是否受一年仲裁时效限制，以及本案是否仅处理关系确认。', 'fields': ['event', 'evidence'], 'source_terms': [('不受劳动争议申请仲裁时效',)]},
        ],
    },
    'la003_review_release': {
        'timeline': [
            {'text': '2023年9月10日：站点配送业务交接协议签订。', 'source_terms': [('2023年9月10日',)]},
            {'text': '2024年7月14日：劳动者开始在站点从事全职配送工作。', 'source_terms': [('2024年7月14日',)]},
            {'text': '2025年4月11日：账号停用并被移出工作群，实际停止工作。', 'source_terms': [('2025年4月11日', '移出')]},
            {'text': '2025年5月14日：劳动者提出仲裁申请。', 'source_terms': [('2025年5月14日',)]},
            {'text': '2025年8月4日：仲裁机构作出裁决。', 'source_terms': [('2025年8月4日',)]},
            {'text': '2026年7月30日：二审裁判形成并维持主要给付项目。', 'source_terms': [('2026年7月30日',)]},
        ],
        'evidence_inventory': [
            {'text': '平台收入账单、扣款截图、银行流水及工资短信', 'purpose': '核对报酬来源、支付周期与工资差额。', 'source_terms': [('收入账单', '银行流水')]},
            {'text': '招聘广告、与站长的聊天、请假及群公告记录', 'purpose': '核对排班、请假、考核和奖惩等实际管理。', 'source_terms': [('招聘广告', '请假')]},
            {'text': '账号停用与移出工作群记录', 'purpose': '核对劳动者停止工作的过程及解除事实。', 'source_terms': [('封号', '移出群聊')]},
            {'text': '站点交接协议、服务合作合同及挂靠经营协议', 'purpose': '核对站点经营主体、外包关系及第三方代发安排。', 'source_terms': [('代理商站点交接协议',), ('自由职业者挂靠经营协议',)]},
        ],
        'issue_extraction': [
            {'topic': 'operating_entity', 'label': '站点经营主体', 'text': '站点配送业务由谁实际承接，外包与合作文件能否证明经营主体已经转移。', 'fields': ['relation', 'evidence'], 'source_terms': [('经营主体问题',)]},
            {'topic': 'platform_management', 'label': '平台劳动管理', 'text': '早会、排班、派单、请假、考核与奖惩是否构成支配性劳动管理。', 'fields': ['relation', 'event', 'evidence'], 'source_terms': [('支配性劳动管理',)]},
            {'topic': 'written_contract', 'label': '未签书面合同', 'text': '第三方挂靠协议能否替代实际用工主体应签订的书面劳动合同。', 'fields': ['event', 'evidence'], 'source_terms': [('挂靠协议不能替代劳动合同',)]},
            {'topic': 'termination', 'label': '停止工作与补偿', 'text': '账号停用、移出工作群与劳动关系解除及经济补偿之间的事实联系。', 'fields': ['event', 'evidence'], 'source_terms': [('实际停止了', '工作权限')]},
            {'topic': 'wage_claims', 'label': '工资差额与其他请求', 'text': '最低工资差额的证据责任，以及加班等其余请求是否有充分材料支持。', 'fields': ['event', 'evidence'], 'source_terms': [('工资差额', '加班工资')]},
        ],
    },
}


# Content shown in the four workbench boundaries after a supplied Word file has
# been matched and stored.  The upload is the unlock event: merely creating a
# case with one of these scenario ids must not expose this material.
RECORDING_STAGE_CONTENT = {
    'la001_edge_block': {
        'facts': {
            'label': '材料事实',
            'title': '主体设立时间与实际管理关系需要分段核对',
            'summary': '原文同时包含长期在营业厅销售、公司后设立、入驻时间争议及个人账户结算等事实，不能只凭工作地点或转账记录判断劳动关系。',
            'items': [
                {'label': '主体与期间', 'text': '劳动者主张自2012年起工作，公司于2021年设立；公司设立前后的用工主体资格应分别审查。'},
                {'label': '管理关系', 'text': '需区分营业厅经营秩序管理与鑫瑞通公司对劳动者的专属劳动管理。'},
                {'label': '款项性质', 'text': '个人账户转账、业务提成、柜台分摊费及超市收益往来存在不同解释。'},
                {'label': '请求与证据', 'text': '经济补偿、加班工资请求仍需以劳动关系、考勤和加班安排证据为基础。'},
            ],
        },
        'disclosure': {
            'label': '披露方案',
            'title': '保留争点结构，删除可反向定位的组合',
            'summary': '本次处理只需呈现主体资格、劳动管理、款项性质和证据缺口，不需要携带唯一案号、完整日期链、营业地点与精确金额。',
            'items': [
                {'label': '可以保留', 'text': '劳动者与经营公司角色、终端销售业务、主体设立先后、管理与结算争议。'},
                {'label': '需要泛化', 'text': '将精确设立日、入驻月份、工作起止日改为相对期间。'},
                {'label': '需要删除', 'text': '唯一案号、具名主体、具体营业厅、精确请求金额及可关联账户线索。'},
                {'label': '原文处理', 'text': '完整原文留在本地，阶段摘要只引用对应证据段落。'},
            ],
        },
        'risk': {
            'label': '边侧判断',
            'title': '当前材料包含可定位案件的组合线索',
            'summary': '唯一案号与公司设立、营业地点、入驻时间和请求金额同时出现，单独替换姓名仍不足以降低关联风险。',
            'items': [
                {'label': '识别到的组合', 'text': '案号 + 地点 + 公司设立时间 + 入驻时间 + 精确请求金额。'},
                {'label': '必要性判断', 'text': '这些精确线索并非判断劳动关系争点结构所必需。'},
                {'label': '阶段结论', 'text': '边侧判断不允许当前候选内容进入后续处理。'},
                {'label': '可继续动作', 'text': '删除或泛化组合线索后重新生成披露方案并再次检验。'},
            ],
        },
        'result': {
            'label': '处理分支',
            'title': '系统判断不能进入外部处理',
            'summary': '本案停留在本地材料与风险判断阶段；未形成批准，也未执行发送。',
            'items': [
                {'label': '材料状态', 'text': '完整 Word 和原文锚点保留在当前案件。'},
                {'label': '当前结果', 'text': '外部处理分支关闭，候选摘要不得继续流转。'},
                {'label': '记录范围', 'text': '仅记录本次材料识别与阶段判断，不代替人工审批。'},
                {'label': '重新进入条件', 'text': '完成最小化改写并重新通过风险检验后，才可创建新的处理请求。'},
            ],
        },
    },
    'la002_human_veto': {
        'facts': {
            'label': '材料事实',
            'title': '店长管理、长期付款与参保记录共同指向关系判断',
            'summary': '原文包含店长岗位、企业管理、按月付款、社会保险补贴及异地参保等材料，同时存在劳动关系起算日不一致。',
            'items': [
                {'label': '岗位与管理', 'text': '劳动者担任店长并从事企业业务，企业提出兼职抗辩。'},
                {'label': '报酬支付', 'text': '法定代表人亲属个人账户长期按月转账，需要结合付款规律和企业关系判断。'},
                {'label': '参保争议', 'text': '社会保险补贴与异地参保记录不能单独决定劳动关系性质。'},
                {'label': '材料冲突', 'text': '一审主文与二审说理采用的关系起算日不同，原文差异必须保留。'},
            ],
        },
        'disclosure': {
            'label': '披露方案',
            'title': '关系要素可以摘要，精确补贴组合与日期冲突交由复核',
            'summary': '候选内容保留岗位、管理、付款周期和证据类型；精确补贴总额、参保时间与起算日差异单独标注。',
            'items': [
                {'label': '可以保留', 'text': '店长角色、企业日常管理、长期按月付款、参保及撤柜等争点类别。'},
                {'label': '需要最小化', 'text': '具名当事人、精确补贴单价与月数、异地参保地点及完整时间链。'},
                {'label': '必须显式保留', 'text': '起算日冲突属于事实不确定性，不能在摘要中自行统一。'},
                {'label': '复核重点', 'text': '判断精确补贴与参保组合是否为当前处理目的所必需。'},
            ],
        },
        'risk': {
            'label': '人工复核',
            'title': '技术检验后仍需人工判断必要性与事实冲突',
            'summary': '材料可进入人工复核，但精确金额、月份、参保时间组合和起算日冲突不能由系统自动放行。',
            'items': [
                {'label': '技术检查', 'text': '已识别精确补贴组合、参保时间与首页具名信息之间的关联可能。'},
                {'label': '事实问题', 'text': '2015年9月1日与2015年9月25日两种起算日表述尚未解决。'},
                {'label': '复核判断', 'text': '人工复核可认定当前候选范围过宽并否决本次请求。'},
                {'label': '处理要求', 'text': '复核人需要说明删减范围、事实前提及本次结论所依据的原文。'},
            ],
        },
        'result': {
            'label': '处理分支',
            'title': '人工复核否决后停止当前请求',
            'summary': '复核人应结合披露必要性与起算日差异作出判断，提交后形成具名复核记录。',
            'items': [
                {'label': '建议结论', 'text': '精确补贴与参保组合非必要，且劳动关系起算日冲突未解决。'},
                {'label': '流转状态', 'text': '否决当前请求后，不进入批准和发送步骤。'},
                {'label': '材料状态', 'text': '完整原文、冲突标注和证据锚点继续保留在本地。'},
                {'label': '重新提交', 'text': '缩减字段并处理起算日差异后，可作为新请求再次提交复核。'},
            ],
        },
    },
    'la003_review_release': {
        'facts': {
            'label': '材料事实',
            'title': '实际管理与履行记录用于判断平台配送劳动关系',
            'summary': '原文围绕站点经营主体、早会排班、请假审批、报酬结算、账号停用和合作协议展开。',
            'items': [
                {'label': '实际管理', 'text': '早会、排班、派单、请假、考核与奖惩记录用于判断支配性劳动管理。'},
                {'label': '报酬与业务', 'text': '平台收入、银行流水和第三方代发需要结合实际经营主体审查。'},
                {'label': '停止工作', 'text': '账号停用和移出工作群用于核对停止工作的过程。'},
                {'label': '书面文件', 'text': '交接、合作和挂靠文件不能脱离实际履行情况单独判断关系性质。'},
            ],
        },
        'disclosure': {
            'label': '披露方案',
            'title': '只保留角色、管理行为、证据类别与处理项目',
            'summary': '候选摘要删除姓名、品牌、站点、案号、精确日期、账户和精确金额，仍能完整表达关系判断所需结构。',
            'items': [
                {'label': '角色信息', 'text': '使用“配送劳动者”“配送经营企业”“第三方结算主体”等角色称谓。'},
                {'label': '核心事实', 'text': '保留排班、请假、考核、报酬结算、账号停用等管理与履行行为。'},
                {'label': '证据类别', 'text': '保留平台记录、沟通记录、银行流水和合作协议等类别，不携带唯一编号。'},
                {'label': '处理项目', 'text': '保留劳动关系、工资差额、未签合同与经济补偿等类别，不披露精确数额。'},
            ],
        },
        'risk': {
            'label': '人工复核',
            'title': '最小化内容可进入人工复核',
            'summary': '当前候选不包含可直接定位个人或站点的唯一组合，但仍需由复核人确认目的、范围和事实前提。',
            'items': [
                {'label': '最小化检查', 'text': '姓名、品牌、站点、案号、精确时间、账户与金额均不进入候选内容。'},
                {'label': '内容完整性', 'text': '关系判断所需的管理行为、业务归属、报酬与证据类别仍被保留。'},
                {'label': '人工责任', 'text': '系统不自动批准；复核人需逐项确认必要性并记录依据。'},
                {'label': '阶段判断', 'text': '完成实际人工复核并允许后，可进入本地处理分支。'},
            ],
        },
        'result': {
            'label': '处理分支',
            'title': '人工复核允许后可生成可回链的本地结果',
            'summary': '结果应保持角色化表达，并能回到原文证据；处理状态以当前任务的复核和审批记录为准。',
            'items': [
                {'label': '允许范围', 'text': '仅处理角色、管理行为、证据类别和裁判项目的最小化摘要。'},
                {'label': '结果要求', 'text': '每个主要判断保留原文锚点，便于返回完整材料核对。'},
                {'label': '过程边界', 'text': '完成实际复核与批准前，不显示为已通过，也不执行真实外发。'},
                {'label': '处理结果', 'text': '完成复核与批准流程后，可查看本地生成结果并返回原文核对。'},
            ],
        },
    },
}


def public_recording_case(case: dict) -> dict:
    """Keep material matching state and stored legacy content on the server."""
    private_fields = {'recording_content_unlocked', 'recording_document_id', 'recording_stage_content'}
    return {key: value for key, value in case.items() if key not in private_fields}


def case_stage_content(case: dict, documents: list[dict]) -> dict:
    """Expose only the matched case's content after its original was imported."""
    if not case.get('recording_content_unlocked'):
        return {}
    original_id = case.get('recording_document_id')
    if not any(document.get('case_id') == case['id']
               and document.get('source_role') == 'recording_original'
               and document.get('status') == 'ready'
               and (not original_id or document['id'] == original_id)
               for document in documents):
        return {}
    return RECORDING_STAGE_CONTENT.get(case.get('scenario'), {})


def build_recording_local_artifact(scenario: str, task_type: str, facts: list[dict], anchors: dict[str, dict]):
    """Build a source-linked local artifact for one supplied recording case."""
    profile = RECORDING_LOCAL_ARTIFACTS.get(scenario, {}).get(task_type)
    if not profile:
        return None
    counts: dict[str, int] = {}
    for block in anchors.values():
        document_id = block.get('document_id')
        counts[document_id] = counts.get(document_id, 0) + 1
    original_document_id = max(counts, key=counts.get) if counts else None
    original_blocks = [block for block in anchors.values()
                       if block.get('document_id') == original_document_id]
    original_ids = {block['id'] for block in original_blocks}

    def row_sources(row):
        result = []
        for terms in row.get('source_terms', []):
            found = next((block for block in original_blocks
                          if all(term in (block.get('text') or '') for term in terms)), None)
            if found and found['id'] not in result:
                result.append(found['id'])
        if result:
            return result
        fields = set(row.get('fields') or [])
        for fact in facts:
            if fields and fact.get('field') not in fields:
                continue
            for source_id in fact.get('source_ids') or []:
                if source_id in original_ids and source_id not in result:
                    result.append(source_id)
                    break
            if result:
                break
        return result

    rows = []
    for index, source in enumerate(profile, 1):
        row = {key: value for key, value in source.items() if key not in {'source_terms', 'fields'}}
        row['id'] = f'{scenario}:{task_type}:{index}'
        row['source_ids'] = row_sources(source)
        if task_type == 'issue_extraction':
            fields = set(source.get('fields') or [])
            row['fact_ids'] = [fact['id'] for fact in facts if fact.get('field') in fields]
        rows.append(row)
    key = {'timeline': 'events', 'evidence_inventory': 'items', 'issue_extraction': 'issues'}[task_type]
    return {key: rows}


def attach_recording_material(repo, case, data: bytes, filename: str, root: Path):
    """Keep the selected Word locally and anchor prepared facts to its full text."""
    from .parsing import parse
    from .util import restrict_mode, uid

    ident = uid('doc')
    path = root / 'files' / (ident + '.docx')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    restrict_mode(path, 0o600)
    try:
        ir = parse(path, ident, ocr_provider=None)
        if not ir['blocks']:
            raise ValueError('Word 未包含可显示的正文')
        document = {'id': ident, 'case_id': case['id'], 'name': Path(filename).name[:200],
                    'extension': '.docx', 'path': path.name, 'version': 1, 'status': 'ready',
                    'source_role': 'recording_original', 'ir': ir}
        repo.put('document', document, case['id'])
        repo.put('document_version', {'id': f'{ident}:v1', 'ir': ir}, case['id'])
        # Ignore the added application page when locating source-case evidence.
        original = ir['blocks']
        for index, block in enumerate(original):
            if block['text'].strip() == '原始案件文书及标注':
                original = original[index + 1:]
                break
        def normalized(text):
            return re.sub(r'[\s,，]', '', text)
        facts = repo.list('fact', case['id'])
        terms = SOURCE_TERMS.get(case['scenario'], [])
        seed = SCENARIOS[case['scenario']]
        for fact in facts:
            index = next((i for i, row in enumerate(seed['facts'])
                          if row[0] == fact['field'] and row[1] == fact['value']), None)
            queries = terms[index] if index is not None and index < len(terms) else []
            anchors = []
            for query in queries:
                found = next((b for b in original if normalized(query) in normalized(b['text'])), None)
                if found and found['id'] not in anchors:
                    anchors.append(found['id'])
            # Retain the scope/annotation anchor as well as original evidence.
            fact['source_ids'] = anchors + fact['source_ids']
            fact['origin'] = 'recording_annotation'
            repo.put('fact', fact, case['id'])
        stage_content = RECORDING_STAGE_CONTENT.get(case['scenario'])
        if stage_content is not None:
            case['recording_content_unlocked'] = True
            case['recording_document_id'] = ident
            repo.put('case', case)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise
