# KubeEdge 本地演练证据（2026-09-24）

## 环境拓扑（真实组件，单机）

| 层 | 组件 | 形态 |
| --- | --- | --- |
| 控制面 | kind `lexaegis-v22`（k8s v1.37.0） | Docker Desktop WSL2 后端容器 |
| 云核 | KubeEdge cloudcore v1.20.0（hostNetwork，advertise 172.23.0.2:10000） | kind 集群 Deployment |
| 边节点 | `edge-1`：edgecore v1.30.7-kubeedge-v1.20.0 + containerd（native snapshotter）+ CNI（host-local/loopback/portmap/ptp） | `edge-node-1` 容器，接入 `kind` docker 网络 |
| 边应用 | LexAegis API（production profile，Python 3.12 venv） | edge-node-1 容器内进程，监听 8765 |
| 控制面应用 | LexAegis API（production profile） | 宿主机 .venv，端口 18777 |

断连方式：`docker network disconnect kind edge-node-1`（物理切断 CloudHub↔EdgeHub 通道）。

## 演练结论

- **下发**：assignment-1（`dpm:labor:2.0.0-draft.3`）deliver → 边侧 `edge_apply` → verified → activated 回执入控制面
- **断连**：edge-1 Ready=Unknown（lease 过期）；边侧自治——health=200、已导入 manifest 仍持有（2 条）
- **断连期下发**：assignment-2（`dpm:labor:3.0.0-product-draft.1`）控制面 delivered、bundle 装进 ConfigMap + carrier pod——**边侧文件系统验证 absent**（KubeEdge 通道物理不通）
- **重连**：edge-1 Ready=True；ConfigMap 经 CloudHub→EdgeHub→MetaManager→edged 卷同步**真实到达**边文件系统（`/var/lib/kubelet/pods/*/volumes/.../bundle/bundle.json`）
- **边侧处理**：`edge_apply` 导入 KubeEdge 携带的 bundle，verified+activated 回执折回控制面
- **撤包**：assignment-1 revoke → 边侧 `edge_revoke` 执行 → revoked 回执 → assignment 终态 `revoked`
- **对账**：`reconcile` → ok=2 / retry=0 / awaiting_receipt=0 / awaiting_revocation=0 / failed=0

边侧库终态（容器内实测）：`2.0.0-draft.3 → revoked`、`3.0.0-product-draft.1 → 已导入`；
控制面终态：`assign_43e3965e… → revoked`、`assign_bd0c621b… → active`。

## 诚实边界（不扩大声明）

- 这是**本地单机** kind+KubeEdge 演练，非生产集群；证据真实但规模有限
- assignment-1 的 bundle 传输走 `docker cp`（宿主层搬运），assignment-2 走**真实 KubeEdge ConfigMap 同步**——后者才是 CloudHub/EdgeHub 通道证据
- 边应用以容器内进程形态运行（非 KubeEdge 下发的 pod），bundle-carrier pod 仅作通道载体
- 演练用 manifest 均为 `validated` 草稿，不代表法学发布；与外发门禁无关
- 断连判据是文件系统侧（CM 未落盘），未覆盖 `waiting-cloud` 返回管道语义（该语义有独立测试）

## 运行日志

```text
[10:37:05] control-plane login :: ok
[10:37:05] manifests :: dpm:labor:2.0.0-draft.3=validated, dpm:labor:3.0.0-product-draft.1=validated
[10:37:05] edge node registered :: edge-1
[10:37:05] assignment-1 created :: assign_43e3965e63d84038 status=assigned
[10:37:05] assignment-1 delivered :: bundle_hash=909d6e02e5d62d67...
[10:37:06] edge_apply executed on edge-1 :: verified manifest_hash=e06c444dab6a06db...
[10:37:06] verified receipt folded :: status=verified
[10:37:06] activated receipt folded :: status=active
[10:37:06] EDGE DISCONNECTED :: docker network detach — CloudHub channel cut
[10:37:53] kubectl node status :: edge-1 Ready=Unknown (lease expired while disconnected)
[10:37:53] edge autonomy :: health=200, manifests held on edge=2
[10:37:54] assignment-2 delivered (control plane) :: bundle_hash=4cb152f5db19205c...
[10:37:54] disconnected check :: bundle configmap on edge = absent
[10:37:54] EDGE RECONNECTED :: docker network attach
[10:38:41] kubectl node status :: edge-1 Ready=True (resynced)
[10:38:41] kubeEdge sync :: bundle arrived at edge fs: /var/lib/kubelet/pods/089ee374-3016-440f-9676-419341d7b068/volumes/kubernetes.io~configmap/bundle/bundle.json
[10:38:42] edge_apply (kubeedge-carried bundle) :: manifest_hash=776659864783b3a7...
[10:38:42] assignment-2 receipts folded :: verified+activated via KubeEdge channel
[10:38:42] edge_revoke executed :: receipt={'kind': 'revoked', 'edge_node_id': 'edge-1', 'manifest_hash': 'e06c444dab6a06db36bafc753bddaf9c2fbb7e2c3842ed9d4c9654781f7e4ed7'}
[10:38:42] final reconcile :: retry=0 awaiting_receipt=0 awaiting_revocation=0 ok=2 failed=0
```
