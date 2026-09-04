"""Verify that a built wheel is a self-contained runtime distribution."""
import sys
import zipfile
from pathlib import Path


root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
wheels = list(root.glob("lexaegis-*.whl"))
if len(wheels) != 1:
    raise SystemExit(f"expected one LexAegis wheel in {root}, found {len(wheels)}")
with zipfile.ZipFile(wheels[0]) as archive:
    names = set(archive.namelist())
    required_suffixes = (
        "lexaegis/frontend/index.html",
        "lexaegis/packs/labor_demo.json",
        "lexaegis/packs/labor_v2_draft.json",
        "lexaegis/NOTICE",
        "lexaegis/LICENSES/Apache-2.0.txt",
    )
    missing = [
        suffix for suffix in required_suffixes
        if not any(name.endswith(suffix) for name in names)
    ]
    if missing:
        raise SystemExit("wheel is missing runtime assets: " + ", ".join(missing))
    if not any(name.startswith("lexaegis/frontend/assets/") and name.endswith(".js") for name in names):
        raise SystemExit("wheel has no built frontend JavaScript asset")
print(f"verified self-contained wheel: {wheels[0].name}")
