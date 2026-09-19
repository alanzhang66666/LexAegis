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
        "lexaegis/packs/labor_product_draft.json",
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
    source_root = Path(__file__).resolve().parent.parent
    for directory in ("frontend", "packs", "LICENSES"):
        source = source_root / ("frontend/dist" if directory == "frontend" else directory)
        expected = {f"lexaegis/{directory}/{path.relative_to(source).as_posix()}": path
                    for path in source.rglob("*") if path.is_file()}
        actual = {name for name in names if name.startswith(f"lexaegis/{directory}/") and not name.endswith("/")}
        if not expected or actual != set(expected):
            raise SystemExit(f"wheel {directory} differs from current build assets (missing or stale files)")
        if any(archive.read(name) != path.read_bytes() for name, path in expected.items()):
            raise SystemExit(f"wheel {directory} content differs from current build assets")
print(f"verified self-contained wheel: {wheels[0].name}")
