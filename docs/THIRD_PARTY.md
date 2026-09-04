# 第三方来源台账

| 来源 | 许可证/状态 | 使用方式 |
| --- | --- | --- |
| kubeedge/ianvs PR #283，固定参考提交 `8150672e6c8abcecfefd1f8377e5e40b17d7ace9` | Apache-2.0 | 借鉴检测区间、风险分项、审计与实验结构；本项目重写并删除生产模型调用、跨境自动结论、伪向量与固定指标 |
| kubeedge/ianvs PR #282 | Apache-2.0 | 仅作为实验方案与文档参考 |
| TracyWang95/DataInfra-RedactionEverything 及当前重定向仓库 | Personal Use License | 只借鉴产品问题与交互思想；不复制代码、不加入依赖树 |
| HU-UH/awesome-design-md | MIT；品牌说明为非官方提取 | 仅参考通用界面方法，形成原创 `DESIGN.md` 与 Token |

Ianvs 的 `PrivacyPreservingLLM` 总编排未移植。生产链只采用确定性 PII/风险/审计结构；DP、显著性掩码、随机投影和 MIA 契约只存在于隔离实验模块。所有实验必须使用真实向量或目标模型输出。

依赖的精确版本记录在 `requirements.lock` 与 `frontend/pnpm-lock.yaml`。仓库不分发模型权重、密钥、真实案件、真值目录或运行数据库。
