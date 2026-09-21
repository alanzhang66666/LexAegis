"""Export the prompts actually used at runtime into prompts/ as reviewable Markdown.

Reads lexaegis.task_engine.registered_tasks() and lexaegis.service.build_system_prompt so the
exported text is the exact string evaluate_task freezes into request.body and hashes as
dependencies.prompt_hash. Never hand-edit prompts/: regenerate it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lexaegis.service import SYSTEM_PROMPT_SUFFIX, build_system_prompt  # noqa: E402
from lexaegis.task_engine import registered_tasks  # noqa: E402

HEADER = "<!-- 由 scripts/export_prompts.py 生成，请勿手工编辑。修改提示词请改 lexaegis/task_engine.py。 -->"


def _fence(payload) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"


def render(definition: dict) -> str:
    lines = [
        HEADER,
        "",
        f"# {definition['name']}（`{definition['id']}`）",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 任务标识 | `{definition['id']}` |",
        f"| 任务定义版本 | `{definition['version']}` |",
        f"| 契约版本 | `schema_version={definition['schema_version']}` |",
        f"| 状态 | `{definition['status']}` |",
        f"| 执行方式 | `{definition['execution_type']}` |",
        f"| 允许的传输 | {'、'.join('`' + item + '`' for item in definition['transports'])} |",
        f"| 输出校验器 | `{definition['validator']}` |",
        f"| 输入上限 | {definition['max_payload_chars']} 字符 |",
        "",
    ]
    if definition.get("prompt_template"):
        lines += [
            "## System prompt（运行时逐字使用）",
            "",
            "下面是 `evaluate_task` 冻结进 `request.body.messages[0].content` 的完整原文，"
            "其哈希记入 `dependencies.prompt_hash`。末段为所有任务共用的固定后缀。",
            "",
            "```text",
            build_system_prompt(definition),
            "```",
            "",
            "### 组成",
            "",
            "任务模板（`task_engine.py` 的 `prompt_template`）：",
            "",
            "```text",
            definition["prompt_template"],
            "```",
            "",
            "固定后缀（`service.SYSTEM_PROMPT_SUFFIX`，对所有任务一致）：",
            "",
            "```text",
            SYSTEM_PROMPT_SUFFIX,
            "```",
            "",
            "## User message",
            "",
            "用户消息不是自由文本，而是 `wire_payload` 的 JSON 序列化结果："
            "`{\"contract_version\": 2, \"task\": {...}, \"facts\": [...]}`。"
            "`facts` 每项仅允许 `id`、`text`、`field` 三个键；"
            "原文、身份映射、`local_text`、`anchors` 一律不上线（见 `cloud.wire_contract_error`）。",
            "",
        ]
    else:
        lines += [
            "## System prompt",
            "",
            "**无提示词。** 该任务为 `local_deterministic`，由 `task_engine.BUILTIN_HANDLERS` 中的"
            "本地确定性函数直接计算，不调用任何模型，也不产生对外请求。",
            "",
        ]
    lines += [
        "## 输入契约",
        "",
        _fence(definition["input_schema"]),
        "",
        "## 输出契约",
        "",
        _fence(definition["output_schema"]),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_index(definitions: list[dict]) -> str:
    lines = [
        HEADER,
        "",
        "# 提示词清单",
        "",
        "本目录是运行时实际使用的提示词，由 `scripts/export_prompts.py` 从"
        "`lexaegis/task_engine.py` 的任务定义与 `lexaegis/service.py` 的固定后缀导出，"
        "与冻结请求逐字一致。请勿手工编辑。",
        "",
        "| 任务 | 标识 | 执行方式 | 是否使用提示词 |",
        "| --- | --- | --- | --- |",
    ]
    for definition in definitions:
        used = "是" if definition.get("prompt_template") else "否（本地确定性）"
        lines.append(
            f"| {definition['name']} | [`{definition['id']}`]({definition['id']}.md) "
            f"| `{definition['execution_type']}` | {used} |"
        )
    lines += [
        "",
        "## 口径",
        "",
        "- 提示词只约束模型输出格式与引用义务，不构成法律判断，也不授予发送权。",
        "- 模型返回结果一律经 `lexaegis/policy.py` 的 `check_claims` 校验引用、数字、身份 token 后才呈现，",
        "  任何改写或新增陈述都会标为 `needs_review` 交人工核对。",
        "- 正式案件的外发另受 `lexaegis/outbound_gate.py` 门禁约束，当前 `formal_dispatch=blocked`。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def export(destination: Path | None = None) -> list[Path]:
    target = Path(destination) if destination else ROOT / "prompts"
    target.mkdir(parents=True, exist_ok=True)
    definitions = [registered_tasks()[key] for key in sorted(registered_tasks())]
    written = []
    for definition in definitions:
        path = target / f"{definition['id']}.md"
        path.write_text(render(definition), encoding="utf-8")
        written.append(path)
    index = target / "README.md"
    index.write_text(render_index(definitions), encoding="utf-8")
    written.append(index)
    return written


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    for item in export(output):
        print("Wrote:", item)
