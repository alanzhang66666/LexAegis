# LexAegis on Kubernetes + KubeEdge

> **状态：本地单机演练已通过（2026-09-24），生产集群未验证。** kind + KubeEdge
> 断连 / 包下发 / 撤包演练收据见 `DRILL_EVIDENCE.md`；注意演练中边应用以
> 容器内进程形态运行、bundle-2 经真实 ConfigMap 同步通道到达，本目录
> manifests 本身未按原样部署——生产形态部署仍是独立验收门禁
> （`docs/V2_2_ALIGNMENT.md` P7）。

## 拓扑映射

| V2.2 域 | Compose 服务 | 本目录 manifest | 节点 |
| --- | --- | --- | --- |
| 边域 Edge | `api` | `edge-api.yaml` | `lexaegis.io/domain: edge`（KubeEdge EdgeCore 节点） |
| 边域 Edge | `worker` | `edge-worker.yaml` | 同上 |
| 云域 Cloud | `gateway`（CGW） | `cloud-gateway.yaml` | `lexaegis.io/domain: cloud`（云侧节点） |
| 共享 | `.env` | `configmap.yaml` + `secret.example.yaml` | — |
| 卷 | `.data/app`、`.data/gateway` | `edge-storage.yaml` | 边侧本地存储（`local-path`） |
| 隔离 | internal/publish 网络 | `network-policy.yaml` | CNI 层 |

边缘侧节点需先打标签与容忍：

```bash
kubectl label node <edge-node> lexaegis.io/domain=edge
kubectl label node <cloud-node> lexaegis.io/domain=cloud
```

## 部署顺序

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
# 用密封密钥或外部密钥系统生成 lexaegis-secrets，勿提交明文
kubectl apply -f deploy/k8s/edge-storage.yaml
kubectl apply -f deploy/k8s/cloud-gateway.yaml
kubectl apply -f deploy/k8s/edge-api.yaml
kubectl apply -f deploy/k8s/edge-worker.yaml
kubectl apply -f deploy/k8s/network-policy.yaml
```

## 云边职责与数据边界

- **原件、身份映射、最终案件状态只落在边侧** `lexaegis-app-data` PVC；
  云域 CGW 只挂 `lexaegis-gateway-data` 账本卷，不接触案件数据。
- **云凭据只注入 CGW pod**（`secret.example.yaml` 注释）；edge-api /
  edge-worker 只持有 `LEX_GATEWAY_SECRET` / `LEX_REDTEAM_SECRET`。
- **云边双通道**：边域 worker → CGW `/dispatch`（签名信封，
  `cloud_task_envelope`）为唯一外发路径；CGW → 边域返回候选结果，
  由 `return_pipeline` 阶段化校验后才可采用。边域 Pod 经
  NetworkPolicy 只能到达 CGW 与 DNS；FQDN 白名单由 CGW 内
  `LEX_CLOUD_ALLOWED_HOSTS` 执行（NetworkPolicy 不识别域名）。
- **断连自治**：云边链路断开时，`ConnectError` 使 send 作业挂起为
  `waiting-cloud` 并退避重试；本地任务继续。详见
  `lexaegis/return_pipeline.py`。

## 包下发链路

V2.2 要求 DomainPackageSet manifest 从云域下发到边域。控制面已落地为
`lexaegis/package_controller.py`（期望状态 + 回执 + 对账），传输通道
可替换：

- `POST /api/v1/edge-nodes`（admin）注册边节点身份——未注册节点
  一律拒绝分配；
- `POST /api/v1/package-assignments`（admin）建期望状态：
  `{manifest_id, edge_node_id}`，manifest 须为
  `validated`/`signed`/`published`/`deprecated`（`draft`/`revoked`
  不可下发）；
- `POST /api/v1/package-assignments/{id}/deliver`（admin）产出签名
  bundle（`export_bundle`）并记 `delivered`，返回的 bundle 由调用方
  负责实际投递；
- `POST /api/v1/package-assignments/{id}/receipts`（admin）边侧回执
  `verified`/`activated`/`revoked`/`failed`——节点身份、manifest
  哈希、状态顺序三项校验，任一不符即拒并记 `failed`；
- `POST /api/v1/package-assignments/{id}/revoke`（admin）期望态转
  `absent`，等待边侧 `revoked` 回执才终态——撤销从不假设已生效；
- `GET /api/v1/package-distribution/reconcile`（admin）期望-实际
  对账报告（retry / awaiting_receipt / awaiting_revocation / ok /
  failed）。

边侧动作：`package_controller.edge_apply`（经 `import_bundle`
fail-closed 入库，`published` 不导入，status 仅对内嵌签名可验证的
记录保留）与 `edge_revoke`（本地撤包 + 在途任务 stale 传播）返回回执
载荷。

集群落地时的建议路径：云域跑控制器（分配 → deliver 产 bundle）→
KubeEdge 通道（ConfigMap/OCM 或独立下发服务）投递 → 边域调
`edge_apply`/`edge_revoke` 并回传回执 → 控制器记回执推进状态；
`reconcile` 供运维或控制器周期对账。本地 kind+KubeEdge 演练已按此路径
跑通（assignment-2 的 bundle 经 ConfigMap 真实同步到边节点文件系统，
断连期 absent、重连后到达），证据见 `DRILL_EVIDENCE.md`；生产集群形态
仍属未验证。

## 与 Compose 的差异

- Compose 的 `isolate-api-route`（删默认路由）在 K8s 由 NetworkPolicy +
  节点域标签承担；edge Pod 不再有出网默认路由语义可删。
- `redteam` 服务未列入本目录——演练用组件，按 Compose profile 方式
  需要时另行部署，密钥必须独立于 `LEX_GATEWAY_SECRET`。
