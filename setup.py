"""Setuptools build hook: ship the verified UI, built-in packs, and notice."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


ROOT = Path(__file__).resolve().parent


class build_py(_build_py):
    def run(self):
        super().run()
        frontend = ROOT / "frontend" / "dist"
        if not (frontend / "index.html").exists():
            raise RuntimeError("frontend/dist is missing; run pnpm build before building the Python wheel")
        shutil.copytree(frontend, Path(self.build_lib) / "lexaegis" / "frontend", dirs_exist_ok=True)
        shutil.copytree(ROOT / "packs", Path(self.build_lib) / "lexaegis" / "packs", dirs_exist_ok=True)
        shutil.copytree(ROOT / "LICENSES", Path(self.build_lib) / "lexaegis" / "LICENSES", dirs_exist_ok=True)
        shutil.copy2(ROOT / "NOTICE", Path(self.build_lib) / "lexaegis" / "NOTICE")


setup(cmdclass={"build_py": build_py})
