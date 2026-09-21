"""Self-check a generated competition delivery without modifying it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


REQUIRED_FILES = (
    "README.md", "SUBMISSION_MANIFEST.md", "DEPENDENCIES.md", "THIRD_PARTY_NOTICES.md",
    "DELIVERY_STATUS.json", "FILE_INVENTORY.sha256", "Dockerfile", ".env.example",
    "docs/EDGE_MODEL_INTERFACE.md", "examples/four_boundary_demo/index.json",
    "start-competition.ps1", "vendor/WHEELHOUSE_MANIFEST.json",
    "validation/live-three-layers.json", "frontend/dist/index.html",
    "src/frontend/dist/index.html",
)
REQUIRED_DIRS = (
    "container", "examples", "examples/four_boundary_demo", "examples/formal_upload",
    "knowledge", "prompts", "src", "tests", "docs", "lexaegis", "frontend", "scripts",
    "vendor/wheels", "validation",
)
BOUNDARIES = {
    "complete_disclosure": "01-完整披露流程",
    "human_review_veto": "02-人工复核否决",
    "linkage_risk": "03-组合线索风险",
    "active_stop": "04-主动停止",
}
FORBIDDEN_SEGMENTS = {
    ".git", ".data", ".venv", ".env", ".runtime", ".artifacts", "node_modules", "__pycache__", ".pytest_cache", ".cache",
    "test-results", "playwright-report", "真实案件", "inbox",
}
FORBIDDEN_INTERFACE_SUFFIXES = {
    ".gguf", ".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".ipynb",
}
REAL_CASE = re.compile(r"FBM-CLI\.C\.\d+")
KEY_LITERAL = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")
FORBIDDEN_TEXT = ("外发" + "已开通", "10 案" + "已通过", "10案" + "已通过")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".tsx", ".ts", ".js", ".mjs", ".jsx", ".css", ".html", ".cfg", ".ini", ".example", ".lock"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def files(root: Path):
    return sorted(item for item in root.rglob("*") if item.is_file())


def compare_tree(root: Path, name: str, findings: list[str]) -> None:
    runtime = root / name
    mirror = root / "src" / name
    if not runtime.is_dir() or not mirror.is_dir():
        return
    runtime_files = {item.relative_to(runtime).as_posix(): item for item in files(runtime)}
    mirror_files = {item.relative_to(mirror).as_posix(): item for item in files(mirror)}
    if runtime_files.keys() != mirror_files.keys():
        findings.append(f"src/{name} 与运行兼容副本文件集合不一致")
        return
    for relative in runtime_files:
        if digest(runtime_files[relative]) != digest(mirror_files[relative]):
            findings.append(f"src/{name}/{relative} 与运行兼容副本不一致")


def verify_inventory(root: Path, findings: list[str]) -> None:
    inventory = root / "FILE_INVENTORY.sha256"
    if not inventory.is_file():
        return
    seen = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            if " *" in line:
                expected, relative = line.split(" *", 1)
            else:
                expected, relative = line.split("  ", 1)
        except ValueError:
            findings.append("FILE_INVENTORY.sha256 行格式无效")
            continue
        item = root / relative
        if relative in seen or not item.is_file() or relative == "FILE_INVENTORY.sha256":
            findings.append(f"哈希清单条目无效：{relative}")
            continue
        seen.add(relative)
        if digest(item) != expected:
            findings.append(f"哈希不匹配：{relative}")
    actual = {
        item.relative_to(root).as_posix()
        for item in files(root)
        if item.name != "FILE_INVENTORY.sha256"
    }
    if seen != actual:
        findings.append("FILE_INVENTORY.sha256 未覆盖全部文件")


def verify_wheelhouse(root: Path, findings: list[str]) -> None:
    manifest_path = root / "vendor" / "WHEELHOUSE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        findings.append(f"离线 wheelhouse 清单无法读取：{error}")
        return
    entries = manifest.get("files") or []
    names = {entry.get("name") for entry in entries}
    joined = "\n".join(name for name in names if isinstance(name, str))
    for marker in ("cp312-win_amd64", "cp313-win_amd64", "lexaegis-1.0.0-py3-none-any"):
        if marker not in joined:
            findings.append(f"离线 wheelhouse 缺少目标：{marker}")
    if manifest.get("network_required_for_install") is not False:
        findings.append("离线 wheelhouse 未声明禁止联网安装")
    actual_names = {item.name for item in (root / "vendor" / "wheels").glob("*.whl")}
    if names != actual_names:
        findings.append("离线 wheelhouse 文件集合与清单不一致")
    for entry in entries:
        name = entry.get("name")
        item = root / "vendor" / "wheels" / str(name)
        if not item.is_file():
            continue
        if entry.get("size") != item.stat().st_size or entry.get("sha256") != digest(item):
            findings.append(f"离线 wheelhouse 哈希或大小不匹配：{name}")


def verify_three_layers(root: Path, findings: list[str]) -> None:
    evidence_path = root / "validation" / "live-three-layers.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        findings.append(f"三层实测证据无法读取：{error}")
        return
    if evidence.get("status") != "passed" or evidence.get("formal_dispatch") != "blocked":
        findings.append("三层实测证据未通过或正式外发状态错误")
    layers = {item.get("layer"): item for item in evidence.get("three_layers") or []}
    expected = {
        "1_edge_blocks": ("block_external", "not_reached", "blocked"),
        "2_human_rejects": ("allow_human_review", "reject_current_request", "rejected"),
        "3_model_and_human_allow": ("allow_human_review", "allow_processing", "complete"),
    }
    if set(layers) != set(expected):
        findings.append("三层实测证据层次不完整")
        return
    for name, (model, human, final) in expected.items():
        item = layers[name]
        if item.get("model_decision") != model or item.get("edge_decision") != model:
            findings.append(f"三层实测模型结论不匹配：{name}")
        if item.get("human_review") != human or item.get("final_state") != final:
            findings.append(f"三层实测人工或最终状态不匹配：{name}")
        if not str(item.get("edge_source") or "").startswith("live_edge_model"):
            findings.append(f"三层实测不是实时边侧模型证据：{name}")
        if not str(item.get("edge_response_hash") or "").startswith("sha256:"):
            findings.append(f"三层实测缺少模型响应哈希：{name}")
        if item.get("safety_floor_applied") is not False:
            findings.append(f"三层实测依赖确定性兜底而非模型本身：{name}")


def verify(root: Path, *, check_inventory_file: bool = True, check_inventory: bool | None = None) -> list[str]:
    if check_inventory is not None:
        check_inventory_file = check_inventory
    findings: list[str] = []
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            findings.append(f"缺少必需文件：{name}")
    for name in REQUIRED_DIRS:
        if not (root / name).is_dir():
            findings.append(f"缺少必需目录：{name}")
    status_path = root / "DELIVERY_STATUS.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        findings.append(f"DELIVERY_STATUS.json 无法读取：{error}")
        status = {}
    mode = status.get("model_mode")
    if mode not in {"interface-only", "bundled"}:
        findings.append("DELIVERY_STATUS.json 缺少有效 model_mode")
    if status.get("formal_dispatch") != "blocked":
        findings.append("正式外发状态必须为 blocked")
    index_path = root / "examples" / "four_boundary_demo" / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entries = {item.get("id"): item for item in index.get("boundaries", [])}
        if set(entries) != set(BOUNDARIES):
            findings.append("四功能边界索引不完整")
        for ident, directory in BOUNDARIES.items():
            if entries.get(ident, {}).get("directory") != directory:
                findings.append(f"演示索引目录错误：{ident}")
            folder = index_path.parent / directory
            for name in ("README.md", "input.json", "expected-state.json"):
                if not (folder / name).is_file():
                    findings.append(f"演示材料缺少：{directory}/{name}")
    except (OSError, json.JSONDecodeError) as error:
        findings.append(f"演示索引无法读取：{error}")
    image_root = index_path.parent
    for image in image_root.rglob("*.png"):
        if not image.with_suffix(".txt").is_file():
            findings.append(f"截图缺同名说明：{image.relative_to(root)}")
    if len(list(image_root.rglob("*.png"))) != 16:
        findings.append("功能页面截图数量应为 16")
    for text in image_root.rglob("*.txt"):
        if text.with_suffix(".png").exists() or text.name in {"README.md"}:
            continue
        # Only a TXT that shares a base name with a screenshot is a screenshot note.
        if text.name != "README.txt" and text.with_suffix(".png").is_file() is False:
            findings.append(f"截图说明缺同名 PNG：{text.relative_to(root)}")
    for name in ("lexaegis", "frontend", "scripts"):
        compare_tree(root, name, findings)
    verify_wheelhouse(root, findings)
    verify_three_layers(root, findings)
    if mode == "interface-only":
        if (root / "models").exists() or (root / "training").exists():
            findings.append("interface-only 不得包含 models 或 training")
    elif mode == "bundled":
        for name in (
            "models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf",
            "models/edge/qwen3-4b-grpo/transformers/model-00001-of-00002.safetensors",
            "models/edge/qwen3-4b-grpo/transformers/model-00002-of-00002.safetensors",
            "models/edge/qwen3-4b-grpo/transformers/model.safetensors.index.json",
            "models/edge/qwen3-4b-grpo/optional-lora/adapter_model.safetensors",
            "models/edge/qwen3-4b-grpo/ASSET_MANIFEST.json",
            "container/edge-runtime/windows/llama-server.exe",
        ):
            if not (root / name).is_file():
                findings.append(f"bundled 缺少模型资产：{name}")
        try:
            edge_manifest = json.loads((root / "models/edge/qwen3-4b-grpo/ASSET_MANIFEST.json").read_text(encoding="utf-8"))
            integrity = ((edge_manifest.get("source") or {}).get("integrity") or {})
            if set(integrity) != {"gguf", "shard_one", "shard_two", "archive"}:
                findings.append("bundled 模型资产清单缺少四个源文件完整性记录")
            elif any(not item.get("sha256", "").startswith("sha256:") or not isinstance(item.get("size"), int)
                     for item in integrity.values() if isinstance(item, dict)):
                findings.append("bundled 模型资产完整性记录格式无效")
        except (OSError, json.JSONDecodeError, AttributeError):
            findings.append("bundled 模型资产清单无法读取")
        try:
            edge_env = (root / ".env.example").read_text(encoding="utf-8")
            compose = (root / "compose.yaml").read_text(encoding="utf-8")
            if "LEX_EDGE_MODEL=lexaegis-qwen3-4b-grpo" not in edge_env or \
                    "LEX_EDGE_GGUF=models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf" not in edge_env:
                findings.append("bundled .env.example 未指向 Qwen3 默认模型")
            if "MiniCPM" in edge_env or "MiniCPM" in compose or \
                    "/models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf" not in compose or \
                    "--alias, lexaegis-qwen3-4b-grpo" not in compose:
                findings.append("bundled Compose 或环境示例仍含旧模型或未指向 Qwen3")
            for name in ("docs/MODELS.md", "docs/DEPLOY.md", "docs/VALIDATION.md"):
                if "MiniCPM" in (root / name).read_text(encoding="utf-8"):
                    findings.append(f"bundled 比赛说明仍含旧模型：{name}")
        except OSError:
            findings.append("bundled Qwen3 运行配置无法读取")
    for item in files(root):
        relative = item.relative_to(root)
        if set(relative.parts) & FORBIDDEN_SEGMENTS:
            findings.append(f"含禁用目录：{relative}")
        if mode == "interface-only" and item.suffix.lower() in FORBIDDEN_INTERFACE_SUFFIXES:
            findings.append(f"interface-only 含模型或训练产物：{relative}")
        if item.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if REAL_CASE.search(text):
            findings.append(f"疑似真实案号：{relative}")
        if KEY_LITERAL.search(text):
            findings.append(f"疑似密钥：{relative}")
        if item.name not in {"verify_competition_delivery.py", "build_submission.py"} and any(value in text for value in FORBIDDEN_TEXT):
            findings.append(f"含禁止表述：{relative}")
    if check_inventory_file:
        verify_inventory(root, findings)
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验比赛版完整材料")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    findings = verify(root)
    report = {"path": str(root), "ok": not findings, "findings": findings}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            print("[verify] " + finding)
        print("[verify] 通过" if not findings else f"[verify] {len(findings)} 项未通过")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
