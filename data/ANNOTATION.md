# 评测标注规范

本目录只收合成或结构抽象后的半合成记录。标注用于回归与对照，**不能**当作正式外发依据。`dispatch_allowed` 必须始终为 `false`。

## 准入

- 每条 `synthetic=true`，数据集 `contains_real_case_content=false`
- 禁止真实文书、可识别当事人、律师工作产品、运行库导出
- 半合成必须已重组人物、金额与可逆对照；未完成重组的材料不得入库

## 双人标注

每条记录至少两名标注人独立填写 `labels[]`，再由第三人写入 `adjudication`。缺任一项，`validate_annotations` 记为问题，不生成法律可用性分数。

每条 label 建议字段：

| 字段 | 说明 |
| --- | --- |
| `annotator` | 具名标注人，不得与另一人相同 |
| `fact_id` | 对应记录内事实 id |
| `field` | `entity` / `relation` / `event` / `date` / `amount` / `evidence` |
| `necessity` | `required` / `conditional` / `unnecessary` / `uncertain`；吃不准就标 uncertain |
| `transform` | `keep` / `pseudonymize` / `generalize` / `delete` |
| `notes` | 可选；不得写入真实身份 |

仲裁只裁定分歧，不发明新的法源。法学包未发布前，标注不得推导 `dispatch_allowed=true`。

## 半合成 100 条

`scripts/generate_semisynthetic.py` 只生成脚手架。标注完成前：

- 不把完整 100 条提交进主库
- 清单保持 `unfrozen_pending_annotation`
- 入库后仍须 `dispatch_allowed=false`

校验与入库门禁：

```text
python -m lexaegis.cli dataset validate
python -m lexaegis.cli dataset promote-semi
```

`promote-semi` 在 `legal_annotation_status` 不是 complete、标注警告非空、`dispatch_allowed` 不为 false、或声明含真实案件内容时拒绝，不写入 catalog。
