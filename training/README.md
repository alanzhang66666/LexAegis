# Qwen3-4B GRPO 适配成果

本目录把固定的 Unsloth `Qwen3_(4B)-GRPO.ipynb` 适配到 LexAegis `fact_summary v2` 契约。
适配范围是输出 JSON、事实引用、`unused_fact_ids` / `gaps`、身份 Token 保真和禁止新增标识；
不训练或奖励法律结论。

当前可核验成果：

- 固定的公开 Qwen3-4B 基座权重与逐文件 SHA-256；
- 固定提交、固定 SHA-256 的上游 GRPO Notebook；
- 8 条完全合成记录的训练投影；
- 直接复用运行时 `validate_cloud_result` 的确定性奖励器；
- 训练后 `merged_16bit` / `merged_4bit` / `GGUF q4_k_m` 导出约定。

`data/manifest.json` 的 `checkpoint_status=not_generated` 是有意的：当前环境没有执行 GPU 训练，
因此不得把基座权重或 Notebook 输出截图写成 LexAegis 已训练 checkpoint。运行固定 Notebook 时，
以 `training.lexaegis_grpo.contract_grounding_reward` 替换数学奖励函数，并加载
`data/lexaegis_grpo_synthetic.jsonl`。训练结束后必须保存训练日志、环境冻结清单、导出权重及
逐文件 SHA-256，再把状态升级为 `generated_unverified`；只有独立评估通过后才能写 `verified`。

这 8 条数据的法学标注仍为 `pending`，只能用于格式与证据归属适配，不能支持法律准确率结论。

