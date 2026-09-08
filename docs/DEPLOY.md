# 部署、备份与隔离

本机 `lexaegis start` 的独立进程**不是**操作系统级网络隔离。正式隔离只在 Compose 拓扑通过检查脚本后才可主张。native 启动**不能**自证隔离，也**不会**写入 `isolation_verified`。Windows 正式隔离必须使用 Compose；`check-isolation` 在 Docker 缺失或探测失败时列出缺口（无 Docker、非隔离拓扑、出口仍开放、卷/密钥不正确）并以非零退出，**不会**翻转验收标志。

## 数据位置

- 原件：`.data/app/files/`
- 业务库：`.data/app/app.sqlite`
- 网关账本：`.data/gateway/gateway.sqlite`

人工校正生成新的 `DocumentIR` 版本；引用旧版本的事实与任务失效。SQLite 使用 WAL；网络与模型推理不在数据库事务中执行。单工作进程通过文件锁防止重复启动。

Windows 上 Unix 文件模式位（`chmod 0700`）不生效，访问控制依赖当前用户 ACL。

## 备份与恢复

先停止 API、worker 和网关。备份含原始材料与账户密码哈希，不含网关签名密钥或云端 API 密钥，权限为仅本地用户可读。

```bash
lexaegis backup /path/to/lexaegis-backup.zip --offline-confirm
lexaegis restore /path/to/lexaegis-backup.zip \
  --target /path/to/restored-app --gateway-target /path/to/restored-gateway
```

恢复仅支持空目录，校验清单与校验和，不覆盖已有案件。恢复后重新设置 `LEX_DATA_DIR`、`LEX_GATEWAY_DIR` 与外部凭据。中断时用新的空目录重试。

## Compose 隔离

`.env` 必须配置 `LEX_LOCAL_PASSWORD` 和 `LEX_GATEWAY_SECRET`。API/worker 在内部网络；仅网关连接外发网络；原件与网关使用不同卷。前端全部本地提供。

```bash
docker compose up --build -d
lexaegis check-isolation
```

启动 Compose 前先停止本机 `lexaegis start`，避免 native 占用 `127.0.0.1:8765`。Windows 上用 `docker compose port api 8765` 确认宿主机绑定；必须得到 `127.0.0.1:<host>`。若输出为空或 `invalid IP:0`，先查端口占用，**不要**把 Compose 改成 `0.0.0.0:8765`（不向局域网暴露）。Docker Desktop 在 Windows 上可能发不出 `127.0.0.1:8765`；仅连接 `internal: true` 网络时，引擎也可能静默丢掉宿主机发布（`HostConfig.PortBindings` 有值但 `NetworkSettings.Ports` 为空）。可改设 `LEX_COMPOSE_API_PORT=38765`（避开 Playwright 的 18765 与先前空绑的 28765），映射为 `127.0.0.1:38765:8765`。容器内健康检查 200 不等于宿主机已发布，也不等于登录页已打开。隔离探测与宿主机发布分开报告；探测通过不得写成浏览器已通。`compose.yaml` 默认仍是 `127.0.0.1:${LEX_COMPOSE_API_PORT:-8765}:8765`，镜像 `CMD` 已是 `--host 0.0.0.0`。

- `edge` profile：自行将 `MiniCPM5-2B-Q4_K_M.gguf` 放到 `models/`，设置 `LEX_EDGE_MODEL=edge-small`。上游镜像标签未锁定 digest。
- `redteam` profile：独立内部网络、不挂载卷；密钥用 `LEX_REDTEAM_SECRET`，不得与网关密钥复用。Compose 内默认 `LEX_REDTEAM_URL=http://redteam:8767`；native 未设置时解析为 `http://127.0.0.1:8767`，需单独启动 redteam，`lexaegis start` 不会拉起。见 [ARCHITECTURE.md 附录 A](ARCHITECTURE.md)。

当前交付环境若未安装 Docker，**不能把 Compose 文件当成隔离已通过的证据**。

## 启动排障

若 `lexaegis start` 报端口占用（Windows `10048`）或 `worker.lock` 权限错误，说明旧 API/网关/worker 仍在运行。结束占用 `127.0.0.1:8765` 与 `8766` 的进程后再启动。请使用 **http://127.0.0.1:8765**，不要用 `localhost`。

`python scripts/dev.py` 仍可用，内部转调同一启动器，便于 Playwright 与旧命令。新流程请使用 `lexaegis start`。
