# 部署、备份与隔离

本机 `lexaegis start` 的独立进程**不是**操作系统级网络隔离。正式隔离只在 Compose 拓扑通过检查脚本后才可主张。

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

- `edge` profile：自行将 GGUF 放到 `models/edge.gguf`，设置 `LEX_EDGE_MODEL=edge-small`。上游镜像标签未锁定 digest。
- `redteam` profile：独立内部网络、不挂载卷；密钥用 `LEX_REDTEAM_SECRET`，不得与网关密钥复用。见 [ARCHITECTURE.md 附录 A](ARCHITECTURE.md)。

当前交付环境若未安装 Docker，**不能把 Compose 文件当成隔离已通过的证据**。

## 启动排障

若 `lexaegis start` 报端口占用（Windows `10048`）或 `worker.lock` 权限错误，说明旧 API/网关/worker 仍在运行。结束占用 `127.0.0.1:8765` 与 `8766` 的进程后再启动。请使用 **http://127.0.0.1:8765**，不要用 `localhost`。

`python scripts/dev.py` 仍可用，内部转调同一启动器，便于 Playwright 与旧命令。新流程请使用 `lexaegis start`。
