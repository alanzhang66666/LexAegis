# 案隐盾（LexAegis）V3.0 门禁精简与默认受控外发 ADR

> **状态**：Proposed。**目标是减少用户操作、重复验证和延迟，不是减少法定义务或绕过原文隔离**。主分支目前仍有 `product_dispatch_state() == "blocked"`；本文是 V3.0 目标，不代表系统现在可以对正式案件发送。
>
> 关联：`docs/V3_0_REFACTOR_SPEC.md`、`docs/V3_0_DELIVERY_MATRIX.md`；依据法学方案的 L0–L4、A/B 双链、A-01/B-01/G-01/E-01/E-02/C-01 以及五类审计记录；实现基线 `lexaegis/outbound_gate.py`、`formal_release.py`、`gateway.py`。

## 1. 决定：四道可见门禁 + 一套后台准入凭证

**目标用户体验**：

```text
材料与任务 → [①法律/接收方准入] → [②最小披露/风险]
          → [③按L等级一次确认] → [④网关即时验签+实发] → 本地证据回链
```

**默认可发送（available-when-ready）**：若部署、服务商、法律包与特定请求都满足签名/法律/隐私/授权/网关条件，用户能实际发送，并得到真实的 `sent/complete/unknown` 回执；**绝无产品级恒阻断**。但任何新请求初始 `pending`，不是 `approved`。L4、未经核实的法律依据、未确认的跨境目标或缺少必需审查必须拒绝发送。

| 用户可见关口 | 合并的检查 | 用户通常需要做什么 | 权威性/失败规则 |
| --- | --- | --- | --- |
| **G-L 法律与接收方** | A/B 法域、业务目的与角色、七维链路规则、经过签署的法源/Provider/已发布领域包有效性。现有 `G1/G3/G5` 及 `G2` 部分案件适用性在此解释 | 首次配置环境、接收方或案由时完成审核；复用范围内免重复签署；A/B 分别出具许可 | 证书过期/撤销/法域或用途变化立即失败。无需 A 的 B-only 调用不强加 A 审批，反之亦然 |
| **G-D 数据与风险** | `G0/G2/G7/G8` 数据检查：S0–S2、L0–L4、PII、字段必要性、组合线索/跨轮累计披露、案件事实版本、敏感攻击结果 | 通常自动生成/查看事实卡 Diff；变动才重审，只有真实风险才要求手工修正 | L4 不可绕过；高风险/攻击失败/未知状态不发。红队结果只对相同 `attack_input_hash` /攻击协议版本有效 |
| **G-H 一次风险分级确认** | 原 `G6` 对应的请求证据与 `G10` 具名角色行动、冻结请求、L 级别审批 | L0 自动（严格无案件事实）；L1 常规确认；L2 律师/合规专员；L3 双重合规与法律审批；L4 无可批准路径 | 每条合法外发请求只建立一次有效授权，不要求用户对 G1…G10 分别签署；角色隔离，独立 A/B 授权 |
| **G-S 网关即时执行** | `G9` 有效部署证据、凭据和目标白名单、签名、`request_hash`、字节哈希、nonce、许可有效期、实际尝试账本 | 发送操作一次，状态直观 | 真实发出前不再执行 OCR/LLM/全量红队；任何签名/版本/目标/预算不符拒绝，未知发送态禁止盲重试 |

**兼容性约定**：这四项是 V3 的**聚合呈现与编排层**，不是立刻删掉旧 `G0–G10` 收据和异常码。旧 G 编号仍可在内部审计/接口返回中逐项回溯，逐项映射在新 `GateEvaluationBundle`，不改已冻结 V2 证据语义。`G6` 等具体历史收据的要求必须在重构代码时由现有 `formal_release.py` 的真实合同映射并通过黄金 fixture 校验，不能仅凭本表名称推定可删除。

## 2. 哪些前置审核可以复用，哪些每次必须检查

| 粒度 | 可复用的核验证据 | 必须触发更新/失效的条件 |
| --- | --- | --- |
| **部署级：`DeploymentReadinessAttestation`** | 经核验的网段隔离、构建/运行身份、供应链、密钥驻留、出站策略。签名 + 有效期 + env/build/image hash | 版本、镜像、网络、防火墙、身份、密钥策略变更，超时、撤销或核查失败 |
| **服务商/法域级：`RecipientLegalAttestation`** | 经法学审核的真实区域、用途限制、DPA、子处理方、留存/训练约定，签名七维法律审查 | 服务商、实际处理/存储区域、适用法、期限、目的、签署者、接收角色、转委托或合同变化 |
| **领域规则级：`PolicyAttestation`** | 法源/领域包已发布的签名哈希、G-产品策略、字段必要性矩阵及有效期 | 法源废止、字段矩阵调整、包撤销、案件类型范围变化 |
| **任务级：`PayloadAssessmentSnapshot`** | 边侧PII、L等级、事实卡Diff、来源/材料版本、已生成的 `attack_input_hash` 对应验证结果 | 请求内容、证据、身份映射版本、跨轮披露账本、接收方、任务目的、攻击协议/模型版本变化 |
| **即时发送级：`OneTimeGrant + WireReceipt`** | 一次性许可绑定任务、链、内容、模型/目标、快照哈希与有权签署者 | 任何状态变化、过期、nonce 已消费、hash不一致、发送状态不明 |

**特别约束**：`G8` 不能单凭“这个部署曾经做过红队测试”跳过当前案件的组合攻击。只有当相同外发载荷、同一接收方的累计披露上下文、攻击协议版本/评估输入均一致且原攻击结论具有适用性时，才可以复用先前 `resisted` 凭据，否则应异步预计算并在发送时检查是否完成；结果 `uncertain/error` 不算通过。`G9` 不能以过期的部署证明代表当前隔离有效。

## 3. 最少人工点击与法学审批梯度

> 下面的审批层级来自法学 PRD；绝不为了减少点击降低审批角色或取消独立链审查。

| L 级别 | 工作台行为 | 审批 |
| --- | --- | --- |
| `L0` | 公开法律条文、抽象问题、不含具体案卷事实，系统自动准入和自动调用记录 | 系统自动核验；仍需已认证服务商、合法目的和网关安全性；不得将“自动核验”扩为自动发送案件内容 |
| `L1` | 已令牌化并宽泛泛化，生成事实卡后自动提示一次确认 | 法务助理/承办律师按角色确认 |
| `L2` | 必需精确金额/日期等，组合线索检查完成、报告可见 | 承办律师或合规专员具名审批 |
| `L3` | 高敏或跨境受限，默认未批准；并列法域评估、PIA/CTIA 适用性核验及加强最小化 | 法学方案规定的律所合伙人/企业 DPO 双重审批；无法确认时拒绝 |
| `L4` | 命中硬性禁止，强制从边侧重构任务或不外发 | 任何角色不能覆盖 |

**A/B 双链最少打扰**：某次只使用 B 链外部模型时，仅审查 B 链所涉及的法域和接收方，不额外让用户对不会发生的 A 链业务分享签字；只 A 业务传输同理。如果同一次工作流先 B 生成再 A 分享，两条**实际发送**必须各自具有合法许可，但可以在一个审核界面展示，复用同一案卷来源事实，不重复上传或审核不变的公共材料。

## 4. 网关实时关键路径（O(1) 小型核验）

```python
def can_dispatch(frozen_request, route, attestations, chain_decision, grant):
    # Policy proofs can be prepared before user clicks Send.
    if not attestations.valid_for(frozen_request, route):
        return BLOCK("environment_or_rule_proof_stale")
    if not chain_decision.valid_for(route.chain, frozen_request):
        return BLOCK("chain_legal_approval_missing")
    if frozen_request.disclosure_grade == "L4":
        return BLOCK("absolute_prohibition")
    if not frozen_request.payload_assessment_hash_valid:
        return BLOCK("risk_or_minimization_stale")
    if not grant.valid_for(frozen_request, route.chain):
        return BLOCK("human_approval_invalid")
    if not frozen_request.wire_bytes_match_approved:
        return BLOCK("wire_hash_mismatch")
    if grant.nonce_consumed_or_unknown:
        return BLOCK("replay_or_unknown")
    return ALLOW_ONCE
```

上述仅为**设计伪代码**，不是对现有 `gateway.py` 的 patch。正式实现还要覆盖 provider 凭证、发件端幂等/事务账本、A/B 适用豁免判断、DP release budget（仅当选择对应机制）、请求双槽范围等所有既有必要条件。`O(1)` 指请求阶段的固定数量预计算摘要核验，不承诺数学意义上的严格复杂度或忽略数据库成本。**既有逐项审计证据只减少重复计算，不减少必须达成的实质结论。**

工作流：
1. `assess`：在任务生成时异步汇集领域证书、接收方、风控、红队信息，一次形成 `GateEvaluationBundle` 和带可修复理由的缺失列表。
2. `approve`：只展示一份审批卡及符合 L 级的签署动作，绑定整包版本；不会让审批人分别对每个技术项签署。
3. `send`：只校验短期有效 Bundle + nonce + 法律适用链 + 精确字节 hash + 网络目标；事务性记录尝试后调用 provider。
4. `return`：原 `return_pipeline.py` 九阶段继续后台执行；证据回链与人审是**结果采纳/正式导出**关口，不应误放到网络发送前反复运行。

## 5. 消除阻碍实际外发的产品级旧设计

现有代码真实障碍：
- `outbound_gate.product_dispatch_state()` 返回恒定 `blocked`，与 V3 默认能力可用冲突；
- `formal_release.py` 存在 `FIRST_RELEASE_TUPLE`（LA-001/`R_fact_summary`/`D_DeepSeek_official_API`）的首案试点范围；
- `evaluate_release` 逐份解析 G1/G2/G3/G5/G6/G7/G8/G9/G10 收据，可能在正常发送前重复耗费大量验证；
- `gateway.py` 已有实际云调用、白名单、签名、发送账本与 `unknown` 防重试，可复用；
- A 链独立共享执行器尚需实现。

**改造不是直接将产品常量改为 `available`**，而是把 `product_dispatch_state` 改为从已签署部署能力证明和有效域包/接收方配置计算的结构化状态：`unconfigured | needs_readiness | available | suspended`。`available` 只意味具备执行能力，单次请求 `allowed` 仍必须由四门合并谓词决定。固定首案试点逻辑改为动态、具版本的 `ScopedReleasePolicy`，保持一请求一许可、一单一 nonce。

## 6. 建议新契约（目标形态）

```json
{
  "GateEvaluationBundleV3": {
    "task_id": "task_123",
    "chain": "B",
    "request_hash": "sha256:...",
    "legal_readiness": "pass",
    "payload_readiness": "pass",
    "approval_readiness": "pending",
    "send_readiness": "pending",
    "legacy_gates": {
      "G0": "pass",
      "G1": "pass",
      "G2": "pass",
      "G3": "pass",
      "G5": "pass",
      "G6": "pass",
      "G7": "pass",
      "G8": "pass",
      "G9": "pass",
      "G10": "pending"
    },
    "attestation_hashes": {
      "deployment": "sha256:...",
      "legal_recipient": "sha256:...",
      "policy": "sha256:...",
      "payload": "sha256:..."
    },
    "blocking_reasons": [
      {"gate": "G-H", "code": "named_approval_required", "action": "request_role_approval"}
    ],
    "valid_until": "2026-12-01T00:00:00Z"
  }
}
```

版本化证书还应具有链类型、法域、签署者、签署范围、撤销/有效期、预期角色、模型/endpoint/provider profile、发布版本；上述 JSON 是展示层的最小切片，不足以单独执行授权。状态必须依赖服务端持久记录，不信任前端直接提交 `legacy_gates` 值。

## 7. 测试矩阵与性能目标

| 类型 | 验收要求 |
| --- | --- |
| **正向** | 在 `production` 环境中，经过审核的 L0、L1、L2、满足全部法学条件的 L3 请求，可以正常真实发送 B 链；A 链独立验证；出站账本 `sent/complete` 与服务商回执一致 |
| **防越权** | L4、未知法源、接收方未审核、A/B 互借、许可超期、请求变更、nonce复用、payload hash 不符、预算缺失、网络隔离失效均不可发 |
| **重用正确性** | 相同环境/包/接收方/冻结请求的证明可复用；换原文、跨轮披露上下文、攻击协议、Provider、法源版本时相关证明失效 |
| **性能** | 比较旧 G0–G10 流水线与 V3 聚合流水线，测量 `gate_eval_p50/p95`、`time_to_approval`、`gateway_authorize_p95`、重检次数、缓存命中/失效率；不得用模拟外发计算实发成功率 |
| **可用性** | 不缺证据时 UI 仅展示一次整包审批；未通过显示可操作、可修复的理由而不是总产品阻断；成功发送后真实回链 |
| **兼容性** | `G0–G10` 老收据映射、V2 冻结哈希、撤销语义、`unknown` 不重试、历史审计查询保持兼容 |
| **流程** | 九阶段返回管道和人工证据审定不阻塞**已经合法完成的请求发送**，但仍阻断未经审定的正式法律文书采纳/导出 |

候选优化指标：**正常准备就绪请求不因重复人工签署而增加超过一次 L 等级所需的交互**；相同证明尽量一次生成、多次合法复用；对网关关键路径用实测 p95 而不是估计或声称「零延迟」。若缓存失效策略导致风险漏放，宁可回退到旧验证路径；避免以减少延迟牺牲合规正确性。

## 8. 工程顺序（相对原 PR-01…11 的更新）

1. **PR-01a 门禁聚合与兼容层**：新增 `GateEvaluationBundleV3` / `AttestationRef` / `gate_orchestrator.py`；老 `G0–G10` 仍执行并落账，先证明新旧允许/阻断等价，不影响外发。
2. **PR-01b 消除重复调用**：将服务商、法域、包签署和部署隔离前置为可核验证明；缓存绑定 scope/hash/TTL/revocation；高风险红队结果只有 exact input 可复用。
3. **PR-02~05**：接入敏感分类、最小化、持久 DP（实验先行）、A/B 链独立准入。
4. **PR-06 真实外发可用**：消除产品级恒阻断和试点单案绑定，使用动态 ScopedReleasePolicy + 精简四门组合结果；生产等价隔离条件下运行正向真实调用；未知态不重试。
5. **PR-07…11**：证据链、UI、KubeEdge、Ianvs、独立法律/安全上线验收；门禁每次变更均做否定性回归与性能对照。

**迁移阶段禁止的捷径**：直接改 `PRODUCT_DISPATCH_BLOCKED` 常量、将 `_REQUIRED_GATES` 改为空、令 `GateHit` 全部返回 `allowed`、把 L3 当 L1、设伪造 `resisted`、复制先前不同载荷的 `G8/G9` 收据、用 `simulation` 冒充 `cloud`、取消 A/B 独立许可。

## 9. 验收口径

- **系统默认**具备受控真实外发能力（即经审核环境不再有无条件总闸门），用户可以持续完成一批合规任务；
- **单次发送默认**未授权，合规满足才进入 `ready_to_dispatch`；
- **只保留四道用户可见门禁**，后台多项工程/法律检查仍需留下可核验记录；
- **审批只做必要次数**：L0 自动，L1 一次常规确认，L2 一次具名专业批准，L3 两名不同授权角色完成审批，L4 无法批准；
- **失败只阻断相关请求/链路**，不因不相关链条、历史缓存或可修复配置问题永久关闭全部产品；
- **实测交付**：按链实际发送、完整网关审计、审批/字节一致性、无漏放与延迟对照同时通过，才称 V3 门禁精简完成。

> 提示：文档将“最少打扰”和“默认可用”具体化为产品及工程验收项，但 **没有修改或放开仓库当前真实出站策略**。
