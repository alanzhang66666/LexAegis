# 来源与许可说明

产品边界来自归档共识 [CONSENSUS-2026-09-04](archive/CONSENSUS-2026-09-04.md) 与当时的实现计划 [PLAN-0.2](archive/PLAN-0.2.md)。现行行为以 [架构说明](ARCHITECTURE.md) 为准。分发构建产物时须保留根目录 [NOTICE](../NOTICE) 与 [LICENSES/](../LICENSES/)。

## 第三方来源

| 来源 | 许可证/状态 | 使用方式 |
| --- | --- | --- |
| kubeedge/ianvs PR #283，固定参考提交 `8150672e6c8abcecfefd1f8377e5e40b17d7ace9` | Apache-2.0 | 借鉴检测区间、风险分项、审计与实验结构；本项目重写并删除生产模型调用、跨境自动结论、伪向量与固定指标 |
| kubeedge/ianvs PR #282 | Apache-2.0 | 仅作为实验方案与文档参考 |
| TracyWang95/DataInfra-RedactionEverything 及当前重定向仓库 | Personal Use License | 只借鉴产品问题与交互思想；不复制代码、不加入依赖树 |
| HU-UH/awesome-design-md | MIT；品牌说明为非官方提取 | 仅参考通用界面方法，形成原创 [DESIGN.md](DESIGN.md) 与 Token |

Ianvs 的 `PrivacyPreservingLLM` 总编排未移植。生产链只采用确定性 PII/风险/审计结构；DP、显著性掩码、随机投影和 MIA 契约只存在于隔离实验模块。所有实验必须使用真实向量或目标模型输出。

## 本仓库资产

- `examples/` 与内置三个演示案例都是新建的合成数据，不对应真实当事人；它们只证明功能路径，不证明匿名化、法律适用性或模型效果。
- `packs/labor_demo.json` 是未正式审核的演示规则；`contract_test.json` 是扩展测试资产；`labor_v2_draft.json` 在保守缺省之上叠加加班核对条件规则，仍为待审草稿，`dispatch_allowed=false`。三者都不能充当正式法律依据。
- `data/` 只收完全合成、结构抽象半合成或案由包回归夹具，与运行期 `.data/` 分开。入库材料须声明 `contains_real_case_content=false`，冻结内容哈希，同版本不可覆盖，且 `dispatch_allowed` 恒为 false。当前 `data/mock_labor_v1/` 是 8 条确定性虚构劳动争议记录，只服务技术对照；未标注的半合成完整材料不进入主库。
- 不随仓库分发任何模型权重、API 密钥、真实案件、运行数据库、原文日志或本地访问口令。

项目通过包管理器使用 React、Vite、TypeScript、Lucide、FastAPI、SQLAlchemy、Alembic、Pydantic、HTTPX、python-docx、pypdfium2、Pillow、pytest 和 Playwright 等依赖；实际版本见 `frontend/pnpm-lock.yaml` 与 `requirements.lock`。上游软件、传递依赖及二进制的许可文件随原始包保留。pypdfium2 包含 PDFium 二进制，其第三方声明应一并保留。

PaddleOCR / PaddlePaddle 和边侧模型权重为可选的后续安装资源，运行前需分别检查硬件、离线资源及相应许可。Compose 中的 llama.cpp 镜像只是可配置运行入口，没有作为已验证的模型资源随代码提供。

仓库暂不添加开源许可证，不因仓库可访问性作出第三方授权主张。
