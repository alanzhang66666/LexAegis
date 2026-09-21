<!-- 由 scripts/export_prompts.py 生成，请勿手工编辑。修改提示词请改 lexaegis/task_engine.py。 -->

# 时间线（`timeline`）

| 项 | 值 |
| --- | --- |
| 任务标识 | `timeline` |
| 任务定义版本 | `2.0` |
| 契约版本 | `schema_version=2` |
| 状态 | `available` |
| 执行方式 | `local_deterministic` |
| 允许的传输 | `local` |
| 输出校验器 | `timeline_v2` |
| 输入上限 | 50000 字符 |

## System prompt

**无提示词。** 该任务为 `local_deterministic`，由 `task_engine.BUILTIN_HANDLERS` 中的本地确定性函数直接计算，不调用任何模型，也不产生对外请求。

## 输入契约

```json
{
  "type": "object",
  "required": [
    "facts"
  ],
  "properties": {
    "facts": {
      "type": "array"
    }
  }
}
```

## 输出契约

```json
{
  "type": "object",
  "required": [
    "events"
  ],
  "properties": {
    "events": {
      "type": "array"
    }
  }
}
```
