# LexAegis · 案隐盾

云边协同的法律材料披露工作台：边侧整理原文与身份映射，律师批准完整请求后，由独立网关调用云端大模型 API，结果回到边侧校核和回链。

**当前版本：0.9.0 待发布（`0.9.0rc0`）。** 工作台、V2 契约、稳定 wire token、门禁与跨平台 CLI 已进入代码。法学规则尚未发布、真实攻击与隔离尚未验收，因此**正式案件的外发保持阻断**。演示只接受内置合成材料。本号不是正式发行版。

现行入口地图见 [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md)。文档地图见 [docs/README.md](docs/README.md)。架构与门禁见 [架构说明](docs/ARCHITECTURE.md)。评测语料见 [data/README.md](data/README.md)。边侧声明见 [models/catalog/README.md](models/catalog/README.md)。

## 快速启动

运行已构建 wheel 只需 Python 3.12+；从源码开发前端需要 Node.js 22+ 和 pnpm 11。请使用 **http://127.0.0.1:8765**，不要用 `localhost`。

### Linux / macOS

`requirements.lock` 用环境标记排除 Windows 不支持的 `uvloop`。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e ".[test]"
cd frontend && pnpm install --frozen-lockfile && pnpm build && cd ..
python scripts/make_examples.py
lexaegis start
```

### Windows（PowerShell）

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

若激活脚本被拦截：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。端口占用或文件锁失败时，先结束旧进程，见 [部署说明](docs/DEPLOY.md)。

打开工作台后输入终端中的本地访问口令。`Ctrl+C` 停止三个服务。不配置模型、不下边侧权重，即可体验三个固定合成案例：

1. 生成披露方案。
2. 检验风险并查看完整请求。四类攻击显示“未运行”不得当作正式通过。当前红队执行器是工程基线，不是正式攻击结论。
3. 批准后执行模拟调用（模拟器组装已披露事实，不声称模型生成）。
4. 逐项回链并确认最终结果。

「组合线索风险」和「主动停止」默认阻断审批。正式案件可上传 `examples/` 下合成 DOCX/PDF，或 UTF-8 文本，体验解析与正式外发阻断。边侧未监听时 `lexaegis start` 会提示，或运行 `lexaegis edge --start`。

## 评测语料、边侧与云端

| 项 | 现状 |
| --- | --- |
| `data/` | 评测语料可作为仓库资产，与运行期 `.data/` 分开。当前 `data/mock_labor_v1` 为 8 条完全合成劳动争议记录。`lexaegis dataset list \| validate \| show \| probe-edge`；`generate-mock \| freeze \| run` 仍写到指定路径。`probe-edge` 只记工程指标，无法学分。`dispatch_allowed` 恒为 false。真实案件与运行库不进 git。 |
| 边侧 | 生产只做事实提取。现行本机单模型 MiniCPM5-2B Q4_K_M 非思考（HF `openbmb/MiniCPM5-2B`，GGUF `MiniCPM5-2B-Q4_K_M.gguf`，服务别名 `edge-small`：`--reasoning-budget 0 --reasoning off --jinja --ctx-size 8192`）。约 4GB 显存，按块抽取。权重不入库，声明在 `models/catalog/`。演示不调边侧。 |
| 云端双槽 | 主 DeepSeek V4 Flash（`deepseek-v4-flash`），备阿里云百炼 Qwen3.8-Flash（`qwen3.8-flash`）。流式只在网关拼完整 JSON，不进工作台。备用仅当已审核且确认请求未离开本地时可用；主方已收包后的超时或 401 记可能披露，不自动换模。一旦有 token，失败记 unknown，禁止自动换模、禁止自动重发。思考关闭。 |
| 密钥 | 只在网关：`LEX_CLOUD_PRIMARY_KEY`（兼容旧名 `LEX_CLOUD_API_KEY`）、`LEX_CLOUD_STANDBY_KEY`。`lexaegis start` 不把云端密钥传给 API/worker。 |
| 工作台 | 运行配置可填主/备并回显；外发目标仍走网关冻结双槽与白名单。审批展示主/备及上述故障转移说明。披露方案可显示「模型建议 · 非规则」。 |

## 配置与运维（摘要）

| 主题 | 文档 |
| --- | --- |
| 边侧小模型、云端双槽、OCR | [docs/MODELS.md](docs/MODELS.md) |
| 边侧模型声明（无权重） | [models/catalog/README.md](models/catalog/README.md) |
| 评测语料 `data/` | [data/README.md](data/README.md)；`lexaegis dataset list \| validate \| show` |
| 云端双槽密钥 | `.env.example`：`LEX_CLOUD_PRIMARY_KEY`（兼容 `LEX_CLOUD_API_KEY`）、`LEX_CLOUD_STANDBY_KEY`；只进网关 |
| 数据目录、备份、Compose 隔离 | [docs/DEPLOY.md](docs/DEPLOY.md) |
| 案由包 `packs/`、任务扩展 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 模拟对照 CLI | `lexaegis dataset generate-mock \| freeze \| run`，报告不作正式效果宣传 |
| 验证命令与本机证据 | [docs/VALIDATION.md](docs/VALIDATION.md) |
| 来源与许可 | [docs/PROVENANCE.md](docs/PROVENANCE.md)、[NOTICE](NOTICE) |
| 界面规范 | [docs/DESIGN.md](docs/DESIGN.md) |
| 历史计划与共识 | [docs/archive](docs/archive/README.md) |

```bash
python -m pytest -q
cd frontend && pnpm build && pnpm exec playwright test
```

本机后端测试以 `python -m pytest -q` 为准（本轮 186 项通过、1 项跳过）。[VALIDATION.md](docs/VALIDATION.md) 记 2026-09-08 的 pytest、前端构建与 `desktop-1280` Playwright。远端 CI 未取得 / 本轮不跑。容器隔离宿主机发布、真实云端 API 仍待目标环境取证。仓库不分发模型权重、真实案件或效果数字。
