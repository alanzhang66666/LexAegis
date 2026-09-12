"""Backfill pilot issue rulings from G-2026-09-12-v1.0. No case text."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PILOT = Path(__file__).resolve().parents[1] / ".data" / "real_cases" / "runs" / "pilot-2026-09"
GUIDE = "G-2026-09-12-v1.0"
SRC_RULING = (
    f"{GUIDE} G1：无文书锚点不得伪造回链；该行留在答案层，不进入文书事实输出。"
    "不是外发授权，也不把参考摘要当作判决原文。"
)
EXTRACT_RULING = (
    f"{GUIDE} G3：边侧抽取是未确认草稿。当时失败为截断 JSON，工程已用分批与引用校验修复；"
    "修复后的入库条仍须机械确认，不得标成已校对。"
)
G2_RULING = f"{GUIDE} G2：保护对象分类与案由字段分栏；证件号/手机等作主体属性，不进本期摘要候选。"
G4_RULING = f"{GUIDE} G4：未明确必要性不进入披露候选；必要内容被删光记 blocked，不按零泄露计成功。"
G5_RULING = f"{GUIDE} G5：主体名称在全部字段一致替换，替换后查残留；残留不得进入可发送文本。"


def main() -> None:
    path = PILOT / "issues" / "issues.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    updated = []
    counts = Counter()
    for row in rows:
        issue_id = row.get("issue_id") or ""
        if row.get("ruling"):
            updated.append(row)
            counts["kept"] += 1
            continue
        if issue_id.endswith("-EXTRACT") or "-EXTRACT" in issue_id:
            row["ruling"] = EXTRACT_RULING
            row["guide_version"] = GUIDE
            counts["g3_extract"] += 1
        elif row.get("actual") == "content_not_in_source_blocks" or issue_id.endswith("-SRC"):
            row["ruling"] = SRC_RULING
            row["guide_version"] = GUIDE
            counts["g1_src"] += 1
        else:
            counts["unmapped"] += 1
        updated.append(row)
    extras = [
        {
            "issue_id": "GUIDE-G2-FIELD-SPLIT",
            "path": "guide",
            "actual": "inventory_type_not_fact_field",
            "expected": "split type vs field",
            "impact": "unmapped Path B rows stay out of fact table",
            "tags": ["规则"],
            "ruling": G2_RULING,
            "guide_version": GUIDE,
        },
        {
            "issue_id": "GUIDE-G4-EMPTY-WIRE",
            "path": "guide",
            "actual": "uncertain_default_cleared_wire",
            "expected": "required wipe is blocked",
            "impact": "B0 empty wire is conservative control, not success",
            "tags": ["规则"],
            "ruling": G4_RULING,
            "guide_version": GUIDE,
        },
        {
            "issue_id": "GUIDE-G5-REGISTERED-NAME",
            "path": "guide",
            "actual": "registered_name_in_non_entity_fields",
            "expected": "cross-field replace then residual scan",
            "impact": "layer A blocker 仍包含未替换的登记主体",
            "tags": ["规则"],
            "ruling": G5_RULING,
            "guide_version": GUIDE,
        },
    ]
    existing = {row.get("issue_id") for row in updated}
    for item in extras:
        if item["issue_id"] not in existing:
            updated.append(item)
            counts["guide_extra"] += 1
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in updated), encoding="utf-8")
    summary = {
        "guide_version": GUIDE,
        "n_rows": len(updated),
        "counts": dict(counts),
        "send": "not_called",
    }
    (PILOT / "issues" / "rulings.G-2026-09-12-v1.0.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
