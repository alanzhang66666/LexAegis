# 边侧模型接口（比赛版 bundled）

当前比赛版默认随包提供本机可运行的 Qwen3-4B GRPO GGUF、规范命名的 safetensors、tokenizer、
可选 LoRA 复现实验资产和 Windows `llama-server` 运行器。完整来源、逐文件哈希、排除项和许可
待确认事项见 `models/edge/qwen3-4b-grpo/ASSET_MANIFEST.json`。

模型完整性与本机接口可验证，但不表示模型质量、法律适用性、目标硬件或正式外发已经验收。最终
LoRA 不会被自动叠加到可能已融合的 GGUF 或 Transformers 权重上。

## 配置

```dotenv
LEX_EDGE_URL=http://127.0.0.1:8080/v1
LEX_EDGE_MODEL=lexaegis-qwen3-4b-grpo
LEX_EDGE_GGUF=models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf
LEX_EDGE_OUTBOUND_REVIEW=1
```

也可在工作台“运行配置”页面填写。端点应仅在本机或经过隔离验证的受控网络中提供。
未配置、健康检查失败或审核协议不合格时，系统保持失败关闭：不把原文发送到其他模型，事实改由
人工录入或停止当前操作。

## OpenAI-compatible `/v1` 契约

### `GET /v1/models`

服务应返回 OpenAI-compatible 模型列表，且 `data[].id` 至少包含
`LEX_EDGE_MODEL` 所指模型。健康检查只证明接口可访问，不代表模型质量或法律适用性通过。

### `POST /v1/chat/completions`

请求采用 `messages`，并要求结构化 JSON 输出。核心约束如下：

- `model` 与 `LEX_EDGE_MODEL` 一致；
- 抽取请求使用确定性配置，并给出 JSON Schema；
- 输出只包含从本地材料提取的候选事实，不作最终法律判断；
- 每条候选事实须携带可回链的来源标识或可核验引文；
- 无法解析、来源不匹配、截断或超时时不得自动放行外发。

除事实抽取外，系统还使用一个严格的边侧审核对象：

```json
{
  "decision": "block_external | allow_human_review",
  "reason": "简短审核理由",
  "risk_codes": ["有限风险代码"],
  "evidence_fact_ids": ["仅限当前输入的事实 id"]
}
```

`allow_human_review` 只表示可以进入人工复核；它不能直接批准、发送或改变正式外发 `blocked` 状态。
协议解析失败时一律视作 `block_external`。

典型响应仍使用 OpenAI-compatible 外壳：

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "{\"facts\": []}"
      }
    }
  ]
}
```

实际字段上限、二次抽取和失败处理以 `lexaegis/edge_eval.py`、
`lexaegis/edge_runtime.py` 及测试为准。

### 本地安全基线

`allow_human_review` 只表示可以进入人工复核；它不能直接批准、发送或改变正式外发 `blocked` 状态。协议解析失败时一律视作 `block_external`。对未脱敏身份证号、手机号与直接标识/精确组合线索，系统还会应用本地安全基线；即使模型原始结论为 `allow_human_review`，最终边侧审核仍会改为 `block_external`，并保留 `model_decision` 和 `safety_floor` 以供审计，避免将模型误判表述为允许。

## 离线模拟与验证

不启动真实边侧服务也可以运行内置合成演示；固定场景默认使用可审计的合成固定审核，不能作为某一
模型的质量证据。设置 `LEX_DEMO_LIVE_EDGE_REVIEW=1` 后可让已启动的本机模型审核合成场景。
接口测试可执行：

```bash
python -m pytest -q tests/test_edge_eval.py tests/test_edge_provider.py
```

## 运行器

从比赛包根目录执行 `python -m lexaegis.cli edge --start`。默认会使用
`container/edge-runtime/windows/llama-server.exe` 和随包 GGUF；也可用 `LEX_EDGE_BIN`、
`LEX_EDGE_GGUF` 覆盖。启动后先检查 `/v1/models`，再启动工作台。

后续若更换或补充模型，须使用 `--model-mode bundled` 重新装配，并同时更新来源、许可、固定版本、
逐文件 SHA-256、训练清单、导出参数和目标硬件验证记录。不得将缓存、未登记检查点或不完整快照
混入交付包。
