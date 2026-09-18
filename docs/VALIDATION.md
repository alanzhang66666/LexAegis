# V1.0 工程验证记录

产品版本现为 **V1.0**（`1.0.0`），非正式发行。下文 2026-09-08/09 条目仍是 0.2.0 周期的本机证据，未因改号重跑。

验证日期：2026-09-08。当前验证设备为 Windows / AMD64、Python 3.13、Docker Compose v5.5.0 / Engine 29.7.2。本文只记录实际执行证据；不填充隐私风险降低率、法律任务准确率或摘要质量等未经盲测的数据。

## 本机已执行验证

| 验证项 | 实际结果 |
| --- | --- |
| `python -m pytest -q` | 2026-09-14 本机 **283 项通过、3 项跳过**（工作树含 `d_path`）。此前 2026-09-09 记录为 216 过 / 1 跳过 |
| `lexaegis dataset validate` | `ok=true`；catalog 仅 `mock_labor` 1.0.0，`dispatch_allowed=false`。本机 `.data/semi_labor_v1` 脚手架存在且契约通过（`legal_annotation_status=pending`，`dispatch_allowed=false`），未写入 `data/catalog.json`，无 `data/semi_labor_v1` |
| TypeScript 类型检查与 Vite 生产构建 | 2026-09-08 三色系本轮：`pnpm exec tsc --noEmit` 通过；`pnpm build` 通过，1588 个模块 |
| 远端 CI | 未取得 / 本轮不跑 |
| Python wheel 构建与归档检查 | 通过；`lexaegis-0.2.0-py3-none-any.whl` 含编译前端、内置案由包、`NOTICE` 和许可证 |
| `lexaegis bench --profile ianvs-pipl`（无输入） | `status=input_required`，`production_dispatch=false`，未造伪向量 |
| `lexaegis dataset compare`（`mock_labor` 8 条） | 五组均写出对照产物；身份 top-1/top-k 与确定性效用代理含分子/分母/失败类；`legal_availability=not_scored`，`privacy_reduction_rate=not_scored`，AURA/人工成本/`interval_estimate=not_applicable`；`production_dispatch=false`。8 条冒烟，不宣布方法胜出 |
| 桌面浏览器完整流程 | 2026-09-08 三色系本轮 `desktop-1280` 6 项通过（`--grep-invert five-viewport`，含复原空态 / 回写待办）；Playwright 复用已有 18765/18766，不抢 8765，未杀边侧 8080 |
| 三色系六态手工 | 2026-09-08 在 `127.0.0.1:18765` 登录页与案件列表点击「配色」林绿/墨青/缃褐与深浅钮。计算样式确认 `data-palette`/`data-theme` 与 Token（林绿 `#225b48`/`#f6f4ee`，墨青 `#2f4f6d`/`#eef1f5`，缃褐 `#8a5a32`/`#f6f1e8`；成功色保持绿色、未并入品牌）。截图可读，侧栏深底浅字。另开演示案事实页（墨青深）与披露页（缃褐浅）。默认仍是林绿浅。未跑五视口 |
| 响应式浏览器矩阵 | 本轮未跑 `five-viewport` |
| 工作台「本地生成争点候选」 | 已点击。native `8765` 健康检查 200，但 `.env` 口令对已有 admin 返回 401，未在 8765 上点按钮。另启隔离栈 `127.0.0.1:28765`（口令与 Playwright 验收相同）打开演示案「01 完整披露流程」：按钮可见可点；界面出现「本地争点候选已生成，未发生外发。」与「按字段分组的候选 · 非法学结论 · 未调用模型」。随后 API 读到 `type=issue_extraction`、`transport=local`、`status=complete`、`provenance=local_deterministic`，6 个字段桶（`labor_relation` / `remuneration` / `disputed_event` / `timing` / `evidence` / `parties`），均有 `source_ids`。未主张云端或边侧外发 |
| MiniCPM5-2B `dataset probe-edge`（`mock_labor` 8 条） | 工程五项均为 8/8：`json_valid`、`source_ids_in_blocks`、`quote_is_substring`、`numbers_from_source`、`aliases_no_conflict`。`legal_availability=not_scored`。报告在被忽略的 `.data/edge-probe/` |
| native `doctor`（dotenv 注入） | `ok=true`；`isolation=unconfigured`（说明项，不失败关闭）；可选 `ocr=available`（冒烟/资产声明，不是识别率）。本轮验收 `edge_json=failed`（可选，不失败关闭） |
| native 工作台 8765 | 演示案 mock 发送完成（`provenance=simulation`）。正式合成 TXT 解析成功；MiniCPM 工作台抽取正式案作业完成，8 条合法枚举 `field`，无竖线 `field`（契约冒烟，无法学分）。空扫描确认本块 409。人工录入事实后尝试真云：审批/发送 409 |
| 本机 PaddleOCR 合成扫描冒烟 | CPU `paddlepaddle` 3.3.1 + `paddleocr` 3.7.0（非 GPU）。用户缓存已有 `PP-OCRv6_medium_det` 与 `PP-OCRv6_medium_rec`。`examples/synthetic_scan.pdf` 解析得 3 块 `kind=ocr`（含 bbox，`needs_review=true`）。`test_live_paddleocr_scan_smoke` 通过。无识别率结论 |
| Compose 隔离探测 | `check-isolation` 五项探测全部为 true；`isolation_verified=true` 于 2026-09-08T09:39:34Z 写入隔离 API 卷。运行态探测不能替代宿主机防火墙与镜像供应链审计 |
| Compose 正式合成真云 | 隔离阻断消失；其余门禁仍在；`formal_dispatch=blocked`。E1：`docker compose port api 8765` 在宿主机 28765 与 38765 recreate 后输出恰好为 `invalid IP:0`。容器内 `http://127.0.0.1:8765/api/v1/health` 为 200。宿主机 38765/28765/8765 未连通。能力面板已拆开 `host_publish` 与 isolation。**本轮跳过 Compose 登录页**（宿主机未发布），不主张浏览器可达隔离 |
| 2026-09-10 本机隔离试点 | Compose `docker compose port api 8765`=`127.0.0.1:38765`；`check-isolation` 五项通过并写入隔离卷；10 案迁入后云端 evaluate 仍 409（四类攻击 `uncertain`，未改成 resisted）；隔离库试点包 `2.0.0-pilot.1` 已 publish，仓库 `packs/labor_v2_draft.json` 仍为 draft。`formal_dispatch=blocked`，非正式外发开通。 |
| 2026-09-12 隔离栈攻击实跑 | Compose 五项仍为真（隔离卷）。工程基线：阳性对照 `identity=succeeded`；空辅助四类 `uncertain`；合成正式案 token 线 uncertain / succeeded / succeeded / uncertain。**不是**四类 resisted。0 案发送。见 [legal/隔离栈攻击实跑-2026-09-12.md](legal/隔离栈攻击实跑-2026-09-12.md) |
| Unicode 路径、跨进程文件锁与进程退出 | 自动化测试通过 |
| DOCX、文本/扫描 PDF、PNG/JPEG 与 OCR Provider 契约 | 自动化测试通过 |
| 材料版本、历史锚点、事实失效和任务期间材料变化 | 自动化测试通过 |
| 边侧提取 URL、JSON、字段、来源和数量边界 | 自动化测试通过 |
| 稳定 token 冲突、破损 token、未知 token 与双轨导出 | 自动化测试通过 |
| 案由包哈希、生命周期、版本不可覆盖和保守缺省 | 自动化测试通过 |
| 通用任务引擎与本地确定性时间线 | 自动化测试通过 |
| 服务商、角色、具名审批、请求哈希和累计披露失效 | 自动化测试通过 |
| 网关 HMAC、幂等、结果不明和禁止盲目重发 | 自动化测试通过 |
| 四类冻结攻击状态与正式门禁 | 自动化测试通过。当前执行器是工程基线：空辅助不得四类 `resisted`；已知泄漏的合成阳性对照必须 `identity=succeeded`。这不是正式攻击结论，也不能作为法学背书。`validate_formal_gate` 仍失败关闭，仅四类 `resisted` 消除红队阻断 |
| 发送控制 7 组回归探针 | 自动化测试覆盖：未审核备用不进批准目标；主方收包后首字节超时不切备；空辅助不得四类 `resisted`；入队后规则退役拒发；空 IR 待解析不崩且阻断外发；能力面板区分未验证 / 可能披露 / 工程基线。正式外发仍失败关闭 |
| DP clipping/RDP、JL/PCA/随机投影和真实 MIA 输入约束 | 自动化测试通过 |
| 合成数据生成、冻结、四组文本对照和 Ianvs 补充组 | 自动化测试通过 |
| 迁移前备份、完整性验证、失败回滚和恢复 | 自动化测试通过 |
| 网络文件系统 SQLite 路径拒绝 | 自动化测试通过 |

浏览器流程只使用仓库内的固定合成材料，覆盖披露、审批、模拟发送、逐项原文校核、最终确认、风险阻断、正式材料人工流程和运行配置。运行数据与截图保存在被忽略的本机目录中，不提交数据库、密钥或案件材料。

### native 正式真云阻断（2026-09-08）

人工事实 + `transport=cloud` 评估后 `approval_allowed=false`，批准与发送均为 409。blocker：

- 存在尚未解决的字段复核事项
- 没有可发送的事实
- 适用规则尚未正式发布
- 适用的 V2 法学规则包尚未冻结并正式发布
- 服务商处理条件或影响评估不完整
- 四类冻结攻击未全部达到 resisted
- 隔离部署自检未通过
- 五类风险信号权重尚未冻结

### Compose 正式真云阻断（2026-09-08）

`isolation.status=available`，`isolation_verified=true`，**不再出现**「隔离部署自检未通过」。其余仍阻断；Compose 默认未写入云端模型，另有「云端服务或模型未配置」。未发布案由包，无真实云端成功外发。

## 已实现但仍需目标环境验证

- 边侧 OpenAI-compatible 提取契约已实现。现行权重为 MiniCPM5-2B Q4_K_M（`edge-small`）。`probe-edge` 工程五项 8/8；工作台抽取正式案作业完成，8 条合法枚举 `field`，无竖线 `field`（契约冒烟，无法学分）。没有系统质量、共指准确率或盲测结论。
- PaddleOCR 3.x 本地适配器、坐标和失败关闭路径已测试。本机已对 `examples/synthetic_scan.pdf` 做过 CPU 合成扫描冒烟（3 块 `kind=ocr`），**没有识别精度或硬件兼容性结论**。RapidOCR / whisper.cpp 以假 provider 与失败关闭路径覆盖；有权重才跑的本机冒烟在 CI 与未声明资产的环境跳过，不写识别率或转写准确率，也不表示本机已安装。
- 云端网关及双槽适配器已用测试替身验证。本机可配置 DeepSeek / 百炼密钥；正式合成案已点真云但门禁关闭，**没有真实外发成功记录**。
- GitHub Actions 已定义 Windows、macOS、Linux、浏览器五视口以及 `linux/amd64`、`linux/arm64` 镜像检查；本记录不把尚未取得的远端运行结果写成已通过。
- Compose 隔离探测已在本机通过并写入容器库（`isolation_verified=true`，2026-09-08T09:39:34Z）。E1 在 28765 与 38765 recreate 后 `docker compose port api 8765` 仍为 `invalid IP:0`；宿主机 38765/28765/8765 未连通。本轮未打开 Compose 登录页，不主张浏览器可达隔离。`host_publish` 与 isolation 已分层；`formal_dispatch=blocked`。`capabilities.validation.detail` 在 `isolation.status=available` 时写「隔离部署已记录」，云端外发与正式案件仍为「仍未验收」。

以上项目是外部运行环境验证缺口，不是以模拟结果代替真实结果。系统继续把未取得验证证据的能力显示为“未验证”或“阻断”。

## 当前合成数据范围

`lexaegis dataset generate-mock` 生成 8 份完全合成的劳动争议记录，固定为 6:2 开发/盲测划分。`freeze` 冻结数据、模板、依赖和随机种子哈希；`run` 生成原文、查找替换、一致假名化、任务驱动最小披露四组文本对照，以及独立的 Ianvs 向量补充组。`dataset compare` / `bench --profile comparable` 在同一攻击预算下另跑五组方法离线对照（查找替换、一致假名化、任务矩阵、通用 generalize 薄基线、Phase 2 法律约束候选），攻击器与评分器分开，开发/盲测分开汇总。

这些数据不来自真实案件，只验证管线可复现性。8 条是冒烟规模，不是代表性保证。法律可用性、隐私降低率、AURA、人工耗时、正式四类攻击效果和 MIA 效果均明确记为 `not_scored` / `not_applicable` 或待标注，不生成伪造分数，也不宣布方法胜出。仓库内红队执行器只证明工程基线可复现，不构成正式攻击结论或法学背书。标注与盲审完成前，对照结果不得写成正式实验结论。

## 对照原 PLAN 的未决项

工程里程碑 M0–M6 在当前约定范围内已落代码（详见 [归档对照表](archive/PLAN_STATUS-2026-09-05.md)）。下列事项**不得**写成工程已完成：

| 类别 | 内容 |
| --- | --- |
| 法学待定 | 正式法源与必要性矩阵、服务商合同与影响评估、正式攻击者模型与阈值、双人标注与试点授权 |
| 外部待验证 | GitHub Actions 三平台/双架构的远端实际结果；PaddleOCR 仅本机合成扫描冒烟、无精度；经审核云端服务商的真实外发成功记录 |

在以上证据补齐之前，`/capabilities` 和正式门禁继续区分技术实现、运行配置、实际验证与法学发布。

## 有意保留的外发阻断

发送控制已按槽位分档审核、逐次 Attempt 与发送时重验实现；能力面板区分未验证 / 可能披露 / 工程基线，正式外发保持失败关闭。法学案由规则与法源尚未定稿、服务商材料和影响评估未审核、正式攻击阈值未冻结、真实材料未获组织授权时，正式外发保持关闭。本机 Compose 隔离探测通过**不能**替代上述法学条件。技术实现状态不得替代法律审核或合规结论。

## 复现命令

```powershell
python -m pytest -q
python -m lexaegis.cli dataset validate
python -m lexaegis.cli dataset compare --output .data/comparable/mock_labor.json
cd frontend
pnpm exec tsc --noEmit
pnpm build
pnpm test:e2e -- --project=desktop-1280 --grep-invert "five-viewport"
pnpm test:e2e -- --grep "five-viewport"
# 需 dotenv：doctor / probe-edge 自己不读 .env
# docker compose --profile redteam --profile benchmark up -d --build --wait
# lexaegis check-isolation
```

浏览器测试配置会自行启动使用独立验收目录的应用，不访问真实边侧模型或云端模型。
