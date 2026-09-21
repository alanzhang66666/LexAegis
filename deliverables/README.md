# deliverables/ · 交付物与生成物

本目录不入库（`deliverables/*` 已 gitignore，仅本 README 入库）。放比赛交付包、功能截图、归档案例包与第三方参考代码。**本目录任何文件都不是发送授权**；不写「已通过 / 外发已开通」口径。

| 子目录 | 内容 | 来源 / 重建方式 |
| --- | --- | --- |
| `competition_submission/` | 比赛「智能体作品及完整材料」版（含 12G 打包 zip） | `python scripts/build_submission.py`（默认输出于此） |
| `开源代码/`、`开源代码.zip` | 比赛第 5 项源码快照 | `python scripts/build_submission.py --item5` |
| `本科生组-…-案隐盾—云边协同…/` | 人工装配的最终提交夹（1–6 项，含成员 PDF 与网盘链接） | 手工维护，不可重建 |
| `三案例流程文件包_1.1/` | LA-001/002/003 本地工作台归档（见该包 `00_总览/README.md`） | 手工归档，不直接提交 |
| `系统截图/功能页面/` | 五个功能页面截图（操作手册与比赛包共用素材） | `node scripts/capture_competition_function_pages.cjs`（需 18765 栈） |
| `reference/AgentCourt/` | 第三方 AgentCourt 参考仓 | 外部来源，只读参考，不进提交包 |

注意：`build_submission.py` 打包时会把 `系统截图/功能页面/` 复制进比赛包 `examples/four_boundary_demo/`；重新截图后须重跑 build_submission 才会生效。
