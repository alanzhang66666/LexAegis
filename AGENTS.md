# LexAegis · 案隐盾

本地优先的法律披露工作台：边侧整理原文与身份映射，法学复核与门禁满足后由审批人批准完整请求，独立网关调云，结果回边侧校核。版本 **V1.0**（`1.0.0`）。正式外发失败关闭。非正式发行。

## 怎么跑

`python -m pip install -e ".[test]"` → `cd frontend && pnpm install --frozen-lockfile && pnpm build` → 回仓库根目录运行 `lexaegis start --profile demo`。演示工作台 **http://127.0.0.1:48765**；`production` 为 38765、`integration` 为 58765（以实际启动输出为准）。演示只接受内置合成材料。口令看终端。

## 技术栈

Python 3.12+ / FastAPI / SQLAlchemy；前端 React + Vite（`frontend/`）；隔离用 Compose。密钥只进网关。

## 目录与约定

根目录只留代码与构建文件；中文文档已归入 docs/legal/archive，旧路径对照见 `docs/README.md`「原根目录文件归位对照」。东西放哪：

| 找什么 | 去哪 |
| --- | --- |
| 规格 / 怎么跑 | `docs/PROJECT_MAP.md`；三角：ARCHITECTURE + VALIDATION + PROVENANCE |
| 法学现行 5 读、法计交接空表 | `docs/legal/README.md` |
| 法源表、标注 xlsx/docx | `legal/sources/`、`legal/templates/` |
| 代码 / 测试 / 包 | `lexaegis/`、`tests/`、`packs/`（无一 published） |
| 运行库、真案、交付包 | `.data/`（不入库）。交付包：`.data/outbound_packets/` |
| 比赛交付物 / 截图 / 案例包 | `deliverables/`（不入库）；`build_submission.py` 默认输出 |

改 `frontend/src` 先读 `.cursor/skills/lexaegis-workbench-ui`。仓库首案包 `2.0.0-draft.3` 与产品包 `3.0.0-product-draft.1` 均为草稿，`dispatch_allowed=false`。本轮三环境、人审否决与常规逐请求放行见 `docs/DUAL_TRACK_ACCEPTANCE.md`；真实验收仍须真实证据，代码测试不代填通过。

## 当前状态（2026-09-19）

**既有 10 案层 A 评估完成，0 案真实发送。** D 路径走一遍 = evaluate，不是 HTTP 发送。首案验收策略仍限 LA-001，须「本次可用」签署及十门全过。常规生产支持规则适用范围内的逐请求策略，每案每次请求独立核验、批准和消费许可，不继承首案授权；原九案未取得真实发送验收。分词 ≠ 匿名。Compose 五项探测 ≠ 本请求隔离收据，native 不能自证隔离。

不要：发明合同/审批人；把口述当服务商 `reviewed`；发布仓库 pack；削弱 `validate_formal_gate` / `authorize_dispatch`；另编第二套门禁编号（执法只走 `outbound_gate` G 表）；把 409 当产品 bug；把工程攻击当法学 `resisted`；写「10 案已通过」或「外发已开通」。

## V2.2 对齐层（2026-09-24 追加）

P1–P8 已按 `docs/V2_2_ALIGNMENT.md` 落地为绿地并行层：`domain_runtime`（绑定/快照/上下文/TaskStep/云信封）、`domain_packages`（八类包 + manifest + 签名/撤销）、`support_registry`（可加载≠已支持）、`capability_registry`+`spi`、`orchestrator`（双写，权威开关默认关）、`return_pipeline`（九阶段 + waiting-cloud）、`acceptance_suite`（19 基线）、`deploy/k8s`（未验证）。消费侧仍读单体 pack；门禁/审批/发布链语义零改动。

## 下一步

完成代码与合成流程回归后，仍须补齐真实构建、十门收据及目标环境证据，再批准 **一次** 哈希绑定的首案 D 发送。一案成功不扩到十案；常规生产后续请求也须分别取得完整授权。
