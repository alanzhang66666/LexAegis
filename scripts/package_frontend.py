"""Copy a verified Vite build into the Python package before building a wheel."""
from pathlib import Path
import shutil


root = Path(__file__).resolve().parent.parent
source = root / "frontend" / "dist"
target = root / "lexaegis" / "frontend"
if not (source / "index.html").exists():
    raise SystemExit("请先在 frontend 运行 pnpm build")
if target.exists():
    shutil.rmtree(target)
shutil.copytree(source, target)
print(f"Packaged frontend: {target}")
