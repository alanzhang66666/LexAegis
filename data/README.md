# 评测数据资产

`data/` 是仓库内的版本化评测与回归语料，和 `packs/` 一样进 git。运行期案件、原文、映射和网关账本仍只存在于被忽略的 `.data/`，不要把两套目录混用。本机真实案件材料放在 `.data/real_cases/`，不要拷回本目录或提交进 git。

## 能进库

- 完全合成材料（`kind=fully_synthetic`）
- 仅保留结构抽象、人物与金额均已重组的半合成材料（`kind=structure_abstracted_semisynthetic`）
- 从案由包抽出的规则回归夹具（`kind=pack_regression`）

每份数据集必须：声明 `contains_real_case_content=false` 且每条记录 `synthetic=true`；用 `content_hash` / `records_hash` / `freeze_hash` 冻结；同 `(id, version)` 不可覆盖；`dispatch_allowed` 恒为 `false`。正式外发不得使用这些材料。

## 不能进库

真实文书、可识别当事人、律师工作产品、运行库导出、原文日志、可逆身份对照表，以及「已脱敏但仍是真实案件」的导出。

## 演示材料例外

`recording_adapted/` 是独立的三案离线演示包，不属于评测数据集，不进入 `catalog.json`，也不供正式外发。它包含为本项目演示流程整理的完整 Word 材料和对应事实映射，包含从用户提供案例中保留的原文段落；该目录只用于本仓库指定的演示导入流程。不得把该目录复制到真实运行案件库、评测语料或对外处理请求中。运行时仍只在用户上传后将材料写入被忽略的 `.data/`。

## 当前资产

| 目录 | 说明 |
| --- | --- |
| `mock_labor_v1/` | 由 `build_mock_corpus` + `freeze_mock_corpus` 生成的 8 条确定性虚构劳动争议记录，6:2 开发/盲测划分，法律标注仍为 pending。 |
| `recording_adapted/` | 三份完整版离线演示材料及固定事实映射，上传后按正文哈希匹配；不属于评测集或正式案件资料。 |

后续 `semi_labor_v1` 预留为 100 条半合成脚手架的独立版本：标注未完成前不把完整材料提交进主库，避免体积膨胀和未标注语料被误当成基准。生成脚本仍是 `scripts/generate_semisynthetic.py`，通过同样门禁后再以新版本入库。标注流程见 [ANNOTATION.md](ANNOTATION.md)。

## 校验

```text
python -m lexaegis.cli dataset list
python -m lexaegis.cli dataset validate
python -m lexaegis.cli dataset show mock_labor
python -m lexaegis.cli dataset compare
python -m lexaegis.cli dataset labels-template --output .data/labels-pending.json
python -m lexaegis.cli dataset probe-edge
python -m lexaegis.cli dataset promote-semi
```

`promote-semi [src] [data-root]` 在标注完成、警告清空、且 `dispatch_allowed` / `contains_real_case_content` 均为 false 时才复制到 `data/semi_labor_v1` 并写 catalog；否则拒绝，不改主库。

`probe-edge` 对 `mock_labor` 调已有 `EdgeClient.extract`，只记 JSON / `source_ids` / `quote` / 数字 / 别名等工程指标，**不打法律可用性分**。报告写到被忽略的 `.data/edge-probe/`。未配置或未启动 llama-server 时状态为 `unconfigured`，退出码 0，不把整个 `doctor` 失败关闭。

`compare` 在同一攻击预算下对五组方法做离线对照：查找替换、一致假名化、当前任务矩阵、通用 generalize/删除薄基线、以及 Phase 2 法律约束候选。原文只作本地效用参照和隔离阳性对照，不送公共搜索。8 条是冒烟规模，不是代表性结论；双人标注仍为 pending，`labels-template` 只写出空 schema。报告只写分子/分母与失败类，不生成法律可用性分、隐私降低率或 AURA 数字，也不宣布方法胜出。正式外发保持 `dispatch_allowed=false`。

`generate-mock` / `freeze` / `run` 仍写到调用方指定路径，且禁止覆盖；它们不会自动改写本目录。
