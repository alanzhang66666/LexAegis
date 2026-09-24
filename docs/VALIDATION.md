# V1.0 工程验证记录

产品版本现为 **V1.0**（`1.0.0`），非正式发行。下文 2026-09-08/09 条目仍是 0.2.0 周期的本机证据，未因改号重跑。

## 2026-09-24 V2.2 CloudResultEnvelope / HumanDecision / 网关角色标志验证

| 项 | 结果 |
| --- | --- |
| `tests/test_result_envelope.py` | **5 项通过**：complete 回包写 `pending_human` 信封（provenance/result_hash/request_hash/case 绑定正确）；schema 拒绝回包写 `rejected`+`invalid_cloud_result` 且 result_hash 绑定回包字节；unknown/无结果不写信封；`/tasks/{id}/confirm` 落 `human_decision`（adopted+actor+artifact_hash+request_hash）且审计带 `human_decision_id`；`LEX_GATEWAY_ROLE` 三态断言（edge 持凭据拒启动 / edge 无凭据可起 / cloud 无凭据拒启动 / unified 兼容） |
| 契约 | `contracts.py` 增 `CloudResultEnvelope`（云回包边侧收据：candidate→pending_human→human adopted 链路）与 `HumanDecision`（具名采纳记录），对齐设计书 §34.3 固化名录——该名录 14 项 schema 至此全部有契约或聚合 |
| 记录面 | `return_pipeline.execute` 成功落 pending_human；`finish_response` ValueError 分支落 rejected；`send.*` 审计补 `result_hash`；`artifact.confirmed` 审计补 `human_decision_id`；只读端点 `/tasks/{id}/cloud-result-envelopes`、`/tasks/{id}/human-decisions` |
| 网关角色 | `LEX_GATEWAY_ROLE`（unified 默认/edge/cloud）启动期断言：edge 禁持云凭据（云域 CGW 唯一持凭据）、cloud 必须持凭据；`/health` 回 `gateway_role`。**claim/queue 跨角色拆分未做**——同进程双角色仍是当前拓扑 |
| Python 全量测试 | `pytest -q`：**661 passed、5 skipped、1 warning** |
| 边界 | CloudResultEnvelope 是边侧收据，不代表回包已被人工采纳；信封不携带 provider_request_id（provider 账本未暴露该字段）；角色标志只管凭据不变量，不拆分调度语义 |

## 2026-09-24 V2.2 orchestrator 权威化 / 包下发控制面 / domain_mapper 真语义验证

| 项 | 结果 |
| --- | --- |
| `tests/test_orchestrator.py` | **12 项通过**：VALIDATION/CLOUD 步骤不污染 `derive_status`；authority 模式下决策入口（authorize_dispatch）对漂移任务 409 `orchestrator_inconsistent`；authority 下 approve→enqueue 正常流程一致 |
| `tests/test_package_controller.py` | **11 项通过**：注册/分配/投递/verified→activated 正路径；未注册节点/draft manifest/错节点/错哈希/错序回执全拒；撤销等 `revoked` 回执才终态；失败回执重试至上限后 failed；reconcile 分桶；`edge_apply`/`edge_revoke` 边侧往返 |
| `tests/test_domain_mapper.py` | **11 项通过**：field_map/value_map/defaults/required_fields 引擎单测；labor cause_pack mapper 真执行（claims 获 `domain` 字段 + artifact 记包 id/content_hash）；`applies_to` 不匹配/无快照/demo V1 无 manifest 分别 skipped/skipped/unbound；必填缺失 → `invalid_cloud_result` fail-closed |
| 收敛点 | `service`/`worker`/`review`/`upgrade`/`runtime_pack`/`support_registry`/`domain_packages` 的全部任务状态写点走 `orchestrator.transition_task`；`authorize_dispatch` 与 `finish_response` 入口接 `assert_consistent`；`recover` 对漂移任务 fail-closed 且不阻塞其他 job 恢复 |
| 语义修正 | 包撤销/支持暂停传播原先只置 stale 标志却记 `to_status="stale"` 步骤（自相矛盾），现真正置 `status="stale"`，与 touch_case/upgrade/runtime_pack 三条既有 stale 路径一致 |
| 测试修正 | `test_restart_recovers_inflight_send_as_unknown` 原以裸写模拟崩溃现场——真实代码中 step 与 task 同事务原子提交，该状态不可达；改为走漏斗写 `sending` 模拟真实可达崩溃态 |
| Python 全量测试 | `pytest -q`：**656 passed、5 skipped、1 warning**；`LEX_ORCHESTRATOR_AUTHORITY=1 pytest -q`：**656 passed、5 skipped**——权威开关下全绿 |
| 边界 | authority 开关仍默认关，转默认需真实环境观察期；控制器是记录层控制面，本地 kind+KubeEdge 下发/断连/撤包演练已过（`deploy/k8s/DRILL_EVIDENCE.md`），生产集群未验证；mapper 为声明式数据配置，不虚构法律语义 |

## 2026-09-24 本地 kind+KubeEdge 下发/断连/撤包演练

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| 集群 | kind `lexaegis-v22`（k8s v1.37.0，Docker Desktop WSL2）+ cloudcore v1.20.0 + edgecore v1.30.7-kubeedge-v1.20.0（`edge-1`，containerd native snapshotter + CNI host-local/loopback/portmap/ptp），节点 Ready |
| 下发 | assignment-1（`dpm:labor:2.0.0-draft.3`）deliver→边侧 `edge_apply`→verified→activated 回执入控制面 |
| 断连 | `docker network disconnect` 切 CloudHub↔EdgeHub：edge-1 Ready=Unknown（lease 过期）；边应用自治 health=200、已导入 manifest 保留 |
| 断连期下发 | assignment-2（`3.0.0-product-draft.1`）控制面 delivered，bundle 装 ConfigMap——边侧文件系统验证 **absent**（通道物理不通，非应用层模拟） |
| 重连 | edge-1 Ready=True；ConfigMap 经 CloudHub→EdgeHub→MetaManager→edged 卷同步真实到达 `/var/lib/kubelet/pods/*/volumes/.../bundle/bundle.json`；`edge_apply` 导入并回执 verified+activated |
| 撤包 | assignment-1 revoke→边侧 `edge_revoke`→revoked 回执→assignment 终态 `revoked`；边库实测 `2.0.0-draft.3 → revoked` |
| 对账 | `reconcile` 终态 ok=2 / retry=0 / awaiting=0 / failed=0 |
| 边界 | 单机演练非生产集群；assignment-1 传输走 docker cp（宿主层），assignment-2 走真实 KubeEdge ConfigMap 同步；边应用为容器内进程非 KubeEdge pod；manifest 均为草稿不代表法学发布；未覆盖 `waiting-cloud` 返回管道语义（另有独立测试） |

脚本 `scripts/kubeedge_local_drill.py`，证据 `deploy/k8s/DRILL_EVIDENCE.md`。

## 2026-09-24 V2.2 包下发 bundle 与审计字段回填验证

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| `tests/test_package_bundle.py` | **6 项通过**：导出含 manifest+全部引用包+bundle_hash；无签名导入一律降 `draft`；签名往返保留 `signed`；篡改内容/`platform_api` 不符 fail-closed；端点 admin 强制 |
| audit 扩展字段 | `task.created`/`risk.evaluated`/`request.approved`/`send.reserved`/worker `send.*` 回填 `cause_id`/`domain_runtime_snapshot_id`/`capability_id`/`edge_node_id`；`edge_node_id` 由 `LEX_EDGE_NODE_ID` 注入，native 为空不造假 |
| 边界 | bundle 通道是代码层落地，不等于集群下发已演练；`published` 状态不导入（发布是本地独立取证决定） |
| Python 全量测试 | `pytest -q`：**631 passed、5 skipped、1 warning**（约 157 秒） |

## 2026-09-24 V2.2 编排器/云信封/能力注册/SPI/返回管道/KubeEdge manifests/验收套件（P4–P8）落地验证

本轮设备为 Windows / AMD64，Python 3.13（仓库 `.venv`）。按 `docs/V2_2_ALIGNMENT.md` P4–P8 落地，不改门禁、审批、发布链语义。

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| P4 `tests/test_orchestrator.py` | **9 项通过**：快照绑定任务建 `CloudTaskEnvelope`（case_ref 不透明）、信封入 `cloud_task_envelope` 聚合与 request 依赖、网关缺信封/信封不一致拒绝、orchestrator 双写 `from_status` 真实、`LEX_ORCHESTRATOR_AUTHORITY` 开关、`invalid_cloud_result`/`failed_before_send` 故障码落 task |
| P5 `tests/test_capability_registry.py` | **6 项通过**：种子注册 4+ 能力、task 记 `capability_id`+`capability_binding_id`、disabled 能力建任务 409、未注册 task_type 仍 409、binding `provider_profile` 悬空 409、SPI 只读面（content 不可写、非包记录拒绝附着） |
| P6 `tests/test_return_pipeline.py` | **5 项通过**：九阶段管道逐步落 `return:*` task_step、mock→simulation/local→local_deterministic/cloud→cloud 严格映射（未知 transport 拒绝）、`ConnectError`→`waiting-cloud` 挂起+`not_before` 退避不推进不伪造、`ReadTimeout` 仍 `unknown` 不重发、信封 request_hash 篡改→`invalid_cloud_result`+`return:envelope:failed` |
| P8 `tests/test_acceptance_suite.py` | **3 项通过**：种子 labor 10 项 `package_asserted` 全过、8 项 `test_mapped` 带 `covered_by` 映射、G10 `manual_gate` 永不自动标过、包漂移 fail-closed、空包集非空洞为真 |
| P7 `deploy/k8s/` | manifests 8 文件按 compose 拓扑映射（边域 api/worker 钉 `lexaegis.io/domain: edge`、云域 CGW 唯一持凭据出网、NetworkPolicy 复刻隔离）；`docs/DEPLOY.md` 增 KubeEdge 章节。**未在真实集群验证** |
| Python 全量测试 | `pytest -q`：625 passed、5 skipped（P4–P8 时点）；含 bundle 与审计回填后为 **631 passed、5 skipped**（见上一节） |

边界如实声明：① `domain_mapper` 阶段目前是只读 SPI 挂接钩子（attached/unbound/skipped），不改行为；② orchestrator 权威开关默认关，TaskStep 双写不接管状态机；③ KubeEdge manifests 未经集群演练，不宣称部署通过；④ 验收套件的 `test_mapped`/`manual_gate` 基线不在进程内执行，不替代真实验收；⑤ `product_dispatch_state()` 恒 blocked、G 门与 `dispatch_allowed` 零改动。

## 2026-09-24 V2.2 Support Registry（P3）落地验证

本轮设备为 Windows / AMD64，Python 3.13（仓库 `.venv`）。按 `docs/V2_2_ALIGNMENT.md` P3 落地与 Package Registry 分离的支持状态注册表：包可加载 ≠ 案由已支持。不改门禁、审批、发布链语义。

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| 新增测试 `tests/test_support_registry.py` | **8 项通过**：种子 labor supported（三 profile 环境）、contract_test 可加载但建案 409、悬空引用注册拒绝、pack_ids 收窄后建任务 409、capabilities 收窄后指定能力 409、suspend 阻断新建并使在途任务 stale（`system:support_suspended` task_step）、integration_only 在 production 环境建案 409、端点角色强制 |
| 既有测试随新语义更新 3 处 | `test_domain_pack_extends…`：新案由导入后须显式注册支持才能建案（断言先 409 再注册后 200）；`test_entrypoint_task…`：插件新能力须登记 `R_custom_timeline`；`test_freeze_accepts_real_create_task…`：直接注入的 fixture pack 须登记 pack_id |
| 自动并入规则 | 对已 supported 案由，pack 经 `registry.publish_pack` 或 `runtime_pack.activate_runtime_pack` 发布后自动并入 `pack_ids`（发布即 vetting 事件）；未注册案由不受影响。`evaluate_task` 增加支持状态软校验：失支持 → risk blocker + `approval_allowed=false`，不新增 G 门编号 |
| Python 全量测试 | `pytest -q`：**602 passed、5 skipped、1 warning**（约 21 分钟） |

边界如实声明：支持状态只决定"能否进入产品闭环"（建案/建任务/批准），**不授予外发**——`product_dispatch_state()` 恒 blocked、G 门与 `dispatch_allowed` 语义零改动；种子仅声明 labor 为 supported，`contract_test` 保持可加载未支持以证明两表分层。

## 2026-09-24 V2.2 Domain Package Set 拆分（P2）落地验证

本轮设备为 Windows / AMD64，Python 3.13（仓库 `.venv`）。按 `docs/V2_2_ALIGNMENT.md` P2 把单体 `DomainPackV2` 拆分为八类 package 聚合 + manifest，快照改走真实分包内容哈希，不改门禁、审批、发布链语义。

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| 新增测试 `tests/test_domain_packages.py` | **8 项通过**：确定性拆分、八类 package_type、哈希稳定、manifest 引用、源 pack 关联、按 task_type 匹配 capability_binding、真实包哈希入快照、P1 回落、生命周期转换、缺签名密钥 fail-closed、撤销阻断新建并使在途任务 stale、API 角色强制 |
| 既有测试 `tests/test_domain_runtime.py` | 一处断言随 P2 语义更新：快照含按 task_type 匹配的 capability_binding_hash，不同 task_type 产不同快照（内容寻址仍成立）；`platform_api` 不匹配仍 fail-closed（manifest 路径同时校验单体 pack 声明） |
| Python 全量测试 | `pytest -q`：**594 passed、5 skipped、1 warning**（约 251 秒）。期间发现一项语义裁决：manifest 生成后插件向 pack 追加的 task_type 无 binding 记录——裁决为"未绑定不阻断"（`capability_binding_id=None`，其余分包哈希仍钉死），而非 fail-closed；已撤销 manifest 则 fail-closed 不回落 |
| 门禁/发布回归 | `outbound_gate.py`/`policy.py`/`formal_release.py` 本轮零改动；正式外发仍 fail-closed |

边界如实声明：仓库种子 manifest 止于 `validated`，无 `LEX_PACKAGE_SIGNING_KEY` 不提供签名、不标记 published；`deprecated` 包仍可解析、`draft`/`revoked` 包拒绝解析；包拆分仅进快照/绑定层，`disclosure.py`、`outbound_gate.py` 消费侧仍读单体 pack——SPI 消费切换属后续阶段。

## 2026-09-22 V2.2 运行时绑定模型（P1）落地验证

本轮设备为 Windows / AMD64，Python 3.13（仓库 `.venv`）。按 `docs/V2_2_ALIGNMENT.md` P1 落地运行时绑定对象，绿地并行双写，不改门禁、审批、发布链语义。

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| 新增测试 `tests/test_domain_runtime.py` | **10 项通过**：绑定创建、快照内容寻址去重、包变更产新快照且旧任务不回改、上下文 supersede 链、request_hash 并入快照、老任务哈希公式不变、platform_api 不匹配 fail-closed、缺包 fail-closed、TaskStep 生命周期记录 |
| Python 全量测试 | `pytest -q`：**586 passed、5 skipped**（约 117 秒）。期间发现两项既有失败：`test_adapted_recording.py::test_three_adapted_workflows` 中录音改编案 `la002/la003` 在既有未提交的边侧复核层 `_synthetic_edge_review` 落入 block_external 分支——本轮顺手补齐三个录音场景 id 的分支映射（la001_edge_block→阻断，la002/la003→可入人审，语义与场景名一致），修复后全绿 |
| 门禁/发布回归 | `test_outbound_gate`、`test_formal_release_*`、`test_runtime_pack*`、`test_workflow` 等全部通过；`outbound_gate.py`/`policy.py`/`formal_release.py` 本轮零改动 |

新对象为双写观测层：`domain_runtime_snapshot`、`case_context_version`、`case_domain_binding`、`task_step` 四个聚合 kind 走通用 records 存储，无数据库迁移。旧任务无快照字段时 request_hash 依赖公式逐字节不变。

## 2026-09-19 双线开发验证

本轮设备为 macOS，Python 3.12；浏览器使用本机 Google Chrome。分支为 `feat/production-demo-dual-track`。本机未安装 Docker Desktop 或 PowerShell，未持有本轮获准真实案件和云端密钥，不把下列代码及合成测试作为 Windows 或真实外发验收。

| 本轮检查 | 实际结果与边界 |
| --- | --- |
| Python 全量测试 | `pytest -q -rs --tb=short`：**520 passed、3 skipped**。跳过 PaddleOCR、RapidOCR、whisper.cpp/large-v3-turbo 的实际资产测试；未自动安装模型。保留一项 Starlette/httpx 弃用提示。 |
| 多案件生产调用链 | 同一个经 HTTP 准备、复核、发布、激活的规则包覆盖两宗合成正式案件。实际创建任务、生成请求、技术隔离登记、法学确认、逐请求策略、具名审批、worker 和独立测试网关分别完成一次调用，并拒绝跨请求使用许可。构建身份、攻击证据和服务商返回为受控测试替身，没有互联网调用。 |
| 人工否决 | 浏览器实际执行技术人员提请暂停、法学人员否决，顶部状态与动作同步；初检和具名复核历史保留。随后切换到独立审批人，确认页面没有批准入口，直接提交同一请求哈希的批准也被 API 409 拒绝。后端覆盖并发入队、旧批准、重新检验和另建任务不能绕过未解决事项。 |
| 成功演示闭环 | 浏览器实际执行披露、初检、法学允许、独立审批、模拟调用、逐条来源核对及最终确认。模拟结果保留来源标识。 |
| 演示桌面回归 | `playwright.config.ts --project=desktop-1280 --grep-invert five-viewport`：**8 passed、2 skipped**，两项为仅在独立 production 配置执行的证据登记测试；四类模拟攻击保留实际检出与不确定结果，没有改写为通过。 |
| 材料不足主动停止 | 新浏览器测试先复现待人工复核时停止按钮被错误禁用；修复后通过。案件操作角色无需先取得允许意见即可主动停止尚未发送的请求，排队停止仍走后端事务边界。刷新后状态仍为 stopped、批准为空、请求快照保留，重新检验不可用，全程没有发送请求；发送开始及已终结请求不提供停止入口。 |
| 生产浏览器回归 | `playwright.runtime-pack.config.ts`：**4 passed**。覆盖技术规则草稿、正式 DOCX 入库与拒发、缺少权威构建时不可批准，以及 G1 人工待核登记与隔离文件绑定校验。最后一项仅替换证据上下文和收据接口来测试表单；案件、材料、事实、云端草案和请求冻结仍使用真实本地 API，不是正式证据验收。 |
| 五种视口 | 1440、1280、900、650、390 像素五项通过，覆盖窄屏面板切换和横向溢出检查。 |
| 前端与 wheel | 主动停止修复后 `pnpm build` 通过，1590 个模块。重建 `lexaegis-1.0.0-py3-none-any.whl`（536701 字节，SHA-256 `9b481e764ba35933b79696b919fba337ebbd3eae49f01966c6525fe37f8b5e77`）。归档与当前前端、规则及许可证逐文件比对通过；安装到独立目录后 API 导入及内置资产检查通过。修复重复打包保留旧资源的问题，旧归档确被新校验拒绝。此 wheel 尚未绑定正式镜像和获核验发布清单。 |
| 恢复中断与旧授权 | 同构建恢复会撤销旧批准、排队发送和未消费许可；复制或任一撤权事务中断后，两端标记阻止启动。已消费网关记录及人工复核历史保留。故障注入和独立复审均通过。 |
| CI 工作流静态检查 | `actionlint -shellcheck= .github/workflows/ci.yml` 通过；已补测试/构建依赖、测试环境分离、PowerShell 语法检查及 Compose 初始化。静态检查不代表远端 CI 已通过。 |
| 远端 Actions | 仓库按所有者要求改为 PUBLIC 后，对提交 `8ca2c235c99b2c191b51757bd6a77b0b63141078` 手动触发 [运行 35435576189](https://github.com/Hanyuan9766/LexAegis/actions/runs/35435576189)。七个任务均在分配 runner 前失败、无执行步骤；Linux/macOS/Windows 检查注释一致为 `The job was not started because your account is locked due to a billing issue.` 仓库 Actions 已启用且允许所有 actions。须由账户所有者解除账单锁定后重新执行，不能将公开仓库或成功入队写成 CI 通过。此前 push/PR 运行仅返回 `startup_failure`，没有任务日志。 |

本轮浏览器截图保存在被忽略的 `.artifacts/dual-track-acceptance/`，不提交运行数据库或凭据。真实联调、获准真实案件发送、Windows 干净机器安装、固定 Docker 镜像交付及现场升级回滚仍待目标环境验收。规则和法源补充稿保持待复核，未代签法律发布结论。

## 2026-09-08 至 14 历史验证

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
pnpm exec playwright test --project=desktop-1280 --grep-invert "five-viewport"
pnpm exec playwright test --grep "five-viewport"
pnpm exec playwright test --config=playwright.human-veto.config.ts
pnpm exec playwright test --config=playwright.runtime-pack.config.ts
# 需 dotenv：doctor / probe-edge 自己不读 .env
# docker compose --profile redteam --profile benchmark up -d --build --wait
# lexaegis check-isolation
```

浏览器测试配置会自行启动使用独立验收目录的应用，不访问真实边侧模型或云端模型。
