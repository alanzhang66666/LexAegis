"""Setuptools build hook: ship the verified UI, built-in packs, and notice."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


ROOT = Path(__file__).resolve().parent


class build_py(_build_py):
    def run(self):
        frontend = ROOT / "frontend" / "dist"
        if not (frontend / "index.html").exists():
            raise RuntimeError("frontend/dist is missing; run pnpm build before building the Python wheel")
        package = Path(self.build_lib) / "lexaegis"
        # Repeated builds must not ship retired modules, packs or hashed UI assets.
        # This is setuptools' generated staging directory, never source/runtime data.
        if package.exists():
            shutil.rmtree(package)
        super().run()
        shutil.copytree(frontend, package / "frontend")
        shutil.copytree(ROOT / "packs", package / "packs")
        shutil.copytree(ROOT / "LICENSES", package / "LICENSES")
        shutil.copy2(ROOT / "NOTICE", package / "NOTICE")


setup(cmdclass={"build_py": build_py})
