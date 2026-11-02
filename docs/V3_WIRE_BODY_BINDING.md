# V3 HTTP 请求体字节绑定

## 执行链

生产 cloud 审批由服务端从当前冻结请求计算 `approval.wire_binding`。绑定包含版本、主/备槽各自的目标、模型、序列化版本、最终 JSON 请求体 SHA-256 和字节数，不含密钥、原件、身份映射或请求体正文。批准记录的审计元数据同时保存绑定摘要。既有 V2 请求结构、黄金序列化和 `request_hash` 不变，绑定是审批的附加字段。

JSON 编码由 `wire_bytes.py` 固定为 UTF-8、排序键、紧凑分隔符，并拒绝 NaN/Infinity。提供商的既有参数归一化（stream、temperature、response_format、DeepSeek thinking）在计算批准字节前执行。实际 HTTP 使用这些不可变字节作为 `content=`，不再让 `json=` 在另一处重新序列化。

排队、worker 发送前和网关领取前均重算并核对绑定。网关对不支持该协议的 provider 失败关闭。provider 先生成准备摘要，再在调用 HTTP transport 前核对实际不可变字节并持久化摘要；落盘失败或字节不一致时不调用 transport。主备槽各自绑定，不得把主槽的字节或模型借给备用槽。网关不会把未提供事先持久化字节回执的 provider 结果记为正式发送成功。

## 账本和失败含义

每个 Attempt 增加 `serializer`、`wire_body_size`、`prepared_wire_body_sha256`、`attempted_wire_body_sha256`、`approved_wire_body_sha256` 与 `transport_prepared_at`。网关记录保留批准绑定，worker 将 Attempt 原样传播到任务与披露账本。

`attempted_wire_body_sha256` 指送交 HTTP transport 前记录的请求体字节。它不证明字节已离开主机，更不证明服务商已收到、处理或合法接收；连接失败仍可能只有 transport-prepared 回执。状态和披露语义继续由既有连接/响应、网关账本与 `unknown` 规则决定。已领取许可之后的异常依旧保守为 unknown，不自动重发。原文、API key、Authorization header 不写进字节回执。

## 升级与回滚

本检查对生产 cloud 默认强制，不是另一个默认关闭的 V3 开关。升级前旧的已批准但未发送任务没有该字段，将在排队或发送前拒绝，必须按既有撤销/重新审批流程产生新绑定，不自动迁移旧批准。已经发送或 unknown 的历史只允许原有只读网关核对，不能以重新审批为由重发。发送接口不支持缺少绑定的旧 envelope；历史查询接口不变。

API、worker、gateway 必须部署同一固定构建，避免混合版本；发布前暂停新发送并处理在途/未知任务。代码回滚会移除此新增强制检查，因此不能把代码回滚当作允许旧批准继续发送的授权。独立副本反向补丁及基线测试的结果在交付的 VERIFICATION.txt 中记录；真实环境回滚仍须暂停出口、保留账本并重新核验。

## 验证与未完成项

新增测试使用合成案件、合成签名依据和 httpx MockTransport，覆盖实际 `httpx.Request.content` 与批准/准备/尝试摘要一致、主备槽分离、签名 envelope 中绑定篡改/缺失、序列化漂移、落盘失败、无回执的伪成功、重复提交、完整 worker→gateway→HTTP transport→任务/披露账本链。没有向真实外部服务商调用。

此变更只补齐请求体字节绑定切片，不替代 G0–G10、真实组织授权、权威证明复用、网关领取后实时撤销、A 链、动态能力计算、真实云回执或法律/安全验收。它也不声称 HTTP headers/TLS 帧是被审批的数据对象。
