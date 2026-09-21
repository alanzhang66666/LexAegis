"""Download the public pinned Qwen3-4B base snapshot and GRPO notebook.

Anonymous access is the default. HF_TOKEN is optional and is never printed or
persisted. Both the model and notebook use immutable commit hashes.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import urllib.request

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "unsloth/Qwen3-4B-Base"
REVISION = "0573b584bc6b32adc84bb9c91bf9b71bea71fc40"
NOTEBOOK_COMMIT = "8081c7e480275013fa38cf2bfbaf902af5ccf589"
NOTEBOOK_NAME = "Qwen3_(4B)-GRPO.ipynb"
NOTEBOOK_URL = (
    "https://raw.githubusercontent.com/unslothai/notebooks/"
    f"{NOTEBOOK_COMMIT}/nb/Qwen3_%284B%29-GRPO.ipynb"
)
DEFAULT_TARGET = ROOT / ".data" / "models" / "qwen3-4b-base"
DEFAULT_REPRO_TARGET = ROOT / ".data" / "model-reproduction" / "qwen3-4b-grpo"


def _submission_module():
    path = ROOT / "scripts" / "build_submission.py"
    spec = importlib.util.spec_from_file_location("_lexaegis_build_submission", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--repro-target", type=Path, default=DEFAULT_REPRO_TARGET)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.max_workers < 1 or args.max_workers > 16:
        parser.error("--max-workers must be between 1 and 16")

    load_dotenv(ROOT / ".env", override=False)
    token = os.environ.get("HF_TOKEN")
    target = args.target.resolve()
    repro_target = args.repro_target.resolve()
    if target.is_symlink() or repro_target.is_symlink():
        parser.error("targets cannot be symbolic links")
    target.mkdir(parents=True, exist_ok=True)
    repro_target.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    print(f"下载公开固定模型：{REPO_ID}@{REVISION}")
    print(f"目标目录：{target}")
    print("访问方式：" + ("已配置 HF_TOKEN" if token else "匿名（公开仓库无需 Token）"))
    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=target,
        token=token,
        max_workers=args.max_workers,
    )
    notebook = repro_target / NOTEBOOK_NAME
    with urllib.request.urlopen(NOTEBOOK_URL, timeout=60) as response:
        notebook.write_bytes(response.read())

    submission = _submission_module()
    files = submission.validate_competition_model(target)
    submission.validate_repro_source(repro_target)
    total = sum(path.stat().st_size for path in files)
    print(f"固定模型与 Notebook 校验完成：{len(files)} 个模型文件，{total} bytes")
    print("HF_TOKEN 未输出、未写入交付目录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
