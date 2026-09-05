# LexAegis 0.2 实现状态

> **历史文档（归档）。** 能力与接口的现行说明已并入 [架构说明](../ARCHITECTURE.md)；实验与红队命令见该文附录。本文保留作 0.2 落地时的原始叙述。

---

## 已进入代码的能力

- `DomainPackV2`、`TaskDefinitionV2`、`DocumentIRV2`、稳定 `MappingEntry`、`ClaimArtifactV2`、服务商、审批、攻击协议与实验产物契约。
- v1 包只作为 draft/demo 读取；V2 包按生命周期冻结哈希，同版本不能覆盖。
- 正式案件采用 `[[LEX:P0001]]` 线 token；mapping、原文、anchors 与 `local_text` 不进入 V2 wire payload 或网关账本。
- 确定性 PII 坐标、重叠合并、敏感性信号和冻结权重风险信号；这些信号不自动作法律结论。
- `fact_summary` 进入通用任务定义；`timeline` 可本地确定性执行；其余任务明确返回未实现。
- 服务商档案、四类冻结攻击结果、完整请求依赖、具名限时审批和隔离记录共同组成正式门禁。
- DOCX、文本/扫描 PDF 与可选 PNG/JPEG 本地 OCR 输入；无 OCR 时保留扫描锚点并进入人工处理。
- 默认导出为 cloud view；含身份与锚点的 local review bundle 要求结果确认及具名二次确认。
- 原生跨平台 CLI、容器隔离 profile 和无正式卷/密钥的 benchmark profile。

## 有意保持阻断的事项

仓库中的劳动争议 V2 包仍为 `draft`，法源、必要性矩阵和风险协议尚待法学团队冻结。没有经审核服务商、四类真实攻击运行、隔离验收与具名审批时，正式外发不会开放。该状态不是缺省“安全”，而是明确的工程阻断。

## 隔离红队运行

正式任务先执行确定性风险检验，生成只由线协议载荷、任务版本、材料版本和累计披露版本构成的 `attack_input_hash`。案由包必须显式绑定四类冻结协议，随后由
`POST /api/v1/tasks/{task_id}/attacks/run` 排队。Worker 只把假名化 `wire_payload`、受查询预算限制的既往披露和操作员声明为攻击者可见的辅助数据发送给 redteam 服务。

Worker 与 redteam 使用独立的 `LEX_REDTEAM_SECRET` 对作业签名；该密钥不得与网关 HMAC 密钥复用。Compose 启动正式红队能力时需显式启用 profile：

```bash
LEX_REDTEAM_SECRET=replace-with-a-separate-random-secret docker compose --profile redteam up -d
```

每类结果以 `AttackRun` 持久化，并绑定协议内容哈希和攻击输入哈希。超时、返回契约错误、Worker 中断、任务内容变化均记为 `error` 或拒绝写入；修改披露决策后旧运行不会被新一轮门禁复用。运行完成后必须再次执行风险检验，只有四类结果均为 `resisted` 才消除红队阻断。

## 声明式扩展与坐标化检测

`TaskDefinitionV2` 的输入、输出 Schema 使用内置的受限 JSON Schema 子集，负载上限在执行前统一检查。本地确定性任务通过 `lexaegis.tasks` entry point 提供 `definition()` 与 `run(payload)`；云端任务仍走同一审批和网关状态机，并在落库前执行注册的结果验证器。UI 渲染器只能从契约中的固定白名单选择，扩展不能注入前端代码。

`DomainPackV2` 会保存任务—字段—必要性矩阵。草案缺少矩阵时只会生成 `uncertain` 的保守项，不会推断法律结论；正式发布则额外要求法学状态、适用范围、外发许可和五类风险权重全部冻结。自定义直接标识正则在导入时编译并进行回溯结构检查，案由包仍只允许声明式数据。

确定性检测首先记录假名化披露文本中的坐标，再依据事实的全部 `source_ids` 查找原文精确跨度，产出 `source_spans`。无法映射到原文的命中保留为 `warning`，不会自动篡改材料。未配置完整风险权重时，各分项仍可用于观察，但权重为零且正式流程增加硬阻断。

## Ianvs 隔离实验

`lexaegis bench --profile ianvs-pipl` 在没有输入时只报告 `input_required`，不会从文本哈希构造伪向量。完整运行需通过 `--input` 指定 JSON，其中 `vectors` 是真实实验向量，`input_model_hash` 是产生向量的模型或生成器哈希；可选的 `target_outputs` 必须声明 `source: real_target_model` 和模型哈希。

```bash
lexaegis bench --profile ianvs-pipl \
  --input experiment-input.json \
  --output experiment-report.json \
  --seed 23 --target-dim 2 \
  --max-norm 1 --noise-multiplier 1 --delta 0.00001
```

报告包含 Gaussian DP 的 L2 clipping 和可组合 RDP 预算、JL/PCA/稀疏随机投影的冻结矩阵哈希与距离失真，以及显著性掩码的 `heuristic` 或 `experimental_model` 来源。LOSS、Neighbourhood MIA、LiRA 和反演相似度只消费显式真实输出；缺失时为 `not_applicable`，常量分数为 `uncertain`。输出路径使用排他创建，既有报告不会被覆盖。该 CLI 不被生产 API、worker 或 dispatch 导入。

## 本地账户、服务商与复原治理

首次启动会创建 `admin` 本地账户，口令使用 scrypt 和独立随机盐保存；API 不返回哈希或盐。管理员可建立 `case_operator`、`legal_reviewer`、`approver` 和其他管理员账户。路由按角色检查，停用和角色变更在下一请求生效，口令变更会令既有会话失效；不能停用或降级最后一个管理员。审计记录从请求上下文写入具名操作者，不再使用固定演员名称。

服务商档案修改后一律回到 `draft`，具名复核是独立动作。角色、处理地区、留存、删除、训练使用、人工访问、分包商状态、合同、影响评估、有效期和允许范围缺任一关键值时不能复核。任务请求冻结 `provider_hash` 与 `pack_hash`，审批和发送前会再次比对，档案或案由包发生变化即要求重新检验。

复原页并列显示云端假名化陈述、边侧身份回填、实际外发支持事实和版本化原文锚点。未知直接标识、破损/未知 token、重复或无效引用、无依据数字均形成显式问题。默认导出为 `cloud_view`；`local_review_bundle` 必须在结果逐项确认后取得绑定当前任务版本和产物哈希的 15 分钟具名确认。

本地离线备份包含账户的密码哈希，以便恢复后保留账户体系；不包含网关签名密钥或云端 API 密钥。恢复后应重新配置外部密钥。

真实边侧模型、PaddleOCR 权重、真实云服务商、容器网络以及 100 份半合成盲测仍需在授权环境执行。代码不得用模拟 loss、文本哈希伪向量、常量指标或空实现伪造验收。
