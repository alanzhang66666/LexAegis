# 来源与许可说明

- 当前产品边界来自用户提供的《案隐盾_项目核心共识与系统架构.md》和本次确认的首版实现计划。
- 本轮新增实现没有复制或集成 DataInfra-RedactionEverything、Ianvs PR #282 / #283 的代码。
- `examples/` 与内置三个演示案例都是新建的合成数据，不对应真实当事人；它们只证明功能路径，不证明匿名化、法律适用性或模型效果。
- `packs/labor_demo.json` 是未正式审核的演示规则；`contract_test.json` 是扩展测试资产。二者不能充当正式法律依据。
- 不随仓库分发任何模型权重、API 密钥、真实案件、运行数据库、原文日志或本地访问口令。

项目通过包管理器使用 React、Vite、TypeScript、Lucide、FastAPI、SQLAlchemy、Alembic、Pydantic、HTTPX、python-docx、pypdfium2、Pillow、pytest 和 Playwright 等依赖；实际版本见 `frontend/pnpm-lock.yaml` 与 `requirements.lock`。上游软件、传递依赖及二进制的许可文件随原始包保留，分发构建产物时仍需保留相应声明。pypdfium2 包含 PDFium 二进制，其第三方声明应一并保留。

PaddleOCR / PaddlePaddle 和边侧模型权重为可选的后续安装资源，运行前需分别检查硬件、离线资源及相应许可。Compose 中的 llama.cpp 镜像只是可配置运行入口，没有作为已验证的模型资源随代码提供。

仓库暂不添加开源许可证，不因仓库可访问性作出第三方授权主张。
