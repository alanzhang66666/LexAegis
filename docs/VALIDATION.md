# 0.2 验证记录

验证日期：2026-09-05。当前实现验证设备为 Windows / AMD64、Python 3.13.2；此前 0.1 浏览器基线来自 macOS / Apple Silicon。此文件只记录实际运行证据，不填充隐私风险降低率或摘要准确率等效果数字。

## 已实现并验证

| 验证 | 结果 |
| --- | --- |
| `python -m pytest -q` | 35 项通过，无弃用警告 |
| TypeScript 类型检查与 Vite 生产构建 | 通过 |
| Python wheel 构建与归档检查 | 通过；包含前端、V2 包与 NOTICE |
| Chrome Playwright 浏览器验收 | 0.1 的 4 条流程通过；0.2 五视口矩阵待 CI/目标环境重跑 |
| 桌面、390px 移动端布局 | 截图检查；移动配置页无横向溢出 |
| DOCX 段落/表格、文本与混合 PDF、扫描页检测 | 解析和来源定位测试通过 |
| 无 OCR 环境下保留扫描页及复核状态 | 通过 |
| 材料校正和历史版本回链、重启恢复 | 通过 |
| 审批失效、未审批阻断、并发重复提交 | 通过 |
| 网关签名、请求摘要、重复请求去重 | 通过 |
| 超时和崩溃结果不明、只查询不重发 | 通过 |
| 累计披露使另一任务旧审批失效 | 通过 |
| 案件假名隔离、演示模式禁止用户材料 | 通过 |
| 无依据数字/引用阻断自动确认 | 通过 |
| 备份、恢复、材料与审批/发送记录关联 | 通过 |
| 新案由包导入、版本不可覆盖 | 通过 |
| 红队边侧字段拒绝、冻结协议与数据驱动结果 | 通过 |
| 0001 数据迁移前备份、完整性、失败回滚 | 通过 |
| 稳定 token、双轨导出、本地导出二次确认 | 通过 |
| DP 裁剪/RDP 组合、投影复现、MIA 无输入不伪造 | 通过 |

浏览器流程：固定合成案例完成披露、审批、模拟发送、逐项原文校核和最终确认；组合线索场景阻断；正式 DOCX 上传和人工事实管理后阻断正式外发；运行配置与移动端布局检查。

截图保存在本机 `.data/acceptance-dashboard.png`、`.data/acceptance-result.png` 和 `.data/acceptance-mobile.png`，不提交运行数据目录。验收测试使用自带合成材料，没有真实案件材料。

## 已实现，等待配置或目标环境验证

- 边侧 OpenAI-compatible 提取接口及 JSON / 引用校验：没有可调用的本地小模型，未做真实推理验证。
- 云端网关和 OpenAI-compatible 适配器：使用测试替身验证控制路径，未提供 API 密钥，未实际调用云端模型。
- PaddleOCR 3.x 适配器：没有安装引擎或模型权重；未验证真实 OCR 推理、识别精度或硬件兼容性。
- Dockerfile、Compose 内外网隔离及验收命令：当前未安装 Docker；`lexaegis check-isolation` 已验证会失败关闭且不写入验收记录，尚未运行容器构建或真实网络隔离验收。
- GitHub Actions 已定义 Windows/macOS/Linux 与 linux/amd64、linux/arm64 构建矩阵；尚无远端运行结果。

## 明确占位

正式法律规则发布、四类攻击的经批准真实运行、双人标注与第三人仲裁、独立盲测效果、完整语义事实核验、多账户管理、证据目录和争点提取。时间线已实现为本地确定性任务。正式外发虽有完整门禁路径，但当前没有满足所有门槛的资产与验收记录。

## 复现浏览器验收

先构建前端，然后启动单独的验收数据目录，避免混入使用者案件。下面的口令只用于本机合成验收：

```bash
LEX_DATA_DIR=.data/acceptance-app \
LEX_GATEWAY_DIR=.data/acceptance-gateway \
LEX_LOCAL_PASSWORD=local-acceptance-only \
LEX_GATEWAY_SECRET=local-acceptance-gateway-secret \
python scripts/dev.py
```

另开终端：

```bash
cd frontend
pnpm exec playwright test
```

默认使用已安装的 Chrome。没有 Chrome 时先安装浏览器，或将 Playwright 配置改成已安装的 Chromium。浏览器验收不会访问云端模型。
