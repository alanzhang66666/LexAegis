"""Generate the non-real 100-case scaffold; legal labels must be added by people."""
import argparse
import json
from pathlib import Path

from lexaegis.dataset import build_semisynthetic_manifest


parser=argparse.ArgumentParser()
parser.add_argument("destination",type=Path)
args=parser.parse_args()
args.destination.mkdir(parents=True,exist_ok=False)
records,manifest=build_semisynthetic_manifest()
(args.destination/"cases.jsonl").write_text("\n".join(json.dumps(record,ensure_ascii=False) for record in records)+"\n",encoding="utf-8")
(args.destination/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Created 100 synthetic records; legal annotation and adjudication remain pending.")
