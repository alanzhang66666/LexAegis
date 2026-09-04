# LexAegis · 案隐盾

云边协同的法律材料披露工作台：边侧整理原文与身份映射，律师批准完整请求后，由独立网关调用云端大模型 API，结果回到边侧校核和回链。

**当前版本：0.2.0。** V2 案由/任务契约、稳定 wire token、确定性 PII 与风险信号、服务商治理、四类冻结攻击接口、本地复原和跨平台 CLI 已进入代码。法学规则尚未发布、真实攻击与隔离尚未验收，因此**正式案件的外发保持阻断**。演示流程只接受内置合成材料，不允许用户上传或自定义外发文本。

## 快速启动

运行已构建 wheel 只需要 Python 3.12+；源码开发前端需要 Node.js 22+ 和 pnpm 11。当前 0.2 验证使用 Windows/AMD64 与 Python 3.13.2，CI 定义了 Windows、macOS、Linux 矩阵。

请使用 **http://127.0.0.1:8765** 打开工作台，不要用 `localhost`（在部分系统上可能解析到 `::1`，与 Host 白名单不一致）。

### Linux / macOS

`requirements.lock` 使用环境标记排除 Windows 不支持的 `uvloop`；也可使用 `constraints/linux.txt` 或 `constraints/macos.txt`。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
python scripts/make_examples.py
lexaegis start
```

### Windows（PowerShell）

Windows 可从项目元数据安装，也可使用 `constraints/windows.txt`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
python scripts/make_examples.py
lexaegis start
```

若执行策略阻止激活脚本，可先运行：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

Windows 本机模式下，Unix 文件权限位（如 `chmod 0700`）不生效；口令与材料的访问控制依赖当前 Windows 用户账户与目录 ACL，不能当作容器网络隔离的替代。

打开 [本地工作台](http://127.0.0.1:8765)，输入启动终端显示的口令。首次启动会在 `.data/app/` 生成本地访问口令和网关签名密钥。按 Ctrl+C 停止 API、网关和工作进程。

不需要配置模型即可体验三个固定合成案例。选择“完整披露流程”，依次执行：

1. 生成披露方案，查看各字段如何保留、假名化或泛化。
2. 检验风险并查看完整请求。合成演示的四类攻击显示“未运行”，不得作为正式检验通过。
3. 批准当前版本，再点击“执行模拟调用”。模拟器仅从已披露事实组装条目，不声称模型生成。
4. 查看摘要、回到原文、逐项核对并确认最终结果。

“组合线索风险”和“主动停止”案例默认阻断审批。正式案件可以上传 `examples/synthetic_labor.docx` 或 `examples/synthetic_scan.pdf`，体验解析、转录、事实编辑及正式外发阻断。若仓库中尚无这两个文件，先执行 `python scripts/make_examples.py`。

## 模型与 OCR 配置

将 `.env.example` 复制为 `.env` 后按需填写。真实密钥和材料仅存放在忽略目录中。

**边侧小模型**：支持 OpenAI-compatible `/v1/models` 和 `/v1/chat/completions`，要求模型输出结构化 JSON。可连接已自行部署的 Ollama 或 llama.cpp 等兼容服务。填写 `LEX_EDGE_URL` 与 `LEX_EDGE_MODEL`，或在工作台“运行配置”中保存。地址默认仅允许 localhost、127.0.0.1、edge-model；可信内网部署需明确设置 `LEX_EDGE_ALLOWED_HOSTS`。未配置模型时仍支持人工事实管理。

**云端大模型**：在工作台填写 API 根地址与模型；仅在网关环境设置 `LEX_CLOUD_API_KEY` 和 `LEX_CLOUD_ALLOWED_HOSTS`。开发启动器不会将云端密钥传给业务 API 或工作进程。请求需使用 HTTPS，服务商主机需要明确登记。首版只支持 Chat Completions JSON 输出，不支持 Responses API、自动工具调用或自动服务商回退。

使用固定合成案例中的“新建真实 API 演示任务”测试已配置服务。每次仍需审批，且会产生服务商调用费用。该入口不允许追加真实材料。**交付验证没有调用真实云端模型。**

**扫描 PDF / OCR**：没有 OCR 时保留页面、坐标和待处理状态，可在边侧看原图并逐页人工转录。需要自动 OCR 时，在目标硬件上安装 `paddleocr>=3,<4` 和匹配平台的 `paddlepaddle>=3,<4`，预置离线模型资源，再设置 `LEX_OCR_ENABLED=1`。不允许案件处理中通过云端 OCR 回退。OCR 结果默认需要人工复核；模型资产缺失或推理错误不会记为识别成功。当前交付已验证扫描页检测、原图渲染及手工转录，**未验证 PaddleOCR 权重推理或识别精度**。

## 数据、版本与恢复

- 原件位于 `.data/app/files/`；业务数据库为 `.data/app/app.sqlite`；网关账本为 `.data/gateway/gateway.sqlite`。
- 原件保持不变，人工校正生成新的 `DocumentIR` 版本。历史事实和任务继续指向原版本；受影响任务失效，不能继续使用旧审批。
- 案件内保存独立 `MappingEntry`，外发只使用 `[[LEX:P0001]]` 稳定 token；真实值映射永不进入网关或云端载荷。任务保存规则、事实及完整请求快照。
- 模型响应必须带事实引用；数字和引用检查、律师逐项确认共同决定最终结果状态。精确文本匹配不代表语义、法律结论或证据真实性已经自动证实。
- 发送前写入披露台账。超时、崩溃或结果不明时禁止盲目重发，只能查询网关已有记录。网关无法证明未送达时，状态继续保持不明。
- SQLite 用 WAL 和短写事务；网络及模型推理不在数据库事务中执行。单工作进程通过文件锁防止重复启动。

离线备份和恢复：先停止三个服务。备份含原始材料，权限为仅本地用户可读，不包含密钥或访问口令；应保存在用户认可的本地位置。

```bash
lexaegis backup /path/to/lexaegis-backup.zip --offline-confirm
lexaegis restore /path/to/lexaegis-backup.zip \
  --target /path/to/restored-app --gateway-target /path/to/restored-gateway
```

恢复仅支持空目录，验证清单和校验和，不覆盖已有案件。重新设置 `LEX_DATA_DIR`、`LEX_GATEWAY_DIR` 与凭据再启动。恢复中断时应使用新的空目录重试。

## 隔离部署

本机开发模式的独立进程不等同于操作系统级安全隔离。提供的 `compose.yaml` 将 API/worker 放入内部网络，只有网关同时连接外发网络；原件与网关使用不同卷。前端资源全部本地提供，无第三方字体或遥测。

```bash
# .env 必须配置 LEX_LOCAL_PASSWORD 和 LEX_GATEWAY_SECRET
docker compose up --build -d
lexaegis check-isolation
```

可选的 `edge` profile 使用 llama.cpp 服务，将自行取得且适配硬件的 GGUF 权重放到 `models/edge.gguf`。设置 `LEX_EDGE_MODEL=edge-small`。`LEX_EDGE_IMAGE` 可覆盖镜像；交付配置中的上游标签未锁定 digest，正式部署前应验证所选镜像并固定 digest。

```bash
docker compose --profile edge up -d
```

红队服务位于独立内部网络且不挂载任何卷；输入契约拒绝原文、mapping、anchors 与真值。只有冻结协议的真实运行结果 `resisted` 才可满足门禁，其他结果均阻断。

当前开发设备没有 Docker，**容器构建及网络隔离未经过实际运行验收**。`check_isolation.py` 是待目标机器执行的验收脚本，不能把 Compose 配置本身当成隔离已通过的证据。主机管理员、恶意本机进程、磁盘加密和云服务商的数据保留政策不属于首版已实现的防护范围。

## 扩展与维护

案由知识包见 `packs/`：声明领域字段、任务范围、披露规则、依据和发布状态。包不能携带可执行规则表达式，相同版本不可覆盖。

```bash
python -m lexaegis.cli import-pack /path/to/domain-pack.json
```

正式发布包需审核记录，但导入发布包本身不会解锁外发：四类风险策略仍需独立实现与验收。测试包 `contract_test` 仅验证案由扩展接口。

任务定义位于 `lexaegis/task_engine.py`，并可由管理员安装的 `lexaegis.tasks` entry point 扩展。事实摘要和本地确定性时间线已开放，证据整理与争点提取明确标为未实现。架构约定见 [架构说明](docs/ARCHITECTURE.md) 与 [V2 实现状态](docs/IMPLEMENTATION_V2.md)。

## 验证

```bash
python -m pytest -q
cd frontend
pnpm build
# 先按 docs/VALIDATION.md 启动独立验收实例
pnpm exec playwright test
```

当前验证为 **35 项后端测试通过且无弃用警告**，前端类型检查和生产构建通过，wheel 已核验包含前端、V2 包和 NOTICE。0.2 浏览器五视口矩阵与容器隔离仍待 CI/目标环境运行；详见 [验证报告](docs/VALIDATION.md)。

本项目不集成 DataInfra 代码；Ianvs 仅按固定来源选择性改写算法思想与结构，并保留修改说明。没有附带模型权重、真实案例或评测效果数字。依赖及来源说明见 [来源与许可](docs/PROVENANCE.md)、[第三方台账](docs/THIRD_PARTY.md) 与 [界面设计基线](docs/DESIGN.md)。
