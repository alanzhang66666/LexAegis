"""Export the frozen synthetic LexAegis GRPO adaptation dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.lexaegis_grpo import DEFAULT_RECORDS, load_projected_records


DEFAULT_OUTPUT = ROOT / "training" / "data" / "lexaegis_grpo_synthetic.jsonl"
DEFAULT_MANIFEST = ROOT / "training" / "data" / "manifest.json"


def export(source: Path = DEFAULT_RECORDS, output: Path = DEFAULT_OUTPUT) -> dict:
    rows = load_projected_records(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    ).encode("utf-8")
    output.write_bytes(encoded)
    manifest = {
        "schema_version": 1,
        "dataset": "lexaegis_grpo_synthetic",
        "record_count": len(rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "source": source.relative_to(ROOT).as_posix(),
        "source_kind": "fully_synthetic",
        "training_scope": "output_contract_and_evidence_grounding_only",
        "legal_annotation_status": "pending",
        "checkpoint_status": "not_generated",
        "formal_dispatch_effect": "none",
    }
    manifest_path = output.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    manifest = export(args.source, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

