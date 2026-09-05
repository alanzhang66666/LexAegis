# LexAegis · 案隐盾

云边协同的法律材料披露工作台：边侧整理原文与身份映射，律师批准完整请求后，由独立网关调用云端大模型 API，结果回到边侧校核和回链。

**当前版本：0.2.0。** 工作台、V2 契约、稳定 wire token、门禁与跨平台 CLI 已进入代码。法学规则尚未发布、真实攻击与隔离尚未验收，因此**正式案件的外发保持阻断**。演示只接受内置合成材料。

文档地图见 [docs/README.md](docs/README.md)。架构与门禁见 [架构说明](docs/ARCHITECTURE.md)。

## 快速启动

运行已构建 wheel 只需 Python 3.12+；从源码开发前端需要 Node.js 22+ 和 pnpm 11。请使用 **http://127.0.0.1:8765**，不要用 `localhost`。

### Linux / macOS

`requirements.lock` 用环境标记排除 Windows 不支持的 `uvloop`。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
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

打开工作台后输入终端中的本地访问口令。`Ctrl+C` 停止三个服务。不配置模型即可体验三个固定合成案例：

1. 生成披露方案。
2. 检验风险并查看完整请求。四类攻击显示“未运行”不得当作正式通过。
3. 批准后执行模拟调用（模拟器组装已披露事实，不声称模型生成）。
4. 逐项回链并确认最终结果。

「组合线索风险」和「主动停止」默认阻断审批。正式案件可上传 `examples/` 下合成 DOCX/PDF，体验解析与正式外发阻断。

## 配置与运维（摘要）

| 主题 | 文档 |
| --- | --- |
| 边侧小模型、云端 API、OCR | [docs/MODELS.md](docs/MODELS.md) |
| 数据目录、备份、Compose 隔离 | [docs/DEPLOY.md](docs/DEPLOY.md) |
| 案由包 `packs/`、任务扩展 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 模拟数据集 CLI | `lexaegis dataset generate-mock \| freeze \| run`，报告不作正式效果宣传 |
| 验证命令与本机证据 | [docs/VALIDATION.md](docs/VALIDATION.md) |
| 来源与许可 | [docs/PROVENANCE.md](docs/PROVENANCE.md)、[NOTICE](NOTICE) |
| 界面规范 | [docs/DESIGN.md](docs/DESIGN.md) |
| 历史计划与共识 | [docs/archive](docs/archive/README.md) |

```bash
python -m pytest -q
cd frontend && pnpm build && pnpm exec playwright test
```

本机验证为 **75** 项后端测试通过，前端构建与五视口浏览器检查通过。容器隔离与三平台远端 CI 仍待目标环境取证。仓库不分发模型权重、真实案件或效果数字。
