# 放行前置 readiness

readiness 是现有 `ReleaseBuildManifest`、`EvidenceArtifact` 和 G1-G10 收据的汇总视图，不是第二套放行状态机。报告固定检查构建清单、Compose 隔离、kind/KubeEdge 一致性、宿主机防火墙和供应链。`k8s_conformance` 是工程附件，不能替代 G9，也不会新增 G11；`formal_dispatch` 继续保持 `blocked`。

## 绑定与证据语义

每份报告绑定 `source_commit`、`build_manifest_hash` 和当前 `request_hash`。读取报告时必须再次核对当前任务、构建清单和镜像 digest；任一哈希不一致、证据过期、撤销或缺失，都按 `blocked` 处理。`checks` 中的 `artifact_ids` 只引用不可变登记件，原始 JSON 和生成摘要都保留哈希。

`source_kind=command_generated` 表示由受控命令生成的工程证据。面板只允许查看和绑定，不能把状态改写为通过。`source_kind=manual_upload` 表示人工上传的宿主机、供应链或其他受控材料，仍须由现有技术复核、法学人员或审批人按 G1-G10 规则登记收据。工程证据已生成不等于法学 G9 收据已经确认，面板会分开显示这两件事。

命令生成结果应使用脱敏配置保存，不得包含密码、token、请求正文或绝对路径。有效期由生成端写入；过期或无法完成绑定的结果不会被自动续期。

## 环境行为

`demo` 和 `integration` 只报告 readiness，不改变现有演示行为。`production` 在 approve、reserve/enqueue 和发送前重验时读取同一份绑定结果；缺少构建、Compose、供应链、宿主机防火墙或其他必需证据时失败关闭并返回现有 409 风格错误。`/formal-release/check` 只负责报告和刷新，不会把报告转换成批准或发送。

本地 kind/KubeEdge 演练只使用合成数据，用于记录注册、下发、断连、重连、撤包和 reconcile。它不能证明生产集群已验收。真实案件发送不会由 readiness 命令触发。

## 生成与交付

候选构建可通过 `lexaegis release verify-candidate --validation-report <json> --readiness-output <json>` 生成机器可读报告。Compose 探测可通过 `lexaegis check-isolation --report <json>` 保存结果；演练脚本同时支持 Markdown 和 `--json-report`。CI 应上传脱敏 JSON、Markdown、测试日志、构建清单和固定版本 SBOM，缺少凭据、Docker、kind/KubeEdge 或 SBOM 工具时失败关闭，不把 GitHub Actions 账单锁定解释为通过。

Draft PR 只有在代码、单测、前端/E2E、Compose 和本地 kind/KubeEdge 证据可重复生成，JSON/Markdown 通过 schema 与脱敏检查，且 CI evidence job 已配置为失败关闭后，才可转 Ready。生产集群尚未验收、账单锁定或真实外发未执行，都必须在 PR 中明确记录。
