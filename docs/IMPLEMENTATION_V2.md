# LexAegis 0.2 实现状态

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

真实边侧模型、PaddleOCR 权重、真实云服务商、容器网络以及 100 份半合成盲测仍需在授权环境执行。代码不得用模拟 loss、文本哈希伪向量、常量指标或空实现伪造验收。
