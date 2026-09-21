<!-- 由 scripts/export_prompts.py 生成，请勿手工编辑。修改提示词请改 lexaegis/task_engine.py。 -->

# 提示词清单

本目录是运行时实际使用的提示词，由 `scripts/export_prompts.py` 从`lexaegis/task_engine.py` 的任务定义与 `lexaegis/service.py` 的固定后缀导出，与冻结请求逐字一致。请勿手工编辑。

| 任务 | 标识 | 执行方式 | 是否使用提示词 |
| --- | --- | --- | --- |
| 证据整理 | [`evidence_inventory`](evidence_inventory.md) | `local_deterministic` | 否（本地确定性） |
| 事实摘要 | [`fact_summary`](fact_summary.md) | `approved_cloud` | 是 |
| 争点提取 | [`issue_extraction`](issue_extraction.md) | `local_deterministic` | 否（本地确定性） |
| 时间线 | [`timeline`](timeline.md) | `local_deterministic` | 否（本地确定性） |

## 口径

- 提示词只约束模型输出格式与引用义务，不构成法律判断，也不授予发送权。
- 模型返回结果一律经 `lexaegis/policy.py` 的 `check_claims` 校验引用、数字、身份 token 后才呈现，
  任何改写或新增陈述都会标为 `needs_review` 交人工核对。
- 正式案件的外发另受 `lexaegis/outbound_gate.py` 门禁约束，当前 `formal_dispatch=blocked`。
