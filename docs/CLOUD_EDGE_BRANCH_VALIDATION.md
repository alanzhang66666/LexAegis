# 云边演示分支：迁移与验证

本分支基于 main 9237d3a，迁入本地尚未提交的验收/诊断修复、云网关部署、Windows 联调工具，以及仓库外登记文档演示、系统全称、共享额度、受限模型进程、固定目标代理和隧道保留修复。保留主线新增的 V3 字节绑定、审批、重新授权及一次性许可行为，没有用旧部署副本覆盖主线。

## 公开范围

公开源码、必要静态资源、空配置模板及全新合成测试。原件、具体案例清单、模型权重、密钥、口令、Cookie、运行库、发送账本、截图和真实收据留在私有运行目录，不进入 Git。过去的本机测评文档仅是注明日期的历史描述，不作为本分支新验收。

登记能力只在 integration 加载私有哈希清单后出现。API、worker 和网关分别加载同一份清单，不依赖单进程的全局注册副作用；独立 worker 仍按原运行范围核验案件。正式案件不获得登记演示例外。

## 验证方法

```powershell
python -m pytest -q --junitxml=.artifacts/backend.xml
cd frontend
pnpm install --frozen-lockfile
pnpm build
pnpm exec playwright install chromium
pnpm exec playwright test --project=desktop-1280 --grep-invert five-viewport
pnpm exec playwright test --config=playwright.v3-gate.config.ts
pnpm exec playwright test --config=playwright.v3-grade.config.ts
pnpm exec playwright test --config=playwright.v3-reapproval.config.ts
```

登记端到端测试由 tests/test_workbench_docker.py 显式启动独立容器，包含回环转发/路由守卫、原登录、哈希上传、文档解析、桩模型抽取、来源定位、人工确认及云任务草稿。另有 Python 完整链路用例经过真实应用的复核、审批、签名网关和来源确认，服务商以本地 provider 桩替代；核对冻结请求哈希与实际准备的 HTTP 字节哈希，不发送真实 DeepSeek 请求。

Docker 测试使用独立项目名、测试卷、端口、全新合成数据和桩模型/桩隧道。强制重建原站后核对隧道容器 ID、StartedAt 不变，并实测应用、网关和本地入口的 IPv4/IPv6 普通出口拒绝。测试只停止自己的容器，保留账本卷；不操作正在运行的演示实例。

其他负向测试覆盖未知文件、禁用开关、清单篡改、production 拒绝、来源/原文不匹配、未确认候选、旧批准失效、正文篡改、无签名、重复发送、并发超额、额度重启连续性、超时未知不退款、流元数据和跨浏览器会话隔离。

## 结果口径

2026-11-03，本分支独立 Windows 检出中的本地实测：

| 检查 | 实际结果 |
| --- | --- |
| 完整后端回归 | 1147 passed / 6 skipped，220.77 秒；包含主线 V3 与登记文档完整模拟收发、来源确认 |
| 后续新增及调整的定向检查 | 22 passed，与完整回归有重叠；含导出扫描、不接管未配置宿主模型、零额度网关与登记完整模拟链路 |
| 前端 | TypeScript/Vite 构建通过 |
| 原工作台浏览器 | 11 passed / 3 skipped；跳过为生产专属及需要独立登记环境的用例 |
| V3 四门、分级和重新批准组件 | 分别 7、8、4 passed |
| 登记文档浏览器 | 1 passed；经私有清单、哈希上传、解析、桩抽取、来源定位、人工确认和任务草稿 |
| 独立 Docker 冒烟 | 1 passed，包含上一行浏览器测试；原站重建保留桩隧道会话、三类进程 IPv4/IPv6 出口拒绝 |
| 服务商生成 | 0 次；模型、服务商和隧道分别采用明确的本地测试桩，不冒充真实云收据 |

这些检查存在覆盖重叠，不相加宣称独立验收项总数。Docker 冒烟需要显式启用，所以完整后端默认将其列为跳过；其他跳过按原测试条件保留。原环境的 750 项通过未复制为本分支结果。

源码镜像和自动化测试不是正式 verified 构建身份，目标云主机、跨主机隔离、实际模型质量和正式案件发送授权保持未验证或阻断。GitHub CI 的不同平台结果以对应提交的工作流为准，不用本机结果补记未运行平台。

本次验证真实 DeepSeek 生成请求为 0。既有运行服务、账号、原件、发送账本及调用额度不参与本分支测试。
