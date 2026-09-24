# 新案由接入流程（V2.2 DomainPackageSet）

平台内核是案由无关的。新增一个案由不是改内核代码，而是产出一套
DomainPackageSet 并完成验收门禁。以下步骤与 `docs/V2_2_ALIGNMENT.md`
的分期实现一一对应。

## 1. 定义范围

- 案由标识 `cause_id`（如 `labor`）、法域 `jurisdiction`、生效区间。
- 任务类型清单：每个 `task_type` 须在 `task_engine` 注册为 capability
  （`capability` 聚合），否则运行期 `assert_capability` fail-closed。
- 人工复核边界：哪些任务类型允许 cloud、哪些仅 local。

## 2. 写包（DomainPackageSet）

单体 `DomainPackV2` 经 `split_monolithic_pack` 确定性拆成八类包：

| package_type | 内容 | 消费方 |
| --- | --- | --- |
| `cause_pack` | fact_schema / task_templates / rules / references / **mapper** | resolver + SPI + 返回管道 |
| `legal_rule_pack` | sources / immutable_relations / rules + effective_from/to | SPI |
| `capability_binding` | task_type → capability_id / execution / provider_profile | `capability_registry` |
| `review_schema` | manual_review_conditions / sensitive_object_rules / conflict_checklist | 复核层 |
| `artifact_schema` | reply_templates | 产出层 |
| `minimization_profile` | direct_identifier_patterns / forbidden_terms | 最小化 |
| `gate_profile` | risk_weights | 门禁 |
| `domain_acceptance_suite` | synthetic_cases | `acceptance_suite` |

约束：包是**纯声明式数据**，经 `spi.py` 只读消费；不得携带代码、
不得触凭据 / G10 / 跨案数据。`capability_binding` 的 `provider_profile`
如填必须指向真实 `provider` 记录，否则建任务即 409。

`cause_pack` 的 `mapper` 键是返回管道的声明式映射配置，由
`lexaegis/domain_mapper.py` 通用引擎执行（包不跑代码）。语法键：
`applies_to`（task_type 白名单）、`claim_list_key`（默认 `claims`）、
`field_map`（字段改名）、`value_map`（值归一）、`defaults`（缺失字段
默认）、`required_fields`（映射后必填断言，缺失即 `invalid_cloud_result`
fail-closed）。阶段出口：`mapped`/`skipped`/`unbound`/`none`/`failed`；
mapper 的包 id + content_hash 写入 artifact 作版本绑定。不得虚构法律
分类或结论——labor 的现存配置仅做必填断言与 `domain` 标记。

## 3. 生命周期推进

```
draft → validated → signed → published → deprecated → revoked
```

- `validated`：`POST /domain-packages/{id}/transition`，结构校验通过。
- `signed`：需 `LEX_PACKAGE_SIGNING_KEY`（或调用方密钥）真实签名；
  无密钥即 409，不发明密钥。
- `published`：对已 supported 案由，发布自动并入 `pack_ids`
  （发布本身是 vetting 事件）。
- `revoked`：安全动作，任何非终态可达；在途任务 stale，resolver
  fail-closed 不回落。

## 4. 注册 manifest

`build_manifest` 把八类包编为 `domain_package_manifest`；快照解析优先走
manifest（含 capability_binding 按 task_type 匹配），manifest 存在但不可
解析时**不回落** interim 路径。

## 5. 验收套件

```bash
python -m lexaegis.acceptance_suite --data <app数据目录> --cause <cause_id>
```

- `package_asserted` 基线（10 项）在本进程内执行，失败即非零退出。
- `test_mapped` 基线映射到 pytest 套件（见报告 `covered_by`）。
- `manual_gate`（如 G10 真实外发）永不自动标过——需要真实证据。

## 6. 部署与激活

- 部署：见 `docs/DEPLOY.md` 与 `deploy/k8s/`（KubeEdge manifests 未在
  真实集群验证）。
- 包下发：控制面 `package_controller.py` 已落地——`POST /edge-nodes`
  注册节点 → `POST /package-assignments` 建期望态 → `POST …/deliver`
  产签名 bundle → 边侧 `edge_apply`（fail-closed 导入，未签名降
  draft，`published` 不导入）→ `POST …/receipts` 回执推进
  （verified→activated）；撤包 `POST …/revoke` + 边侧 `edge_revoke`
  + `revoked` 回执；`GET /package-distribution/reconcile` 对账。
- 激活：`POST /supported-causes` 登记 `SupportedCause`（environments /
  pack_ids / manifest_ids / capabilities / status）。**包可加载 ≠ 已支持**：
  未进 Support Registry 的案由建案即 409。
- 暂停：`POST /supported-causes/{cause}/transition` → `suspended`，
  在途任务 stale + 审计 step。

## 7. 禁写口径

任何阶段不得宣称：外发已开通、N 案已通过、包已发布（仓库包保持草稿）、
KubeEdge 已验证、自动化测试等同于法学/安全/部署验收。
