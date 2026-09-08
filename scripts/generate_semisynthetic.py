"""Generate the non-real 100-case scaffold; legal labels must be added by people."""
import argparse
from pathlib import Path

from lexaegis.data_registry import write_semi_labor_v1


parser = argparse.ArgumentParser()
parser.add_argument("destination", nargs="?", type=Path, default=None, help="默认 .data/semi_labor_v1")
args = parser.parse_args()
write_semi_labor_v1(args.destination)
print("Created 100 synthetic records; legal annotation and adjudication remain pending.")
