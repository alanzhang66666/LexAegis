# 文档索引

现行说明只保留下列入口。历史计划与共识在 [archive/](archive/README.md)，不再作为规格。

| 文档 | 用途 |
| --- | --- |
| [PROJECT_MAP.md](PROJECT_MAP.md) | 现行入口地图：下一步、运行时、代码与门禁 |
| [../AGENTS.md](../AGENTS.md) | Agent 边界：怎么跑、禁写口径、当前状态。不是规格 |
| [../README.md](../README.md) | 产品架构书（中文）：设计动机、信任边界、领域模型、门禁、状态机、证据链、威胁模型与现状边界 |
| [proposalv1.0.md](proposalv1.0.md) | 理想运行状态提案。不是当前验收，不是发送授权 |
| [../README_EN.md](../README_EN.md) | Product architecture book in English (chapter-for-chapter with ../README.md) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 字段级工程详本：模块、契约字段、状态机、API、限额、红队/实验附录 |
| [DEPLOY.md](DEPLOY.md) | 数据目录、备份恢复、Compose 隔离 |
| [DUAL_TRACK_DEPLOY.md](DUAL_TRACK_DEPLOY.md) | 三种运行环境、Windows 维护与隔离目录 |
| [DUAL_TRACK_ACCEPTANCE.md](DUAL_TRACK_ACCEPTANCE.md) | 人工否决录制路径、正式单次放行与交付验收边界 |
| [legal/PRODUCT_RULE_PREPARATION.md](legal/PRODUCT_RULE_PREPARATION.md) | 常规产品规则草稿、导入报告及法源待复核边界 |
| [MODELS.md](MODELS.md) | 边侧小模型、云端双槽、OCR 与本机转写 |
| [../data/README.md](../data/README.md) | 仓库评测语料、合成门禁与 dataset CLI |
| [VALIDATION.md](VALIDATION.md) | 实际跑过的验证与未决项 |
| [LOCAL_STATUS.md](LOCAL_STATUS.md) | 本机盘点；2026-09-12 现状以文首为准。不是规格，不替代 VALIDATION |
| [项目现状完整说明-2026-09-14.md](项目现状完整说明-2026-09-14.md) | 可单独带走的现状稿：十案、十门、已落地与缺口。不是发送授权 |
| [功能展示说明材料/](功能展示说明材料/README.md) | 比赛第 4 项成稿：正文、14 张图、截图来源。不是发送授权，不是规格 |
| [PROVENANCE.md](PROVENANCE.md) | 来源、许可、合成数据边界 |
| [DESIGN.md](DESIGN.md) | 界面 Token 与信息原则 |
| [legal/README.md](legal/README.md) | 法学现行入口：规则正文、审核、一对一、攻击实跑 |
| [../legal/](../legal/) | 法源对照表与标注示范模板；不是规格，也不是评测主库 |
| [V2_2_ALIGNMENT.md](V2_2_ALIGNMENT.md) | V2.2 目标架构对齐：差距分析与分阶段计划。目标不是现状，不是规格，不是发送授权 |
| [DOMAIN_ONBOARDING.md](DOMAIN_ONBOARDING.md) | 新案由接入流程：写包 → 生命周期 → manifest → 验收套件 → 部署 → Support Registry 激活 |

## 原根目录文件归位对照

根目录中文跳转文件已于 2026-09-21 移除。若外部仍引用旧路径，按本对照取正文：

| 原根目录文件 | 正文位置 |
| --- | --- |
| `PLAN.md` | [archive/PLAN-0.2.md](archive/PLAN-0.2.md) |
| `案隐盾_项目核心共识与系统架构.md` | [archive/CONSENSUS-2026-09-04.md](archive/CONSENSUS-2026-09-04.md) |
| `案隐盾_系统法学规则与验收标准_v1.0.md` | [legal/案隐盾_系统法学规则与验收标准_v1.0.md](legal/案隐盾_系统法学规则与验收标准_v1.0.md) |
| `案隐盾_内部测试法学审核提交_AI法学成员_2026-09-12.md` | [legal/LEX-LG-AI-2026-09-12-01.md](legal/LEX-LG-AI-2026-09-12-01.md)（登记见同目录 -登记.md） |
| `案隐盾_十案上云路径设计_v0.1_2026-09-14.md` | [legal/案隐盾_十案上云路径设计_v0.1_2026-09-14.md](legal/案隐盾_十案上云路径设计_v0.1_2026-09-14.md)；不是发送授权 |
| `案隐盾_法律标注工作簿_v0.1.md` | `../legal/templates/案隐盾_法律标注工作簿_v0.1.xlsx` |
| `案隐盾_法律标注指南_v0.1.md` | `../legal/templates/案隐盾_法律标注指南_v0.1.docx` |
| `LA001_D_外发交付包_20260914.md` | 交付包在 `.data/outbound_packets/LA001_D_外发交付包_20260914/`；不是发送授权 |
| `功能展示说明材料.md` | [功能展示说明材料/README.md](功能展示说明材料/README.md) |
| `人工审批页面说明.docx` | [legal/人工审批页面说明_设计稿.docx](legal/人工审批页面说明_设计稿.docx)（字节级同件） |
| `系统说明书部分.docx` | [系统说明书-法律规则与人工复核-2026-09-18.docx](系统说明书-法律规则与人工复核-2026-09-18.docx)（字节级同件） |
| `总法源目录（补充版）.xlsx` | `../legal/sources/总法源目录_v0.2.xlsx`（字节级同件） |
| `硬性禁止、人工复核情形及冲突处理回答（修订版）.docx` | `../legal/sources/硬性禁止、人工复核情形及冲突处理回答_v0.2.docx`（字节级同件） |
| `第4项-V1.0完整修改建议与技术资料补交清单.docx`、`第4项-功能展示与说明材料_V1.0修订底稿R1.docx` | [功能展示说明材料/drafts/](功能展示说明材料/drafts/) |
| `LexAegis_系统架构设计书_V2.2_KubeEdge_多案由可扩展平台.md` | [LexAegis_系统架构设计书_V2.2_KubeEdge_多案由可扩展平台.md](LexAegis_系统架构设计书_V2.2_KubeEdge_多案由可扩展平台.md)；对齐状态见 [V2_2_ALIGNMENT.md](V2_2_ALIGNMENT.md) |

## Stub 路径（docs 内）

下列文件只跳转到归档，不当现行规格：

| 路径 | 指向 |
| --- | --- |
| [PLAN_STATUS.md](PLAN_STATUS.md) | 对照表已归档；现行验证见 VALIDATION |
| [IMPLEMENTATION_V2.md](IMPLEMENTATION_V2.md) | 实施说明已归档；现行见 ARCHITECTURE |
| [THIRD_PARTY.md](THIRD_PARTY.md) | 第三方台账已归档；现行见 PROVENANCE |
