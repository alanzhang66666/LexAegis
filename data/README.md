# 评测数据资产

`data/` 是仓库内的版本化评测与回归语料，和 `packs/` 一样进 git。运行期案件、原文、映射和网关账本仍只存在于被忽略的 `.data/`，不要把两套目录混用。

## 能进库

- 完全合成材料（`kind=fully_synthetic`）
- 仅保留结构抽象、人物与金额均已重组的半合成材料（`kind=structure_abstracted_semisynthetic`）
- 从案由包抽出的规则回归夹具（`kind=pack_regression`）

每份数据集必须：声明 `contains_real_case_content=false` 且每条记录 `synthetic=true`；用 `content_hash` / `records_hash` / `freeze_hash` 冻结；同 `(id, version)` 不可覆盖；`dispatch_allowed` 恒为 `false`。正式外发不得使用这些材料。

## 不能进库

真实文书、可识别当事人、律师工作产品、运行库导出、原文日志、可逆身份对照表，以及「已脱敏但仍是真实案件」的导出。

## 当前资产

| 目录 | 说明 |
| --- | --- |
| `mock_labor_v1/` | 由 `build_mock_corpus` + `freeze_mock_corpus` 生成的 8 条确定性虚构劳动争议记录，6:2 开发/盲测划分，法律标注仍为 pending。 |

后续 `semi_labor_v1` 预留为 100 条半合成脚手架的独立版本：标注未完成前不把完整材料提交进主库，避免体积膨胀和未标注语料被误当成基准。生成脚本仍是 `scripts/generate_semisynthetic.py`，通过同样门禁后再以新版本入库。标注流程见 [ANNOTATION.md](ANNOTATION.md)。

## 校验

```text
python -m lexaegis.cli dataset list
python -m lexaegis.cli dataset validate
python -m lexaegis.cli dataset show mock_labor
python -m lexaegis.cli dataset probe-edge
python -m lexaegis.cli dataset promote-semi
```

`promote-semi [src] [data-root]` 在标注完成、警告清空、且 `dispatch_allowed` / `contains_real_case_content` 均为 false 时才复制到 `data/semi_labor_v1` 并写 catalog；否则拒绝，不改主库。

`probe-edge` 对 `mock_labor` 调已有 `EdgeClient.extract`，只记 JSON / `source_ids` / `quote` / 数字 / 别名等工程指标，**不打法律可用性分**。报告写到被忽略的 `.data/edge-probe/`。未配置或未启动 llama-server 时状态为 `unconfigured`，退出码 0，不把整个 `doctor` 失败关闭。

`generate-mock` / `freeze` / `run` 仍写到调用方指定路径，且禁止覆盖；它们不会自动改写本目录。
