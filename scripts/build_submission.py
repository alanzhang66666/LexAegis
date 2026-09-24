"""Assemble the competition and production delivery forms.

The competition form follows the reference material groups.  Its current bundled
edge-model path selects the usable runtime weights, normalized Transformers shards,
tokenizer/configuration, final optional LoRA, and a local llama-server runtime from
the declared edge-asset source.  It deliberately excludes source ZIP archives,
cache/checkpoint/optimizer state, notebooks, and training records.  The production
form is a fail-closed staging kit: it contains deployment/maintenance inputs but never
invents a verified build manifest, fixed image, receipt, or production acceptance
result.

Nothing is ever copied by "take the whole tree then delete a few things": the real-case
material under data/真实案件/ must never be able to slip through.

Usage:
    python scripts/build_submission.py                      # build competition form
    python scripts/build_submission.py --edition both       # build both forms
    python scripts/build_submission.py --edition production # production staging form
    python scripts/build_submission.py --out somewhere      # choose output root
    python scripts/build_submission.py --item5               # build item 5 into deliverables/开源代码/
    python scripts/build_submission.py --audit PATH [PATH…]  # only scan paths for risky content
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PART1 = "1-智能体作品及其完整材料"
PRODUCTION_PART = "2-生产部署交付结构（待签封）"
DEFAULT_OUT = ROOT / "deliverables" / "competition_submission"
SCREENSHOT_SOURCE = ROOT / "deliverables" / "系统截图" / "功能页面"
DELIVERABLES = ROOT / "deliverables"
PRODUCTION_EDGE_MODEL_FILENAME = "MiniCPM5-2B-Q4_K_M.gguf"
PRODUCTION_EDGE_MODEL_CATALOG = "edge.minicpm5-2b.q4_k_m.nothink.json"
COMPETITION_MODEL_ID = "unsloth/Qwen3-4B-Base"
COMPETITION_MODEL_REVISION = "0573b584bc6b32adc84bb9c91bf9b71bea71fc40"
COMPETITION_MODEL_COMMIT = COMPETITION_MODEL_REVISION
COMPETITION_NOTEBOOK_REPOSITORY = "unslothai/notebooks"
COMPETITION_NOTEBOOK_COMMIT = "8081c7e480275013fa38cf2bfbaf902af5ccf589"
COMPETITION_NOTEBOOK_PATH = "nb/Qwen3_(4B)-GRPO.ipynb"
COMPETITION_NOTEBOOK_SIZE = 756283
COMPETITION_NOTEBOOK_SHA256 = "40d6e9758991c4ee3da069b4612b907b271ee300b90ab9a3ef57d0f514548bc6"

# ---------------------------------------------------------------- copy plan

# Directory segments that must never appear anywhere in the produced tree.
FORBIDDEN_SEGMENTS = frozenset({
    ".git", ".data", ".venv", ".env", ".runtime", "node_modules", "__pycache__",
    ".pytest_cache", ".hypothesis", ".artifacts", "build", "dist",
    "lexaegis.egg-info", "test-results", "playwright-report", ".cache",
    "真实案件", "__MACOSX", "inbox",
})

# Per-tree extra exclusions, matched against any path segment or file name.
TREES: tuple[tuple[str, frozenset[str]], ...] = (
    ("lexaegis", frozenset({"frontend"})),          # packaged frontend copy is a wheel artifact
    ("frontend", frozenset({"tsconfig.tsbuildinfo"})),
    ("tests", frozenset({
        "test_legal_asset_import.py", "test_adapted_recording.py",
        "test_demo_document_import.py",
    })),
    ("examples", frozenset()),
    ("packs", frozenset()),
    ("constraints", frozenset()),
    ("LICENSES", frozenset()),
    ("training", frozenset()),
)

ROOT_FILES = (
    "Dockerfile", ".dockerignore", "compose.yaml", "compose.demo.yaml",
    "compose.integration.yaml", "pyproject.toml", "setup.py",
    "MANIFEST.in", "requirements.lock", ".env.example", "NOTICE", "LOGO.jpg",
)

# scripts/: only what the submission itself needs. The pilot / legal-docx generators are
# excluded because they hard-code .data/real_cases paths and embed ten-case identifiers.
SCRIPT_FILES = (
    "build_submission.py", "export_prompts.py", "make_examples.py",
    "export_grpo_assets.py",
    "fetch_competition_model.py", "package_frontend.py", "package_delivery.py",
    "verify_wheel.py", "verify_competition_delivery.py",
    "capture_competition_function_pages.cjs", "dev.py",
)

# docs/: current specification and runtime docs only. archive/, LOCAL_STATUS.md and the
# ten-case / internal legal material stay out.
DOC_FILES = (
    "PROJECT_MAP.md", "ARCHITECTURE.md", "VALIDATION.md", "PROVENANCE.md",
    "DESIGN.md", "DEPLOY.md", "MODELS.md", "THIRD_PARTY.md",
    "DUAL_TRACK_DEPLOY.md", "DUAL_TRACK_ACCEPTANCE.md", "DELIVERY_EDITIONS.md",
    "EDGE_MODEL_INTERFACE.md",
)
DOC_LEGAL_FILES = ("案隐盾_系统法学规则与验收标准_v1.0.md",)

DATA_FILES = ("catalog.json", "README.md", "ANNOTATION.md")
DATA_TREES = ("mock_labor_v1",)

LEGAL_SOURCE_FILES = (
    "总法源目录.xlsx",
    "总法源目录_v0.2.xlsx",
    "总法源目录_合并版.xlsx",
    "总法源目录_合并版.json",
    "总法源目录_v0.1-v0.2差异清单.md",
    "个人信息-个保法-处理方式对应表.xlsx",
    "其他敏感客体-相应法条-处理方式对照表.xlsx",
    "硬性禁止、人工复核情形及冲突处理回答.docx",
    "硬性禁止、人工复核情形及冲突处理回答_v0.2.docx",
)

# legal/templates/: annotation guide only. The 案例标注示范* files are left out because they
# may be derived from real case samples. The v0.1 workbook is also left out: its 「来源登记」
# sheet registers real source documents — real case numbers (FBM-CLI.C.*), file hashes and
# .data/landing_20260911 intake paths. It ships only after legal produces a sanitized copy.
LEGAL_TEMPLATE_FILES = (
    "README.md",
    "案隐盾_法律标注指南_v0.1.docx",
)

# knowledge/ carries a read-only copy plus an index. The runtime always reads the paths above.
KNOWLEDGE_COPIES: tuple[tuple[str, str], ...] = (
    ("packs", "knowledge/packs"),
    ("legal/sources", "knowledge/legal/sources"),
)

# ---------------------------------------------------------------- content scanning

REAL_CASE_NUMBER = re.compile(r"FBM-CLI\.C\.\d+")
API_KEY_LITERAL = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")
SECRET_ASSIGNMENT = re.compile(
    r"(LEX_CLOUD_API_KEY|LEX_CLOUD_PRIMARY_KEY|LEX_CLOUD_STANDBY_KEY|LEX_GATEWAY_SECRET"
    r"|LEX_REDTEAM_SECRET|LEX_LOCAL_PASSWORD)[ \t]*[=:][ \t]*(?!\$\{)([^\s#\"']{16,})"
)
FORBIDDEN_CLAIMS = (
    "10 案已通过", "10案已通过", "外发已开通", "10 案可发", "10案可发",
)

TEXT_SUFFIXES = frozenset({
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".lock",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".html", ".example", ".in", "",
})
OFFICE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx"})
# Binary legacy Office cannot be scanned reliably, so it is never allowed through.
UNSCANNABLE_SUFFIXES = frozenset({".doc", ".xls", ".ppt"})


def _office_text(path: Path) -> str:
    chunks = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith((".xml", ".rels")):
                    try:
                        chunks.append(archive.read(name).decode("utf-8", errors="replace"))
                    except KeyError:
                        continue
    except (zipfile.BadZipFile, OSError) as error:
        return f"__UNREADABLE__{error}"
    return "\n".join(chunks)


def readable_text(path: Path) -> str | None:
    """Text of a file for content scanning, or None when it is not scannable."""
    suffix = path.suffix.lower()
    if suffix in OFFICE_SUFFIXES:
        return _office_text(path)
    if suffix in UNSCANNABLE_SUFFIXES:
        return None
    if suffix not in TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def scan_content(path: Path, *, allow_claims: bool = False) -> list[str]:
    """Risky-content findings for one file. Never returns the matched secret itself."""
    text = readable_text(path)
    if text is None:
        return []
    findings = []
    if REAL_CASE_NUMBER.search(text):
        findings.append("包含真实案号形态（FBM-CLI.C.*）")
    if API_KEY_LITERAL.search(text):
        findings.append("包含 sk- 形态密钥字面量")
    if SECRET_ASSIGNMENT.search(text):
        findings.append("包含非空凭据赋值")
    if not allow_claims:
        for claim in FORBIDDEN_CLAIMS:
            if claim in text:
                findings.append(f"包含禁写句「{claim}」")
    return findings


# ---------------------------------------------------------------- copying


def _rejected(relative: Path, extra: frozenset[str]) -> bool:
    parts = set(relative.parts)
    if parts & FORBIDDEN_SEGMENTS:
        return True
    if parts & extra:
        return True
    return relative.name in extra


def copy_tree(source: Path, target: Path, extra: frozenset[str] = frozenset()) -> int:
    """Copy a directory file by file, skipping rejected segments. Returns files copied."""
    if not source.is_dir():
        raise SystemExit(f"缺少源目录：{source}")
    copied = 0
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        if _rejected(relative, extra):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1
    return copied


def copy_file(source: Path, target: Path) -> int:
    if not source.is_file():
        raise SystemExit(f"缺少源文件：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def validate_competition_model(source: Path) -> list[Path]:
    """Validate the pinned full Qwen3-4B base snapshot before a delivery is built."""
    source = source.resolve()
    required = {
        "README.md", "config.json", "model.safetensors.index.json",
        "tokenizer_config.json",
    }
    missing = sorted(name for name in required if not (source / name).is_file())
    if missing:
        raise SystemExit("比赛模型快照不完整，缺少：" + "、".join(missing))
    model_card = (source / "README.md").read_text(encoding="utf-8", errors="replace")
    if "license: apache-2.0" not in model_card.lower():
        raise SystemExit("模型卡未声明预期的 Apache-2.0 许可")
    try:
        index = json.loads((source / "model.safetensors.index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"无法读取模型 safetensors 索引：{error}") from error
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise SystemExit("模型 safetensors 索引没有有效 weight_map")
    shards = sorted(set(weight_map.values()))
    invalid_shards = [name for name in shards if Path(name).name != name or not name.endswith(".safetensors")]
    if invalid_shards:
        raise SystemExit("模型索引包含不安全或非 safetensors 分片")
    missing_shards = [name for name in shards if not (source / name).is_file()]
    if missing_shards:
        raise SystemExit("模型权重分片缺失：" + "、".join(missing_shards))
    files = []
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(source)
        if _rejected(relative, frozenset()):
            continue
        files.append(item)
    weight_bytes = sum((source / name).stat().st_size for name in shards)
    if weight_bytes < 6 * 1024**3:
        raise SystemExit("模型权重不足 6 GiB，疑似指针文件、量化替代物或不完整快照")
    return files


def write_model_manifest(target: Path, source: Path, files: list[Path] | None = None) -> dict:
    """Write a content-addressed inventory for the pinned Qwen3-4B model snapshot."""
    source = source.resolve()
    files = files or validate_competition_model(source)
    inventory = []
    for path in files:
        relative = path.relative_to(source).as_posix()
        inventory.append({
            "path": f"models/qwen3-4b-base/{relative}",
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    manifest = {
        "schema_version": 1,
        "edition": "competition",
        "model_id": COMPETITION_MODEL_ID,
        "revision": COMPETITION_MODEL_REVISION,
        "huggingface_commit": COMPETITION_MODEL_COMMIT,
        "huggingface_visibility": "public",
        "license_declaration": "apache-2.0 (upstream model card metadata)",
        "license_file_note": (
            "The upstream snapshot does not contain a LICENSE file; the delivery keeps "
            "an Apache-2.0 text under models/license-evidence and requires final legal review."
        ),
        "format": "huggingface_safetensors_base_16bit",
        "runtime": {
            "transformers": "4.56.2",
            "trl": "0.22.2",
            "vllm_t4": "0.11.2",
            "vllm_other_colab_gpu": "0.15.1",
        },
        "served_model_id": "qwen3-4b-base",
        "artifact_role": "upstream_base_weights_for_pinned_grpo_notebook",
        "files": inventory,
        "validation_scope": (
            "固定快照与文件完整性清单；不等于比赛目标硬件兼容性、"
            "法律事实抽取质量或生产适用性验收"
        ),
    }
    destination = target / "models" / "model-manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_repro_source(source: Path) -> list[Path]:
    source = source.resolve()
    name = Path(COMPETITION_NOTEBOOK_PATH).name
    candidates = (source / COMPETITION_NOTEBOOK_PATH, source / name)
    notebook = next((path for path in candidates if path.is_file()), None)
    if notebook is None:
        raise SystemExit("复现材料缺少固定 Notebook：" + name)
    if notebook.stat().st_size != COMPETITION_NOTEBOOK_SIZE:
        raise SystemExit("GRPO Notebook 大小与固定提交不一致")
    if sha256_file(notebook) != "sha256:" + COMPETITION_NOTEBOOK_SHA256:
        raise SystemExit("GRPO Notebook SHA-256 与固定提交不一致")
    return [notebook]


def write_reproducibility_manifest(target: Path, source: Path, files: list[Path]) -> int:
    value = {
        "schema_version": 1,
        "source_repository": f"https://github.com/{COMPETITION_NOTEBOOK_REPOSITORY}",
        "source_commit": COMPETITION_NOTEBOOK_COMMIT,
        "source_path": COMPETITION_NOTEBOOK_PATH,
        "source_snapshot": [
            {
                "path": "models/reproduction/source/" + item.name,
                "size": item.stat().st_size,
                "sha256": sha256_file(item),
            }
            for item in files
        ],
        "base_model": {
            "repository": COMPETITION_MODEL_ID,
            "revision": COMPETITION_MODEL_REVISION,
            "commit": COMPETITION_MODEL_COMMIT,
        },
        "training_contract": {
            "method": "SFT pre-finetune followed by GRPO",
            "base_precision": "16bit (load_in_4bit=False)",
            "max_seq_length": 2048,
            "lora_rank": 32,
            "export_options": ["merged_16bit", "merged_4bit", "GGUF q4_k_m"],
        },
        "notebook_runtime": {
            "transformers": "4.56.2",
            "trl": "0.22.2",
            "vllm_t4": "0.11.2",
            "vllm_other_colab_gpu": "0.15.1",
            "unsloth": "not pinned by upstream notebook",
        },
        "artifact_status": (
            "The included weights are the pinned upstream base. A trained LexAegis GRPO merged "
            "checkpoint does not exist until the notebook is executed and its output is separately hashed."
        ),
    }
    path = target / "models" / "reproducibility.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1


def copy_competition_model(target: Path, source: Path, repro_source: Path) -> int:
    """Copy the pinned Qwen3 base snapshot and exact GRPO notebook."""
    files = validate_competition_model(source)
    model_target = target / "models" / "qwen3-4b-base"
    copied = 0
    for item in files:
        copied += copy_file(item, model_target / item.relative_to(source))
    copied += copy_file(
        ROOT / "LICENSES" / "Apache-2.0.txt",
        target / "models" / "license-evidence" / "Apache-2.0.txt",
    )
    repro_files = validate_repro_source(repro_source)
    repro_target = target / "models" / "reproduction" / "source"
    for item in repro_files:
        copied += copy_file(item, repro_target / item.name)
    write_model_manifest(target, source, files)
    copied += write_reproducibility_manifest(target, repro_source, repro_files)
    return copied + 1


# ---------------------------------------------------------------- generated documents

KNOWLEDGE_README = """# 知识资源清单

本目录是**只读副本与索引**。程序运行时读取的是交付包根目录下的 `packs/`、`legal/sources/`、
`data/`——`lexaegis/registry.py` 的 `seed_packs` 只认 `packs/`，`runtime_pack.py`、`dataset.py`
也按根目录解析，所以那些文件没有被移动。改动知识资源请改根目录下的原件，再重新装配。

## 运行必需

| 资源 | 运行时路径 | 版本 | 状态 | 用途 |
| --- | --- | --- | --- | --- |
| 劳动争议演示包 | `packs/labor_demo.json` | `0.1.0-demo` | `demo` | 三个固定合成演示的适用规则 |
| 劳动争议 V2 草案包 | `packs/labor_v2_draft.json` | `2.0.0-draft.3` | `draft`，`dispatch_allowed=false` | 正式案件的字段矩阵与披露规则；**未发布**，不能用于正式外发 |
| 合同测试夹具 | `packs/contract_test.json` | `0.0.1` | `draft` | 规则回归夹具，非法源 |

三份案由包**无一为 `published`**。`lexaegis/outbound_gate.py` 的 G5 要求包已发布且
`legal_status=reviewed`、`dispatch_allowed=true`，因此正式案件的外发当前必然被阻断。

## 参考资料（不参与运行时判定）

| 资源 | 路径 | 说明 |
| --- | --- | --- |
| 总法源目录及其合并版 | `legal/sources/总法源目录*.xlsx` / `.json` | 项目自行整理的法源目录，**不是官方发布物**；条文引用须回到官方文本核对 |
| 个人信息处理方式对应表 | `legal/sources/个人信息-个保法-处理方式对应表.xlsx` | 字段与处理方式的对照整理 |
| 其他敏感客体对照表 | `legal/sources/其他敏感客体-相应法条-处理方式对照表.xlsx` | 同上 |
| 硬性禁止与人工复核口径 | `legal/sources/硬性禁止、人工复核情形及冲突处理回答*.docx` | 规则设计依据 |
| 标注指南 | `legal/templates/` | 标注方法，非评测主库；工作簿 v0.1 含真实案号登记，未随包 |
| 评测语料 | `data/mock_labor_v1/` | 8 条**全合成**劳动争议记录，`kind=fully_synthetic`、`frozen`，法律标注仍为 pending |
| 语料清单 | `data/catalog.json` | 仅登记 `mock_labor`，`freeze_hash` 冻结 |

## 未随包提交

- 真实案件材料：一律不在交付包内，也不在仓库版本库内。
- OCR/转写模型资产不随包分发；未配置时对应能力保持未验证或改为人工录入。
- 比赛版默认运行权重在 `models/edge/qwen3-4b-grpo/`：GGUF、规范命名的 Transformers 分片与可选 LoRA；完整性见该目录 `ASSET_MANIFEST.json`。下载缓存与其他权重不随包。
- 法计交接空表与内部法学盘点材料：不随包提交，因此
  `tests/test_legal_asset_import.py` 在交付包内会失败，属预期，见根 `README.md` 的验证章节。

## 演示输入

`examples/synthetic_labor.docx`、`examples/synthetic_scan.pdf` 是**演示输入，不是智能体的组成部分**，
可用 `python scripts/make_examples.py` 重新生成。三个固定演示只接受内置合成材料
（`lexaegis/demo.py`），不接受上传。
"""


DELIVERY_README = """# 案隐盾 LexAegis · 比赛版智能体作品及其完整材料

本地优先的法律披露工作台。原文与身份映射留在本地；律师对**一次完整冻结请求**具名批准后，
由独立网关调用云端大模型 API；返回结果在本地校核并回链到原文。

版本 **V1.0**（`1.0.0`），非正式发行。

> **阅读顺序**：先看「一、快速开始」把程序跑起来，再看「四、一次示例运行」照着走一遍，
> 最后看「七、如实口径」了解哪些能力已验证、哪些没有。

---

## 一、快速开始（单容器）

需要 Docker。容器内会由启动器依次拉起网关、API、worker 三个进程。

```bash
docker build -t lexaegis-submission .
docker run --rm -p 127.0.0.1:8765:8765 -v ./models:/models:ro lexaegis-submission
```

终端会打印：

```text
LexAegis: http://127.0.0.1:8765
本地访问口令: <随机生成的口令>
native 模式不具备可验证网络隔离，正式外发保持阻断。
工作台已绑定 0.0.0.0：请只发布到宿主机回环口（docker run -p 127.0.0.1:8765:8765），不要暴露到局域网。
```

浏览器打开 **http://127.0.0.1:8765**，用终端里的口令登录。用户名 `admin`。

### 三个必须照做的点

1. **只能用 `http://127.0.0.1:8765`。** `lexaegis/api.py` 的 `TrustedHostMiddleware` 只放行
   `127.0.0.1`、`localhost`，用局域网 IP 或其他主机名访问会被拒。
2. **宿主机端口若不是 8765，必须同步告知程序**，否则登录后所有写操作会被跨站校验拦成 403：
   ```bash
   docker run --rm -p 127.0.0.1:9000:8765 -e LEX_API_PORT=9000 -v ./models:/models:ro lexaegis-submission
   ```
3. **口令**：`docker run` 前台运行时直接看终端。若用 `-d` 后台运行，用 `docker logs <容器名>`；
   推荐直接指定，省去翻日志：
   ```bash
   docker run --rm -p 127.0.0.1:8765:8765 -e LEX_LOCAL_PASSWORD="your-local-password" -v ./models:/models:ro lexaegis-submission
   ```

### 数据持久化

镜像声明了 `VOLUME /data`。不带 `-v` 时 Docker 每次创建新的匿名卷，**口令与案件数据不会跨容器保留**。
要保留就挂命名卷：

```bash
docker volume create lexaegis-data
docker run --rm -p 127.0.0.1:8765:8765 -v lexaegis-data:/data -v ./models:/models:ro lexaegis-submission
```

⚠️ **不要把 Windows 或网络目录绑定挂载到 `/data`。** `lexaegis/util.py` 的
`assert_local_filesystem` 会拒绝 `nfs`/`cifs`/`smbfs`/`sshfs`/`9p` 类文件系统上的 SQLite 目录，
Docker Desktop 的主机目录共享可能正属于其中之一。请用命名卷或不挂卷。

---

## 二、从源码运行（不使用 Docker）

需要 Python 3.12+、Node.js 22+、pnpm 11。

```bash
python -m venv .venv
# Windows: .\\.venv\\Scripts\\Activate.ps1
source .venv/bin/activate
python -m pip install -e ".[test]"
cd frontend && pnpm install --frozen-lockfile && pnpm build && cd ..
python scripts/make_examples.py
python -m lexaegis.cli start
```

同样打开 **http://127.0.0.1:8765**，口令看终端。`Ctrl+C` 停止三个进程。
源码方式默认只监听回环（`LEX_BIND_HOST` 默认 `127.0.0.1`），不需要额外配置。

---

## 三、目录说明

| 位置 | 内容 |
| --- | --- |
| `lexaegis/` | 后端全部源码：入口与启动器、案件与解析、门禁与策略、外发与网关、评测 |
| `frontend/` | 前端源码（React + Vite）。`frontend/src/App.tsx` 是工作台主界面 |
| `prompts/` | **运行时实际使用的提示词**，由 `scripts/export_prompts.py` 从代码导出，与冻结请求逐字一致 |
| `knowledge/` | 知识资源的只读副本与清单；运行时读的是根目录的 `packs/`、`legal/sources/`、`data/` |
| `models/` | Qwen3-4B 基座固定快照、GRPO Notebook、逐文件哈希与复现清单；不含下载缓存 |
| `container/` | 容器入口、Compose 形态和端侧模型装载边界说明 |
| `packs/` | 案由规则包（运行时读取），无一为 `published` |
| `legal/sources/` | 法源目录与处理方式对照表 |
| `data/` | 评测语料，`mock_labor_v1` 为 8 条全合成记录 |
| `examples/` | **演示输入，非智能体组成部分** |
| `tests/` | 后端测试 |
| `docs/` | 现行规格与部署文档 |
| `scripts/` | 装配、提示词导出、演示材料生成等脚本 |
| `Dockerfile` | 单容器提交形态 |
| `compose.yaml` | **隔离部署参考，不是提交形态**，见第七节 |
| `.env.example` | 配置样例，仅占位符 |

---

## 四、一次示例运行

登录后进入案件列表，打开「01 完整披露流程」（内置合成演示）。四步工作台：

1. **事实与证据** — 查看内置合成事实，每条可「查看原文依据」回链到来源块。
2. **逐项披露方案** — 对每个字段选择保留、假名化、泛化或删除，并记录必要性。
3. **风险与审批** — 点「检验风险并冻结请求」。系统跑确定性检测与门禁判定，冻结出
   `request_hash`。通过后由具名 approver 填写审批理由、事实前提、权限判断等必填项后批准。
4. **摘要与回链** — 点「执行模拟调用」，结果逐条回链到原文锚点，需人工逐项确认。

**边界案例（必看）**：打开「02」走同样流程，到审批步会看到 **409**，阻断原因是
「组合线索风险：唯一岗位或公开事件仍保留」。这是门禁按设计生效，**不是缺陷**，不要尝试强行批准。

**正式案件**：新建正式案件并上传 `examples/` 下的合成材料，可以体验解析、事实抽取与披露方案；
审批或发送会返回 **409**，因为正式外发的十道门禁尚未齐备（见第七节）。

---

## 五、验证

```bash
python -m pytest -q
python -m lexaegis.cli doctor
cd frontend && pnpm exec tsc --noEmit && pnpm build
```

### 预期的一处失败

`tests/test_legal_asset_import.py` 会失败。原因：它依赖法计交接空表等**未随包提交**的法学材料
（`lexaegis/legal_assets.py` 的 `_required_asset_paths` 要求 `docs/legal/法计交接/` 整棵树）。
这些材料属项目内部法学过程文件，不随交付包提交。跳过它即可：

```bash
python -m pytest -q --ignore=tests/test_legal_asset_import.py
```

`lexaegis doctor` 中 `edge_model`、`isolation`、`host_publish`、`ocr`、`whisper` 为可选项，
未配置时不影响整体 `ok`。

---

## 六、配置项

配置见 `.env.example`，复制为 `.env` 后按需修改；容器里用 `-e` 传入。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LEX_LOCAL_PASSWORD` | 自动生成 | 本地访问口令。不设时启动器生成并打印到终端 |
| `LEX_API_PORT` | `8765` | 工作台端口。**宿主机映射端口不同时必须同步设置** |
| `LEX_BIND_HOST` | `127.0.0.1` | 工作台绑定地址。镜像内设为 `0.0.0.0`；网关始终只绑 `127.0.0.1` |
| `LEX_DATA_DIR` | `.data/app`（镜像内 `/data/app`） | 运行库与案件数据目录 |
| `LEX_GATEWAY_DIR` | `.data/gateway`（镜像内 `/data/gateway`） | 网关独立数据目录 |
| `LEX_GATEWAY_SECRET` | 自动生成 | API 与网关之间签名用的共享密钥 |
| `LEX_CLOUD_PRIMARY_KEY` | 空 | 云端主槽 API Key。**只由运行者通过环境变量提供，不在包内** |
| `LEX_CLOUD_STANDBY_KEY` | 空 | 云端备槽 API Key |
| `LEX_CLOUD_ALLOWED_HOSTS` | 见 `.env.example` | 云端出口白名单 |
| `LEX_EDGE_URL` / `LEX_EDGE_MODEL` | 空 | 本地边侧抽取模型（OpenAI 兼容 `/v1`）。未配置时改为人工录入事实 |

### 随包端侧模型

比赛版保留公开 Hugging Face `unsloth/Qwen3-4B-Base` 的固定提交
`0573b584bc6b32adc84bb9c91bf9b71bea71fc40`，并保留固定提交的
`Qwen3_(4B)-GRPO.ipynb`。先按 `models/model-manifest.json` 校验逐文件 SHA-256。
随包权重是 Notebook 的上游基座，不是尚未执行训练的 LexAegis GRPO 成品；权重随包也不代表
目标机器显存、法律事实抽取质量或生产适用性已经验收。

### 关于云端模型

云端主槽的目标与模型名在工作台「运行配置」页填写，并受 `LEX_CLOUD_ALLOWED_HOSTS` 白名单约束。
代码内的默认目录常量位于 `lexaegis/cloud.py`（主槽 `api.deepseek.com`）。
**模型名以组委会最终通知与官方 API 实际可用名称为准**，在运行配置里填写即可，不需要改代码。

真实 API Key 只能由运行者通过环境变量提供，**不进交付包、不写入任何文件**；
密钥仅注入网关进程，业务 API 与 worker 进程的环境变量里会被剔除（`lexaegis/launcher.py`）。

---

## 七、如实口径

这一节写清哪些是已验证的，哪些不是。请不要把未验证项当作已通过。

### 单容器形态没有可验证的网络隔离

单容器运行时部署模式为 `native`。`lexaegis/cli.py` 的隔离验收命令对 `native` 直接拒绝写入
`isolation_verified`——**native 不能自证隔离**。因此门禁 G9（隔离部署自检）在单容器下必然不通过。
`compose.yaml` 保留在源码中作为隔离部署的参考配置，**它不是本次提交形态**，
且容器内探测通过也不等于对某一次请求的隔离收据。

### 正式外发失败关闭

产品级闩 `product_dispatch_state()` 恒为 `blocked`（`lexaegis/outbound_gate.py`）。
正式案件的外发还须同时满足案由包发布与法学状态、服务商档案与影响评估、四类攻击全部
`resisted`、隔离自检通过等条件，当前**均未齐备**。所以正式案件在审批或发送时返回 **409**，
这是门禁生效而不是产品缺陷。**真实云端 API 成功外发：从未发生过。**

### 演示 01 的摘要不是模型生成

演示 01 使用 `transport="mock"`。网关在本地把已披露事实按 1:1 组装成摘要返回
（`lexaegis/gateway.py`），结果标记为 `provenance="simulation"`，界面显示「模拟结果 · 非模型生成」。
这条链路上的审批哈希、HMAC 签名、SQLite 台账都是真实的，**只有摘要文本不是模型产物**。
演示链路不会读取任何云端密钥，也不会发出对外请求。

### 本次交付未验证的部分

| 项 | 状态 |
| --- | --- |
| `docker build` 与容器内实跑 | 本次装配不代替目标评审机实跑；必须在目标机器重新构建并留存结果 |
| 真实云端 API 调用 | 未验证。交付材料中没有任何真实云端调用记录 |
| 比赛开放模型 | 固定 merged 权重随包并有逐文件哈希；目标硬件与法律事实抽取质量仍须现场验证 |
| OCR / 语音转写 | 默认关闭，需本地模型资产；无识别率或转写准确率结论 |
| 容器隔离与宿主机发布取证 | 未验证 |

### 已在本机验证的部分

| 项 | 结果 |
| --- | --- |
| 后端测试 | 以 `docs/VALIDATION.md` 及交付前重新执行的测试记录为准；装配本身不把历史结果改写为本次通过 |
| 启动器绑定行为 | API 绑定 `0.0.0.0` 时可从本机地址访问；网关同时仅在 `127.0.0.1` 监听，外部不可达 |
| 工作台可用性 | 登录、案件引导、静态页面、三份案由包装载（status 仅 `demo`/`draft`）均正常 |
| 提示词一致性 | `prompts/` 与运行时冻结请求中的 system prompt 逐字一致（有测试守卫） |

### 其他

- 身份分词 `[[LEX:P0001]]` **不是匿名化**。
- 具名批准是**发送控制**，不是《个人信息保护法》第 13 条意义上的处理依据。
- 确定性检测不是完整的再识别测试；未执行的攻击不计为通过。

---

## 八、许可与来源

第三方组件许可见 `NOTICE` 与 `LICENSES/`，来源说明见 `docs/PROVENANCE.md` 与
`docs/THIRD_PARTY.md`。知识资源的来源与状态见 `knowledge/README.md`。
本包仅分发 `models/model-manifest.json` 登记的端侧权重；不分发真实案件材料或未经验证的效果数字。
"""


SUBMISSION_MANIFEST = """# 比赛提交材料清单

本目录对应“智能体作品及其完整材料”。组织方式参照比赛提交目录，将源码、测试、容器材料、
演示输入、提示词、知识资源和模型资产分组保存。`src/` 是供评审浏览的源码镜像；为保证原有
Docker、wheel 和测试命令无需改写，`lexaegis/`、`frontend/` 与 `scripts/` 同时保留运行兼容副本。
两套路径在装配时由同一白名单复制，不作为两套实现维护。

| 要求 | 位置 |
| --- | --- |
| 后端与前端完整源码 | `src/lexaegis/`、`src/frontend/`；根层同名目录为运行兼容副本 |
| 构建与运行配置 | `Dockerfile`、`compose*.yaml`、`.env.example`、`container/` |
| 运行提示词 | `prompts/` |
| 知识与法源资源 | `knowledge/`、`packs/`、`legal/sources/`、`data/` |
| 开放模型权重与复现声明 | `models/qwen3-4b-base/`、`models/reproduction/source/Qwen3_(4B)-GRPO.ipynb`、`models/model-manifest.json`、`models/reproducibility.json` |
| 微调适配成果 | `training/`（合成训练投影、奖励器、状态；checkpoint 尚未生成） |
| 合成演示输入 | `examples/` |
| 测试 | `tests/` |
| 依赖与许可 | `DEPENDENCIES.md`、`requirements.lock`、`frontend/pnpm-lock.yaml`、`NOTICE`、`LICENSES/` |

## 明确排除

`.env`、API Key、运行数据库、真实案件、出站交付包、模型下载缓存、未完成的 Qwen 权重、
`node_modules`、虚拟环境、构建缓存和测试结果均不进入比赛版。
"""


COMPETITION_DEPENDENCIES = """# 比赛版依赖说明

## 源码运行

- Python 3.12+；Python 依赖以 `requirements.lock` 与 `pyproject.toml` 为准。
- Node.js 22+、pnpm 11；前端完整锁文件为 `frontend/pnpm-lock.yaml`。
- GRPO Notebook 固定 Transformers 4.56.2、TRL 0.22.2；T4 分支使用 vLLM 0.11.2，
  其他 Colab GPU 分支使用 vLLM 0.15.1。上游没有固定 Unsloth 版本，实跑后必须补充环境锁定清单。
- 下载公开 Hugging Face 固定提交时使用 `huggingface-hub` 与
  `scripts/fetch_competition_model.py`；默认匿名访问，不需要 Token。若运行者主动配置 `HF_TOKEN`，
  也只从环境或被忽略的 `.env` 读取，绝不进入交付包。

## 容器运行

- Docker Engine 24+；应用镜像由根目录 `Dockerfile` 构建。
- `compose.yaml` 是隔离与 edge profile 的参考形态；比赛单容器演示仍是 native，不能自证隔离。
- vLLM/Transformers 运行时由部署者按复现清单固定；本包不把任意更新后的运行时冒充为已验证版本。

## 外部服务

云端模型是可选外部服务，凭据由运行者注入独立网关。比赛离线演示不需要真实云端 Key。
"""


THIRD_PARTY_NOTICES = """# 第三方与模型资源说明

Python、前端与基础设施组件的归属和许可见 `NOTICE`、`LICENSES/` 与 `docs/THIRD_PARTY.md`。
比赛模型来源、固定标签、复现归档和实际文件哈希见 `models/reproducibility.json` 与
`models/model-manifest.json`。
提交前仍须由提交人核对模型许可证与比赛分发条款；文件随包不代表该项法律复核已经完成。
"""


CONTAINER_README = """# 容器材料

根目录 `Dockerfile` 是比赛单容器演示入口；`container/docker-entrypoint.sh` 在
`lexaegis start` 时于同一容器内尝试拉起 Linux `llama-server`。把宿主机 `./models`
只读挂到 `/models` 后即可使用随包 GGUF。未挂载时工作台仍启动，边侧审核改用离线夹具。

`compose.demo.yaml`、`compose.yaml` 和 `compose.integration.yaml` 分别描述演示、生产及联调
形态。单容器是 native，不能自证隔离；正式外发保持 `blocked`。
"""


MODEL_README = """# 比赛开放模型

本目录保留 `unsloth/Qwen3-4B-Base` 提交 `0573b584…` 的完整基座 safetensors，
以及 Unsloth `Qwen3_(4B)-GRPO.ipynb` 提交 `8081c7e…`。
`model-manifest.json` 记录每个随包权重文件的 SHA-256；`reproducibility.json` 固定 Notebook、
基座提交、训练参数和导出选项。

不要把缓存、其他权重或浮动 `main/latest` 混入交付包。当前随包权重是公开基座，不能冒充
已经执行 SFT + GRPO 的项目成品。完成 Notebook 训练后，须选择 `merged_16bit` 或 `q4_k_m` 导出、
逐文件哈希并重新装配；该训练流程不自动构成 LexAegis 法律事实抽取质量或生产适用性结论。
"""


SOURCE_README = """# 源码审阅镜像

本目录参照比赛材料的 `src/` 分组，保存后端、前端、装配脚本和 Python 构建配置。交付包根层的
`lexaegis/`、`frontend/`、`scripts/` 是同一构建瞬间生成的运行兼容副本，供现有 Docker、wheel
和测试命令直接使用。请勿分别修改两个位置；修改源仓库后应重新运行装配脚本。
"""


PRODUCTION_README = """# 案隐盾 LexAegis · 生产部署交付结构（待签封）

这是生产交付的**待签封结构**，不是可发送的正式发行包。它只保存固定交付所需的配置、维护脚本、
依赖锁、许可和验收说明；真实生产 ZIP 必须由 `scripts/package_delivery.py` 使用已经构建并核验的
镜像、wheel、依赖清单和 `release-build-manifest.json` 生成。

当前 `formal_dispatch=blocked`。本目录没有伪造上述四类构建输入，也没有真实案件、密钥、批准人、
十门通过收据或真实外发记录。补齐 `release-inputs/README.md` 列出的输入后，仍须目标 Windows 主机、
Docker Desktop、隔离、备份恢复和逐请求正式门禁验收。

端侧模型在生产中是独立受控资产：本结构保留 `models/catalog/` 声明与登记要求，不复制比赛版
GGUF。部署时应把经许可、经哈希核验的权重按 `MODEL_ASSET_REQUIREMENTS.md` 单独登记和安装。
"""


PRODUCTION_INPUTS_README = """# 生产签封前必须提供的输入

以下项目缺一不可，且不得使用占位文件：

1. `images.tar`：由 `docker image save` 产生，包含固定应用镜像和 route-isolation 镜像。
2. `release-build-manifest.json`：状态必须为 `verified`，绑定提交、前端、wheel、锁文件、Runtime Pack 和镜像 ID。
3. `lexaegis-1.0.0-*.whl`：哈希与构建清单一致。
4. `dependencies.json`：绑定相同运行镜像，逐项列出组件、版本和许可证。
5. 已审核 Runtime Pack、服务商档案、正式证据与十门收据；这些运行证据不由打包脚本代签。

使用 `scripts/package_delivery.py` 生成最终 ZIP。该脚本只核验并封装，不构建、不下载、不激活生产。
"""

# ---------------------------------------------------------------- item 5 documents

ITEM5_NAME = "开源代码"

# 开源代码夹只收代码与构建必需文件：数据、知识库、第三方模板与资料来源说明
# 属其他提交项，不进本夹；可运行的完整材料走第 1 项装配。
ITEM5_TREES: tuple[tuple[str, frozenset[str]], ...] = (
    ("lexaegis", frozenset({"frontend"})),          # packaged frontend copy is a wheel artifact
    ("frontend", frozenset({"tsconfig.tsbuildinfo"})),
    ("tests", frozenset()),
    ("constraints", frozenset()),
    ("LICENSES", frozenset()),
)

ITEM5_README = """# 开源代码 · 案隐盾 LexAegis

比赛「开源代码」提交项的源码快照，由 `python scripts/build_submission.py --item5`
装配：仅收代码与构建必需文件；数据、知识库、第三方模板与资料来源说明属其他提交项，
不在本夹；可运行的完整材料见第 1 项「智能体作品及其完整材料」。

| 位置 | 内容 |
| --- | --- |
| `lexaegis/` | 后端源码（Python 3.12+，FastAPI / SQLAlchemy） |
| `frontend/` | 前端源码（React + Vite） |
| `tests/` | 后端测试 |
| `prompts/` | 运行时提示词快照（`export_prompts.py` 导出，与冻结请求逐字一致） |
| `scripts/` | 装配、提示词导出、演示生成与校验脚本 |
| `constraints/`、`requirements.lock`、`pyproject.toml`、`setup.py`、`MANIFEST.in` | 依赖与打包配置 |
| `Dockerfile`、`.dockerignore`、`compose.yaml` | 容器与隔离部署配置 |
| `.env.example` | 配置样例（仅占位符，无密钥） |
| `NOTICE`、`LICENSES/` | 第三方归属声明（含 kubeedge/ianvs PR #282/#283 Apache-2.0 改编） |

装配后逐文件扫描风险内容（真实案号、密钥字面量、非空凭据赋值、禁写句），命中即整夹删除。
"""

# The 资料来源说明 document belongs to a separate submission item and is not generated
# by this script.

# ---------------------------------------------------------------- assembly

GENERATED_MARKER = ".built-by-build_submission"
# The scanner carries the forbidden-claim patterns as data; exempt it from the claims
# check only. All other checks still apply to it.
CLAIM_SCAN_EXEMPT = frozenset({"build_submission.py"})


def _load_export_prompts():
    """Load scripts/export_prompts.py without making scripts/ a package."""
    import importlib.util

    path = ROOT / "scripts" / "export_prompts.py"
    spec = importlib.util.spec_from_file_location("_submission_export_prompts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_target(target: Path, *, force: bool = False) -> None:
    """Create a fresh output dir. Refuse to clobber anything this script did not build."""
    if target.exists():
        if not force and not (target / GENERATED_MARKER).is_file():
            raise SystemExit(
                f"目标目录已存在且不是本脚本产物，拒绝覆盖（确认后用 --force）：{target}"
            )
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / GENERATED_MARKER).write_text(
        "generated by scripts/build_submission.py\n", encoding="utf-8"
    )


def _competition_script_files(model_mode: str) -> tuple[str, ...]:
    if model_mode == "interface-only":
        excluded = {"fetch_competition_model.py", "export_grpo_assets.py"}
        return tuple(name for name in SCRIPT_FILES if name not in excluded)
    return SCRIPT_FILES


def _safe_extract(archive: zipfile.ZipFile, member: str, destination: Path) -> int:
    """Extract one known member without trusting archive paths."""
    if Path(member).is_absolute() or ".." in Path(member).parts:
        raise SystemExit(f"模型归档包含不安全路径：{member}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    return 1


def copy_supplied_model_assets(target: Path, source: Path) -> int:
    """Normalize the supplied D-drive model set into a reusable bundled layout."""
    source = source.resolve()
    shard_one = sorted(source.glob("model-00001-of-00002-*.safetensors"))
    shard_two = sorted(source.glob("model-00002-of-00002-*.safetensors"))
    ggufs = sorted(source.glob("*.gguf"))
    archives = sorted(source.glob("Qwen3_4B_GRPO_Submission-*.zip"))
    if len(shard_one) != 1 or len(shard_two) != 1 or len(ggufs) != 1 or len(archives) != 1:
        raise SystemExit(
            "bundled 模式要求边侧模型目录恰好包含两片 safetensors、一个 GGUF 和一个 GRPO ZIP"
        )
    if shard_one[0].stat().st_size + shard_two[0].stat().st_size < 6 * 1024**3:
        raise SystemExit("safetensors 分片总量不足 6 GiB，拒绝作为完整合并模型")

    merged = target / "models" / "qwen3-4b-grpo-merged-16bit"
    lora = target / "models" / "qwen3-4b-grpo-lora"
    training_target = target / "training" / "grpo"
    copied = copy_file(shard_one[0], merged / "model-00001-of-00002.safetensors")
    copied += copy_file(shard_two[0], merged / "model-00002-of-00002.safetensors")
    copied += copy_file(ggufs[0], target / "models" / "qwen3-4b-base-q4" / ggufs[0].name)

    prefix = "Qwen3_4B_GRPO_Submission/"
    with zipfile.ZipFile(archives[0]) as archive:
        names = set(archive.namelist())
        index_member = prefix + "merged_16bit/model.safetensors.index.json"
        if index_member not in names:
            raise SystemExit("GRPO ZIP 缺少 merged_16bit/model.safetensors.index.json")
        index = json.loads(archive.read(index_member).decode("utf-8"))
        expected_shards = sorted(set(index.get("weight_map", {}).values()))
        if expected_shards != [
            "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"
        ]:
            raise SystemExit("GRPO ZIP 的模型索引与两分片布局不一致")
        for member in sorted(names):
            if member.endswith("/") or "/.cache/" in member:
                continue
            relative = member[len(prefix):] if member.startswith(prefix) else ""
            if relative.startswith("merged_16bit/"):
                name = relative.removeprefix("merged_16bit/")
                if name.endswith(".safetensors"):
                    continue
                copied += _safe_extract(archive, member, merged / name)
            elif relative.startswith("final_lora/"):
                copied += _safe_extract(
                    archive, member, lora / relative.removeprefix("final_lora/")
                )
            elif relative.startswith("checkpoints/"):
                copied += _safe_extract(
                    archive, member, training_target / relative.removeprefix("checkpoints/")
                )

    copied += copy_file(
        ROOT / "LICENSES" / "Apache-2.0.txt",
        target / "models" / "license-evidence" / "Apache-2.0.txt",
    )
    inventory = []
    for item in sorted((target / "models").rglob("*")):
        if item.is_file() and item.name != "MODEL_ASSET_MANIFEST.json":
            inventory.append({
                "path": item.relative_to(target).as_posix(),
                "size": item.stat().st_size,
                "sha256": sha256_file(item).removeprefix("sha256:"),
            })
    manifest = {
        "schema_version": 1,
        "artifact_status": "bundled_unvalidated_candidate",
        "source_directory": "D:/边侧模型 (read-only assembly input)",
        "source_archive": {
            "name": archives[0].name,
            "size": archives[0].stat().st_size,
            "sha256": sha256_file(archives[0]).removeprefix("sha256:"),
        },
        "normalization": (
            "外部分片按归档索引要求重命名；归档内 merged_16bit 元数据、final_lora 和"
            "checkpoints 分别装配。缓存未纳入。"
        ),
        "q4_note": "GGUF 文件名标记为 Base；不将其描述为 GRPO 微调输出。",
        "validation_scope": (
            "已验证文件存在、两分片索引关系、大小和 SHA-256；尚未完成目标硬件推理质量验收。"
        ),
        "files": inventory,
    }
    manifest_path = target / "models" / "MODEL_ASSET_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "models" / "README.md").write_text(
        "# 随包边侧模型资产\n\n"
        "本目录由 `D:/边侧模型` 的只读输入规范化生成。`qwen3-4b-grpo-merged-16bit/` "
        "由归档内模型元数据与外部两片 safetensors 组成；`qwen3-4b-grpo-lora/` 保留最终 "
        "LoRA；`qwen3-4b-base-q4/` 是文件名明确标注为 Base 的 GGUF。逐文件来源、大小和 "
        "SHA-256 见 `MODEL_ASSET_MANIFEST.json`。结构完整不等于质量、许可或目标硬件验收通过。\n",
        encoding="utf-8",
    )
    return copied + 2


def copy_allowlist(
    target: Path, model_source: Path | None = None, repro_source: Path | None = None,
    *, include_examples: bool = True, model_mode: str = "interface-only",
    model_assets_dir: Path | None = None,
) -> int:
    """Copy the competition allow-listed snapshot into target."""
    copied = 0
    for name, extra in TREES:
        if model_mode == "interface-only" and name == "training":
            continue
        source = ROOT / name
        if name == "examples":
            if not include_examples:
                continue
            if not source.is_dir():
                raise SystemExit(
                    "缺少 examples/：演示输入属完整材料的一部分，"
                    "请先运行 python scripts/make_examples.py"
                )
        copied += copy_tree(source, target / name, extra)
    for name in ROOT_FILES:
        copied += copy_file(ROOT / name, target / name)
    script_files = _competition_script_files(model_mode)
    for name in script_files:
        copied += copy_file(ROOT / "scripts" / name, target / "scripts" / name)
    for name in DOC_FILES:
        copied += copy_file(ROOT / "docs" / name, target / "docs" / name)
    for name in DOC_LEGAL_FILES:
        copied += copy_file(ROOT / "docs" / "legal" / name, target / "docs" / "legal" / name)
    for name in DATA_FILES:
        copied += copy_file(ROOT / "data" / name, target / "data" / name)
    for name in DATA_TREES:
        copied += copy_tree(ROOT / "data" / name, target / "data" / name)
    for name in LEGAL_SOURCE_FILES:
        copied += copy_file(ROOT / "legal" / "sources" / name, target / "legal" / "sources" / name)
    for name in LEGAL_TEMPLATE_FILES:
        copied += copy_file(ROOT / "legal" / "templates" / name, target / "legal" / "templates" / name)
    for src, dst in KNOWLEDGE_COPIES:
        copied += copy_tree(ROOT / src, target / dst)
    for name in DATA_FILES:
        copied += copy_file(ROOT / "data" / name, target / "knowledge" / "data" / name)
    for name in DATA_TREES:
        copied += copy_tree(
            ROOT / "data" / name, target / "knowledge" / "data" / name
        )
    # Reference-style source grouping for reviewers. Root-level copies remain the
    # executable compatibility layout used by Docker, setuptools and existing tests.
    for name, extra in TREES:
        if name in {"lexaegis", "frontend", "constraints", "LICENSES", "training"}:
            if model_mode == "interface-only" and name == "training":
                continue
            copied += copy_tree(ROOT / name, target / "src" / name, extra)
    for name in script_files:
        copied += copy_file(ROOT / "scripts" / name, target / "src" / "scripts" / name)
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "requirements.lock"):
        copied += copy_file(ROOT / name, target / "src" / name)
    (target / "src" / "README.md").write_text(SOURCE_README, encoding="utf-8")
    screenshot_source = SCREENSHOT_SOURCE
    copied += copy_tree(
        screenshot_source,
        target / "examples" / "four_boundary_demo",
        frozenset({"功能页面截图清单.json", "功能页面截图说明.md"}),
    )
    for name in ("synthetic_labor.docx", "synthetic_scan.pdf"):
        copied += copy_file(
            ROOT / "examples" / name, target / "examples" / "formal_upload" / name
        )
    if model_mode == "bundled":
        if model_assets_dir is not None:
            copied += copy_supplied_model_assets(target, model_assets_dir)
        elif model_source is not None and repro_source is not None:
            copied += copy_competition_model(target, model_source, repro_source)
        else:
            raise SystemExit("bundled 模式需要 --model-assets-dir 或旧版模型与复现目录参数")
    (target / "knowledge" / "README.md").write_text(KNOWLEDGE_README, encoding="utf-8")
    (target / "container").mkdir(parents=True, exist_ok=True)
    copied += copy_file(ROOT / "container" / "docker-entrypoint.sh", target / "container" / "docker-entrypoint.sh")
    _load_export_prompts().export(target / "prompts")
    return copied + 4


PRODUCTION_FIXED_FILES = (
    "compose.yaml", "compose.demo.yaml", "compose.integration.yaml", ".env.example",
    "requirements.lock", "frontend/pnpm-lock.yaml", "NOTICE",
    "scripts/windows/lexaegis.ps1", "scripts/package_delivery.py",
    "docs/DUAL_TRACK_DEPLOY.md", "docs/DUAL_TRACK_ACCEPTANCE.md",
    "docs/PROVENANCE.md", "docs/DELIVERY_EDITIONS.md",
)


def production_status() -> dict:
    return {
        "schema_version": 1,
        "edition": "production_staging",
        "version": "1.0.0",
        "build_status": "not_built",
        "production_acceptance": "not_attested",
        "formal_dispatch": "blocked",
        "real_cloud_success_count": 0,
        "missing_release_inputs": [
            "images.tar",
            "release-build-manifest.json(status=verified)",
            "lexaegis wheel matching manifest",
            "image-bound dependencies.json",
            "target-environment acceptance evidence",
        ],
        "models": "register_and_verify_separately",
    }


def copy_production_staging(target: Path) -> int:
    """Copy only production delivery tooling; never fabricate signed artifacts."""
    copied = 0
    for name in PRODUCTION_FIXED_FILES:
        copied += copy_file(ROOT / name, target / name)
    copied += copy_tree(ROOT / "LICENSES", target / "LICENSES")
    copied += copy_tree(ROOT / "models" / "catalog", target / "models" / "catalog")
    (target / "README.md").write_text(PRODUCTION_README, encoding="utf-8")
    (target / "release-inputs").mkdir(parents=True, exist_ok=True)
    (target / "release-inputs" / "README.md").write_text(
        PRODUCTION_INPUTS_README, encoding="utf-8"
    )
    (target / "MODEL_ASSET_REQUIREMENTS.md").write_text(
        "# 生产端侧模型资产要求\n\n"
        f"部署声明文件：`models/catalog/{PRODUCTION_EDGE_MODEL_CATALOG}`。生产权重不得从比赛目录静默继承；"
        "须核对分发许可、文件大小和 SHA-256，并将记录绑定到目标环境。默认文件名为 "
        f"`{PRODUCTION_EDGE_MODEL_FILENAME}`。权重存在不等于 edge 服务、32K、GPU 或质量验收通过。\n",
        encoding="utf-8",
    )
    (target / "DELIVERY_STATUS.json").write_text(
        json.dumps(production_status(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return copied + 4


def scan_tree(target: Path, *, allow_claims: bool = False) -> list[str]:
    """Risky-content findings for every file under target. Never prints matched secrets."""
    findings = []
    for item in sorted(target.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(target)
        forbidden = set(relative.parts) & FORBIDDEN_SEGMENTS
        generated_frontend = (
            relative.parts[:2] == ("frontend", "dist")
            or relative.parts[:3] == ("src", "frontend", "dist")
        )
        if forbidden and not (forbidden == {"dist"} and generated_frontend):
            findings.append(f"{relative}: 命中禁用目录段")
            continue
        if item.suffix.lower() in UNSCANNABLE_SUFFIXES:
            findings.append(f"{relative}: 不可扫描的旧版 Office 格式，不得随包")
            continue
        exempt = item.name in CLAIM_SCAN_EXEMPT
        for finding in scan_content(item, allow_claims=allow_claims or exempt):
            findings.append(f"{relative}: {finding}")
    return findings


def audit(paths) -> int:
    """Scan the given files/dirs strictly and report findings; builds nothing."""
    findings = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            findings.extend(scan_tree(path))
        elif path.is_file():
            for finding in scan_content(path):
                findings.append(f"{path}: {finding}")
        else:
            findings.append(f"{raw}: 路径不存在")
    for finding in findings:
        print(f"[audit] {finding}")
    print(f"[audit] {len(findings)} 项命中" if findings else "[audit] 未发现风险内容")
    return 1 if findings else 0


def _finish(target: Path, copied: int) -> int:
    """Validate the assembled tree; delete it entirely on any finding."""
    findings = scan_tree(target)
    if findings:
        for finding in findings:
            print(f"[validate] {finding}", file=sys.stderr)
        shutil.rmtree(target, ignore_errors=True)
        print(f"校验未通过（{len(findings)} 项），已删除 {target}", file=sys.stderr)
        return 1
    print(f"装配完成：{target}（{copied} 个文件，扫描 0 命中）")
    return 0


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _competition_readme(model_mode: str) -> str:
    model_section = (
        "本包采用 `interface-only`：保留 OpenAI-compatible `/v1` 接口、配置和测试桩，"
        "不含权重、训练产物或 Notebook。详情见 `docs/EDGE_MODEL_INTERFACE.md`。"
        if model_mode == "interface-only" else
        "本包采用 `bundled`：包含由只读模型输入规范化得到的 merged safetensors、最终 LoRA、"
        "训练 checkpoint 与 Base Q4 GGUF。逐文件哈希见 `models/MODEL_ASSET_MANIFEST.json`；"
        "随包不等于质量、许可、目标硬件或生产适用性验收通过。"
    )
    return f"""# 案隐盾 LexAegis · 比赛版智能体作品及其完整材料

本地优先的法律披露工作台，版本 **V1.0（1.0.0）**。本目录可独立阅读、从源码启动并自检；
仅接受公开合成演示材料，正式外发保持失败关闭。

## 快速启动

### Docker

```bash
docker build -t lexaegis-submission .
docker run --rm -p 127.0.0.1:8765:8765 -v ./models:/models:ro lexaegis-submission
```

以启动输出中的实际端口和一次性口令为准，不要把工作台暴露到非受控网络。

### 源码

```bash
python -m pip install -e ".[test]"
cd frontend && pnpm install --frozen-lockfile && pnpm build && cd ..
lexaegis start --profile demo
```

演示工作台通常为 `http://127.0.0.1:48765`。演示只接受内置合成材料。

## 四个功能边界

1. `01-完整披露流程`：模型初检允许、人工复核允许、独立审批，第三条成功是这一次请求的云端真实发送（`transport=cloud`，`provenance=cloud`）。随包功能截图不是这次发送记录。产品闩仍是 `blocked`。
2. `02-人工复核否决`：模型初检允许，但人工否决；批准与执行不可继续。
3. `03-组合线索风险`：边侧模型审核识别组合线索风险并在人工批准前阻断。
4. `04-主动停止`：停止后不可继续，刷新后状态保持。

完整流程按“材料与事实 → 披露方案 → 风险与审批 → 摘要与回链”展开。当前 16 张功能页面
截图及同名说明在 `examples/four_boundary_demo/`；公共功能页面单独归入 `00-公共功能页面/`。

## 边侧模型

{model_section}

运行时通过 `LEX_EDGE_URL` 与 `LEX_EDGE_MODEL` 接入；接口不可用时不得把原文转发到其他端点。

## 目录

- `src/`：评审浏览入口；根层 `lexaegis/`、`frontend/`、`scripts/` 是逐文件一致的运行副本。
- `examples/`：四边界演示证据和公开合成上传样例。
- `knowledge/`、`prompts/`：从当前运行时权威来源装配的知识与提示词快照。
- `tests/`：可随包执行的测试；依赖内部未交付法学资产或历史录屏材料的测试已排除并在清单解释。
- `DELIVERY_STATUS.json`：装配模式与本次验证实录。
- `FILE_INVENTORY.sha256`：除清单自身外的逐文件 SHA-256。

## 验证

```bash
python scripts/verify_competition_delivery.py .
python -m pytest -q
cd frontend && pnpm exec tsc --noEmit && pnpm build
```

Docker 或浏览器测试未执行时，`DELIVERY_STATUS.json` 会明确记录 `not_run`，不会写成通过。

## 已知限制

- 合成演示的 `mock` 摘要不是云模型生成结果。
- 健康检查、代码测试或模型文件完整，均不能替代真实隔离收据、法律复核和逐请求授权。
- 身份分词不等于匿名化；所有正式案件仍受现行门禁约束。
"""


def _submission_manifest(model_mode: str) -> str:
    model_row = (
        "| 边侧模型接口 | `docs/EDGE_MODEL_INTERFACE.md`、`.env.example`、接口代码与测试；资产状态 `deferred` |"
        if model_mode == "interface-only" else
        "| 边侧模型及微调成果 | `models/`、`training/grpo/`、`models/MODEL_ASSET_MANIFEST.json` |"
    )
    exclusion = (
        "模型权重、Adapter、GGUF、Notebook、训练输出和模型缓存"
        if model_mode == "interface-only" else
        "模型下载缓存、Notebook 和未登记模型文件"
    )
    return f"""# 比赛提交材料清单

本目录对应“智能体作品及其完整材料”，按评审阅读、运行和自检三种需要组织。

| 材料 | 位置 |
| --- | --- |
| 后端、前端和装配源码 | `src/`；根层同名目录为逐文件一致的运行兼容副本 |
| 容器与配置 | `Dockerfile`、`compose*.yaml`、`.env.example`、`container/` |
| 四边界功能证据 | `examples/four_boundary_demo/` |
| 公开合成上传样例 | `examples/formal_upload/` |
| 运行提示词 | `prompts/` |
| 知识与法源资源 | `knowledge/`、`packs/`、`legal/sources/`、`data/mock_labor_v1/` |
{model_row}
| 可随包测试 | `tests/` |
| 依赖与许可 | `DEPENDENCIES.md`、锁文件、`NOTICE`、`LICENSES/`、`THIRD_PARTY_NOTICES.md` |
| 状态与完整性 | `DELIVERY_STATUS.json`、`FILE_INVENTORY.sha256` |

## 未纳入

- 真实案件、案号、数据库、日志、密钥、`.env`、运行缓存和历史出站包；
- {exclusion}；
- `tests/test_legal_asset_import.py`：依赖未交付的内部法计交接资产；
- `tests/test_adapted_recording.py`、`tests/test_demo_document_import.py`：依赖历史录屏转换材料，非当前四边界证据。

上述测试排除只限定交付包的自包含测试范围，不会被表述为通过。
"""


def _dependencies(model_mode: str) -> str:
    model_note = (
        "模型运行时不随包固定；部署者提供 OpenAI-compatible `/v1` 服务。"
        if model_mode == "interface-only" else
        "模型文件随包，但推理服务仍由部署者按目标硬件提供 OpenAI-compatible `/v1` 端点。"
    )
    return f"""# 依赖说明

- Python 3.12+；Python 依赖以 `requirements.lock` 与 `pyproject.toml` 为准。
- Node.js 22+、pnpm 11；前端锁文件为 `frontend/pnpm-lock.yaml`。
- Docker Engine 24+（可选）；镜像由根目录 `Dockerfile` 构建。
- {model_note}
- 比赛离线演示不需要云端 API Key；任何凭据只能由运行者通过环境注入。
"""


def _third_party_notices(model_mode: str) -> str:
    model_note = (
        "本形态不分发模型文件。" if model_mode == "interface-only" else
        "模型来源文件哈希、规范化关系和验证边界见 `models/MODEL_ASSET_MANIFEST.json`；"
        "提交人仍须核对上游许可与比赛分发条款。"
    )
    return (
        "# 第三方与模型资源说明\n\n"
        "Python、前端与基础设施组件的归属和许可见 `NOTICE`、`LICENSES/` 与 "
        "`docs/THIRD_PARTY.md`。" + model_note + "\n"
    )


def _container_readme(model_mode: str) -> str:
    return (
        "# 容器材料\n\n根目录 `Dockerfile` 是比赛演示入口；`compose*.yaml` 描述演示、生产参考及联调形态。"
        "边侧模型通过 OpenAI-compatible `/v1` 独立接入。"
        + ("本形态不在容器内携带或自动启动权重。" if model_mode == "interface-only" else
           "挂载 `./models` 到 `/models` 后，单容器入口会用 Linux llama-server 读取随包 GGUF。")
        + "容器探测不能替代本请求隔离收据。\n"
    )


def _load_delivery_verifier():
    import importlib.util

    path = ROOT / "scripts" / "verify_competition_delivery.py"
    spec = importlib.util.spec_from_file_location("_competition_delivery_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_inventory(target: Path) -> int:
    lines = []
    for item in sorted(target.rglob("*")):
        if item.is_file() and item.name != "FILE_INVENTORY.sha256":
            lines.append(
                f"{sha256_file(item).removeprefix('sha256:')}  {item.relative_to(target).as_posix()}"
            )
    (target / "FILE_INVENTORY.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def _validation_defaults() -> dict:
    return {
        name: {"status": "not_run", "note": "装配前未提供本次运行记录"}
        for name in (
            "backend_tests", "frontend_typecheck", "frontend_build",
            "browser_four_boundaries", "source_start", "docker_build_and_smoke",
            "delivery_self_check", "archive_reextract_check",
        )
    }


def _delivery_status(model_mode: str, validation_record: Path | None) -> dict:
    validation = _validation_defaults()
    if validation_record is not None:
        loaded = json.loads(validation_record.read_text(encoding="utf-8"))
        validation.update(loaded.get("validation", loaded))
    return {
        "schema_version": 1,
        "edition": "competition",
        "version": "1.0.0",
        "git_commit": _git_commit(),
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "model_mode": model_mode,
        "edge_model_artifact_status": (
            "deferred" if model_mode == "interface-only" else "bundled_unvalidated_candidate"
        ),
        "formal_dispatch": "blocked",
        "real_cloud_success_count": 0,
        "demo_boundaries": [
            "complete_disclosure", "human_review_veto", "linkage_risk", "active_stop"
        ],
        "validation": validation,
    }


def _create_archive(target: Path, archive_path: Path) -> None:
    temporary = archive_path.with_name(archive_path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    stored = {".gguf", ".safetensors", ".zip", ".png", ".pdf", ".docx", ".xlsx"}
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        for item in sorted(target.rglob("*")):
            if not item.is_file():
                continue
            arcname = (Path(target.name) / item.relative_to(target)).as_posix()
            compression = zipfile.ZIP_STORED if item.suffix.lower() in stored else zipfile.ZIP_DEFLATED
            archive.write(item, arcname, compress_type=compression, compresslevel=6)
    os.replace(temporary, archive_path)


def _verify_archive(archive_path: Path, target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="lexaegis-archive-check-", dir=target.parent) as raw:
        extracted_root = Path(raw)
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad:
                raise SystemExit(f"ZIP CRC 校验失败：{bad}")
            archive.extractall(extracted_root)
        extracted = extracted_root / target.name
        errors = _load_delivery_verifier().verify(extracted, check_inventory=True)
        if errors:
            raise SystemExit("ZIP 重新解压验证失败：" + "；".join(errors[:5]))
        original_files = sum(1 for item in target.rglob("*") if item.is_file())
        extracted_files = sum(1 for item in extracted.rglob("*") if item.is_file())
        if original_files != extracted_files:
            raise SystemExit(
                f"ZIP 重新解压文件数不一致：{original_files} != {extracted_files}"
            )


def build_part1(
    out_root: Path, model_source: Path | None = None, repro_source: Path | None = None,
    *, force: bool = False, model_mode: str = "interface-only",
    model_assets_dir: Path | None = None, validation_record: Path | None = None,
) -> int:
    if model_mode == "bundled" and model_assets_dir is None:
        if model_source is None or repro_source is None:
            raise SystemExit("bundled 模式需要 --model-assets-dir 或旧版模型与复现目录参数")
        validate_competition_model(model_source)
        validate_repro_source(repro_source)
    out_root.mkdir(parents=True, exist_ok=True)
    target = out_root / PART1
    if target.exists() and not force and not (target / GENERATED_MARKER).is_file():
        raise SystemExit(f"目标目录已存在且不是本脚本产物，拒绝覆盖：{target}")
    temporary = out_root / f".{PART1}.building-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    _prepare_target(temporary, force=True)
    backup = out_root / f".{PART1}.previous-{os.getpid()}"
    try:
        copied = copy_allowlist(
            temporary, model_source, repro_source, model_mode=model_mode,
            model_assets_dir=model_assets_dir,
        )
        (temporary / "README.md").write_text(
            _competition_readme(model_mode), encoding="utf-8"
        )
        (temporary / "SUBMISSION_MANIFEST.md").write_text(
            _submission_manifest(model_mode), encoding="utf-8"
        )
        (temporary / "DEPENDENCIES.md").write_text(
            _dependencies(model_mode), encoding="utf-8"
        )
        (temporary / "THIRD_PARTY_NOTICES.md").write_text(
            _third_party_notices(model_mode), encoding="utf-8"
        )
        (temporary / "container" / "README.md").write_text(
            _container_readme(model_mode), encoding="utf-8"
        )
        status = _delivery_status(model_mode, validation_record)
        status["validation"]["delivery_self_check"] = {
            "status": "passed", "note": "目录结构、源码镜像、敏感内容与演示材料自检通过"
        }
        status_path = temporary / "DELIVERY_STATUS.json"
        status_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        findings = scan_tree(temporary)
        if findings:
            raise SystemExit("交付敏感内容扫描失败：" + "；".join(findings[:10]))
        _write_inventory(temporary)
        errors = _load_delivery_verifier().verify(temporary, check_inventory=True)
        if errors:
            raise SystemExit("交付自检失败：" + "；".join(errors[:10]))

        if target.exists():
            target.replace(backup)
        temporary.replace(target)
        if backup.exists():
            shutil.rmtree(backup)

        archive_path = out_root / f"{PART1}.zip"
        _create_archive(target, archive_path)
        _verify_archive(archive_path, target)
        status = json.loads((target / "DELIVERY_STATUS.json").read_text(encoding="utf-8"))
        status["validation"]["archive_reextract_check"] = {
            "status": "passed", "note": "ZIP CRC、重新解压、文件数量与清单哈希验证通过"
        }
        (target / "DELIVERY_STATUS.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_inventory(target)
        _create_archive(target, archive_path)
        _verify_archive(archive_path, target)
        archive_hash = sha256_file(archive_path).removeprefix("sha256:")
        (out_root / f"{PART1}.zip.sha256").write_text(
            f"{archive_hash}  {archive_path.name}\n", encoding="utf-8"
        )
        print(
            f"装配完成：{target}（复制 {copied} 个文件）\n"
            f"ZIP：{archive_path}\nSHA-256：{archive_hash}"
        )
        return 0
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise


def build_production(out_root: Path, *, force: bool = False) -> int:
    target = out_root / PRODUCTION_PART
    _prepare_target(target, force=force)
    copied = copy_production_staging(target)
    return _finish(target, copied)


def build_item5(out_root: Path, *, force: bool = False) -> int:
    """第 5 项「开源代码」：仅代码与构建必需文件 → <out>/开源代码/."""
    target = out_root / ITEM5_NAME
    _prepare_target(target, force=force)
    copied = 0
    for name, extra in ITEM5_TREES:
        copied += copy_tree(ROOT / name, target / name, extra)
    for name in ROOT_FILES:
        copied += copy_file(ROOT / name, target / name)
    for name in SCRIPT_FILES:
        copied += copy_file(ROOT / "scripts" / name, target / "scripts" / name)
    copied += len(_load_export_prompts().export(target / "prompts"))
    (target / "README.md").write_text(ITEM5_README, encoding="utf-8")
    return _finish(target, copied)


# ---------------------------------------------------------------- competition v2: source-review mirror + optional bundled edge model

COMPETITION_V2_TREES = (
    ("lexaegis", frozenset({"frontend"})),
    ("frontend", frozenset({"tsconfig.tsbuildinfo"})),
    ("packs", frozenset()),
    ("constraints", frozenset()),
    ("LICENSES", frozenset()),
)
COMPETITION_V2_SCRIPTS = (
    "build_submission.py", "export_prompts.py", "make_examples.py", "package_frontend.py",
    "package_delivery.py", "verify_wheel.py", "dev.py", "capture_competition_function_pages.cjs",
    "verify_competition_delivery.py", "verify_three_layers_live.py", "start_competition.ps1",
)
COMPETITION_V2_TEST_EXCLUDES = frozenset({
    "test_legal_asset_import.py", "test_adapted_recording.py", "test_demo_document_import.py",
    "test_grpo_adaptation.py",
})
EDGE_SOURCE_FILES = {
    "gguf": "Qwen3-4B-Base.Q4_K_M-002.gguf",
    "shard_one": "model-00001-of-00002-001.safetensors",
    "shard_two": "model-00002-of-00002-003.safetensors",
    "archive": "Qwen3_4B_GRPO_Submission-20260920T092535Z-1-004.zip",
}
EDGE_SOURCE_INTEGRITY = {
    "gguf": {"size": 2497276832, "sha256": "sha256:1e2452a1d6fe03178b6b29a04929250d40cedde7da776e8f0eb2f6277ce91fca"},
    "shard_one": {"size": 4967215360, "sha256": "sha256:b99ecfc9459614b6f7ad4f54c23e719447f8f9e9b68a21cce7e204b99dbe2dfb"},
    "shard_two": {"size": 3077766632, "sha256": "sha256:c13beea88dd4a225b2c4a4022ceb36f365deb439bb62e577e6b73085e594df32"},
    "archive": {"size": 477613835, "sha256": "sha256:65412b0c27b1c3697bf6ec12e39e55bd94299b9ffa810dde4cb5a118bcabe026"},
}
EDGE_ARCHIVE_ROOT = "Qwen3_4B_GRPO_Submission/"
EDGE_RUNTIME_GGUF = "models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf"


def _copy_generated_tree(source: Path, target: Path) -> int:
    """Copy a reviewed generated artifact tree such as frontend/dist."""
    if not source.is_dir():
        raise SystemExit(f"缺少已生成目录：{source}")
    copied = 0
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(source)
        if set(relative.parts) & {"__pycache__", ".cache", "node_modules"}:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1
    return copied


def _copy_offline_wheelhouse(target: Path) -> int:
    source = ROOT / ".artifacts" / "competition-wheelhouse"
    wheels = sorted(source.glob("*.whl"))
    if not wheels or not any(item.name.startswith("lexaegis-1.0.0-") for item in wheels):
        raise SystemExit("缺少离线 wheelhouse 或 lexaegis-1.0.0 wheel")
    destination = target / "vendor" / "wheels"
    copied = 0
    files = []
    for item in wheels:
        copied += copy_file(item, destination / item.name)
        files.append({
            "name": item.name,
            "size": item.stat().st_size,
            "sha256": sha256_file(item).removeprefix("sha256:"),
        })
    required_markers = ("cp312-win_amd64", "cp313-win_amd64", "lexaegis-1.0.0-py3-none-any")
    names = "\n".join(item.name for item in wheels)
    missing = [marker for marker in required_markers if marker not in names]
    if missing:
        raise SystemExit("离线 wheelhouse 缺少运行目标：" + "、".join(missing))
    (target / "vendor" / "WHEELHOUSE_MANIFEST.json").write_text(
        json.dumps({
            "schema_version": 1,
            "platform": "Windows x64",
            "python_versions": ["3.12", "3.13"],
            "network_required_for_install": False,
            "files": files,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return copied + 1

COMPETITION_README = """# 案隐盾 LexAegis · 比赛版智能体作品及其完整材料

这是可独立审阅与启动的比赛版材料。原始材料与身份映射留在本地；边侧模型只能把最小化候选
事实审核为“不可外发”或“可进入人工复核”，不能授予发送权。人工复核、独立审批和正式门禁
仍分别生效。当前正式外发固定为 `blocked`。

## 怎么跑

### Windows 本机（推荐，可离线）

```powershell
powershell -ExecutionPolicy Bypass -File ./start-competition.ps1
```

只要求机器已有 **Windows x64 Python 3.12 或 3.13**。脚本从 `vendor/wheels/` 离线创建
`.runtime/venv`（运行时生成，不要打进提交包），不调用 PyPI、不要求 Node.js。随后以 CPU
兼容参数启动随包 `llama-server`、GGUF、网关、worker 和工作台。

- 地址：`http://127.0.0.1:48765`，口令见终端。
- 自行指定口令须至少 **12** 个字符。
- GPU：`-GpuLayers 99`。端口可用脚本参数调整。

### Docker 单容器（构建需联网）

```powershell
docker build -t lexaegis-submission .
docker run --rm -p 127.0.0.1:8765:8765 -v ${PWD}/models:/models:ro lexaegis-submission
```

工作台：`http://127.0.0.1:8765`。口令见终端；`-e LEX_LOCAL_PASSWORD=` 同样至少 12 个字符。
挂上 `models/` 后，同一容器内的 Linux `llama-server` 读取随包 GGUF；未挂载时工作台仍启动，
边侧审核改用离线夹具。这是 native，不能自证隔离，也不构成模型质量或正式外发验收。

隔离参考形态是 `compose.demo.yaml` / `compose.yaml`（多容器），不是单容器。

## 目录

| 位置 | 作用 |
| --- | --- |
| `start-competition.ps1` | Windows 一键离线安装与启动 |
| `lexaegis/`、`frontend/` | 运行用后端与工作台；`frontend/dist` 已编入 |
| `src/` | 评审浏览镜像，与根层 `lexaegis/`、`frontend/`、`scripts/` 逐文件一致，不是第二套实现 |
| `vendor/wheels/` | Python 3.12/3.13 Windows x64 离线 wheel 与 `lexaegis-1.0.0` |
| `models/edge/qwen3-4b-grpo/` | 默认 GGUF；`transformers/` 与 `optional-lora/` 仅供复现，不自动叠加 |
| `container/edge-runtime/windows/` | 本机 Windows llama-server |
| `container/docker-entrypoint.sh`、`Dockerfile` | 单容器入口：网关 + API + worker；可选同容器边侧 |
| `compose*.yaml` | 隔离部署参考，不是提交时的单容器形态 |
| `packs/`、`legal/`、`data/` | 运行时规则包、法源整理、合成评测语料 |
| `knowledge/`、`prompts/` | 上述资源的只读副本与提示词快照；改运行请改根层原件 |
| `examples/four_boundary_demo/` | 四边界截图、同名 TXT、步骤、合成输入与预期状态 |
| `examples/formal_upload/` | 公开合成 DOCX/PDF，不属于四个固定场景 |
| `tests/`、`frontend/e2e/` | 随包回归；不含未交付录制材料或内部法学资产测试 |
| `docs/` | 规格与比赛口径 |
| `validation/live-three-layers.json` | 实时边侧三层审核证据 |
| `DELIVERY_STATUS.json`、`FILE_INVENTORY.sha256` | 装配记录与逐文件哈希 |

## 四个功能边界与三层审核

| 边界 | 结果 | 材料 |
| --- | --- | --- |
| 01 完整披露流程 | 边侧允许进入人工复核，人工允许，独立审批后按 cloud 真实发送并回链。须在 integration 上跑，`provenance=cloud`。产品闩仍是 `blocked` | `examples/four_boundary_demo/01-完整披露流程/` |
| 02 人工复核否决 | 边侧允许进入人工复核，人工否决，后续批准和执行均不可继续 | `examples/four_boundary_demo/02-人工复核否决/` |
| 03 组合线索风险 | 边侧模型审核识别组合线索风险并阻断，不进入人工批准 | `examples/four_boundary_demo/03-组合线索风险/` |
| 04 主动停止 | 停止后不可继续，刷新后状态保留 | `examples/four_boundary_demo/04-主动停止/` |

独立启动脚本默认让三个递进层次实际调用随包边侧模型；只有显式传 `-FixedDemoReview` 才改用固定
审核夹具。第三条成功是 integration 上这一次合成请求的 cloud 发送。`formal_dispatch` 仍是 `blocked`。

## 验证

```powershell
python scripts/verify_competition_delivery.py .
powershell -ExecutionPolicy Bypass -File ./start-competition.ps1 -LocalPassword local-check-ok
./.runtime/venv/Scripts/python.exe scripts/verify_three_layers_live.py `
  --base-url http://127.0.0.1:58765 --password local-check-ok
```

`tests/` 排除项见 `SUBMISSION_MANIFEST.md`。

## 已知边界

- 随包权重可校验完整性和启动接口，不等于目标硬件、抽取质量、许可再分发或正式外发已验收。
- LoRA 是可选复现资产，不能和已经融合的 GGUF 自动叠加。
- 密钥、真实案件、数据库、缓存、运行日志、`.runtime/` 均不得随包。
- 旁路的 `1-智能体作品及其完整材料.zip` 若早于本目录的 Docker 入口修正，提交前须按本目录重打。
"""

COMPETITION_MODELS_GUIDE = """# 比赛版边侧模型

本交付包的默认边侧运行资产是 `models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf`，
由 `container/edge-runtime/windows/llama-server.exe` 提供本机 OpenAI-compatible `/v1` 接口，
服务别名为 `lexaegis-qwen3-4b-grpo`。`transformers/` 中是规范命名的高精度分片和 tokenizer/config；
`optional-lora/` 仅用于可选复现实验，不能自动叠加到可能已融合的 GGUF 或 Transformers 权重。

在交付根目录执行 `python -m lexaegis.cli edge --start` 即可使用默认运行器和 GGUF。`.env.example`
给出了可覆盖的 `LEX_EDGE_*` 配置。启动后先验证 `/v1/models` 中包含上述别名，再启动工作台。

边侧审核只能得出“不可外发”或“可进入人工复核”，绝不授予发送许可。接口错误、未配置或无效
JSON 均失败关闭；未脱敏直接标识和精确组合线索还会触发本地安全基线，即使模型原始结论允许复核，
最终仍为阻断。完整协议、资产哈希、排除项和来源/许可证边界见 `EDGE_MODEL_INTERFACE.md` 与
`models/edge/qwen3-4b-grpo/ASSET_MANIFEST.json`。

随包资产已做文件结构、哈希和本机接口准备；这不等于模型质量、法律适用、目标硬件、许可证再分发
条件或正式外发已经验收。
"""

COMPETITION_DEPLOY_GUIDE = """# 比赛版运行与部署

Windows x64 安装 Python 3.12 或 3.13 后，在交付根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ./start-competition.ps1
```

脚本以 `--no-index` 从 `vendor/wheels/` 安装应用和全部依赖，前端已经编译进应用 wheel，因此不要求
Node.js、pnpm、PyPI 或仓库外文件。边侧服务默认使用随包 Qwen3 GGUF 和 Windows `llama-server`，
不下载权重，也不静默回退到远程模型。

单容器：

```powershell
docker build -t lexaegis-submission .
docker run --rm -p 127.0.0.1:8765:8765 -v ${PWD}/models:/models:ro lexaegis-submission
```

镜像把应用数据放在 `/data/app`、网关数据放在 `/data/gateway`，并默认 `demo` 档。挂载 `models/`
后，同一容器内的 Linux `llama-server` 读取随包 GGUF。未挂载时工作台仍启动。

`compose.yaml` 的 `edge` profile 同样指向
`/models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf` 和
`lexaegis-qwen3-4b-grpo`。Compose 仅为隔离部署参考；容器构建、隔离探测或本机演示都不构成
模型质量、法律适用或正式外发验收。正式外发保持 `blocked`。
"""

COMPETITION_VALIDATION_GUIDE = """# 比赛版验证口径

本次构建的实际结果以根目录 `DELIVERY_STATUS.json` 为准。可复现的检查包括：

```powershell
python scripts/verify_competition_delivery.py .
powershell -ExecutionPolicy Bypass -File ./start-competition.ps1 -LocalPassword local-check-ok
# 上面启动的是 demo。第三条真发改在 integration（58765）上跑，且云端槽位已配置：
./.runtime/venv/Scripts/python.exe scripts/verify_three_layers_live.py --base-url http://127.0.0.1:58765 --password local-check-ok
```

四功能边界的浏览器回归和功能页面截图使用内置合成材料；每张 PNG 都有同名 TXT 说明。边侧模型的
本机启动、`/v1/models` 健康检查和结构化审核仅证明接口可用，不构成质量或正式外发验收。Docker 若
因环境、镜像或网络未执行完成，状态必须记录为失败或 `not_run`，不得写为通过。
"""

COMPETITION_MANIFEST_V2 = """# 比赛提交材料清单

| 类别 | 位置 | 说明 |
| --- | --- | --- |
| 运行源码 | `lexaegis/`、`frontend/` | 后端与 React 工作台；`src/` 为逐文件镜像审阅入口 |
| 接口与门禁 | `lexaegis/providers.py`、`lexaegis/service.py`、`docs/EDGE_MODEL_INTERFACE.md` | OpenAI-compatible 边侧审核、失败关闭、人工复核与独立审批 |
| 随包模型 | `models/edge/qwen3-4b-grpo/` | GGUF 默认运行资产；规范命名的 safetensors、tokenizer 和可选 LoRA 用于复现 |
| 边侧运行器 | `container/edge-runtime/windows/` | Windows llama.cpp / llama-server 运行资产与启动说明 |
| 单容器 | `Dockerfile`、`container/docker-entrypoint.sh` | 网关 + API + worker；挂载 `models/` 时可在同一容器启动 Linux 边侧 |
| 离线运行 | `start-competition.ps1`、`vendor/wheels/` | Python 3.12/3.13 离线安装；前端已编译，无需 Node.js |
| 知识与提示词 | `knowledge/`、`prompts/` | 从根层运行时资源和任务定义导出，不收录历史内部过程稿 |
| 演示材料 | `examples/four_boundary_demo/` | 四边界截图、同名 TXT、步骤、合成输入与预期状态 |
| 正式入口样例 | `examples/formal_upload/` | 公开合成 DOCX/PDF，不属于四个固定场景 |
| 测试 | `tests/`、`frontend/e2e/` | 随包回归；排除依赖未交付录制材料、内部法学资产或训练目录的测试 |
| 依赖和许可 | `DEPENDENCIES.md`、`THIRD_PARTY_NOTICES.md`、`LICENSES/` | 版本、许可和待提交人确认事项 |
| 完整性 | `DELIVERY_STATUS.json`、`FILE_INVENTORY.sha256` | 装配状态、模型模式、验证记录和逐文件哈希 |
| 三层实测证据 | `validation/live-three-layers.json` | 实时模型响应哈希、人工结论和最终状态 |

## 未随包内容

真实案件、真实案号、密钥、数据库、缓存、运行日志、`.runtime/`、模型下载缓存、未完成训练检查点和内部法学
过程材料均被排除。`.runtime/` 由 `start-competition.ps1` 在本机生成，不得打进提交包。模型来源目录中的
checkpoint、optimizer、随机状态、调度器及训练参数不作为运行资产；其排除原因详见模型资产清单。
旁路 zip 若早于本目录当前内容，提交前须按本目录重打。
"""

COMPETITION_DEPENDENCIES_V2 = """# 依赖说明

- Windows x64；Python 3.12 或 3.13。
- `vendor/wheels/` 同时提供 cp312、cp313 和纯 Python 依赖，不需要连接 PyPI。
- `lexaegis-1.0.0-py3-none-any.whl` 已包含生产构建后的前端，不要求 Node.js/pnpm。
- `start-competition.ps1` 创建隔离的 `.runtime/venv` 并使用 `--no-index` 安装。
- 本比赛版离线闭包覆盖工作台、四功能边界和三层验证；OCR（rapidocr/paddleocr/paddlepaddle）与
  实验性训练依赖（numpy/scikit-learn）不是启动前提，未随包提供。
- 随包边侧运行：Windows x64 llama.cpp `llama-server`，资产记录在
  `container/edge-runtime/runtime-manifest.json`。
- 默认边侧权重：`models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf`。
- 运行器与模型均不下载任何资产；显卡、CUDA、内存与驱动要求以实际启动输出为准。

正式云端凭据不属于本交付物。边侧审核失败、未配置或协议不合格时，系统阻断当前请求而非回退到
外部服务。
"""

COMPETITION_NOTICES_V2 = """# 第三方与模型资产说明

Python、前端组件与项目代码许可见 `NOTICE`、`LICENSES/` 和 `docs/THIRD_PARTY.md`。

边侧运行器来自 llama.cpp Windows 发行资产；其版本、文件哈希和随附 OpenMP 许可见
`container/edge-runtime/`。模型源目录没有提供完整模型卡、许可证或再分发证明，因此
`models/edge/qwen3-4b-grpo/ASSET_MANIFEST.json` 记录了来源文件、哈希和待确认事项。随包的
Apache-2.0 文本只作为上游 Qwen 基座许可证证据副本，提交人仍须在比赛提交前核对模型、量化
转换与微调资产的许可和再分发条款。

模型文件存在、可被运行器读取或通过哈希校验，都不代表法律效果、性能、目标硬件或正式外发已验收。
"""


def _competition_scripts(mode: str) -> tuple[str, ...]:
    # Model fetch / notebook export helpers are intentionally not part of the
    # reviewable runtime package; bundled assets are copied from a frozen source.
    return COMPETITION_V2_SCRIPTS


def _write_competition_env(target: Path, mode: str) -> None:
    path = target / ".env.example"
    text = path.read_text(encoding="utf-8")
    if mode == "bundled":
        replacement = """# Competition bundled edge model: local Qwen3-4B GRPO GGUF via llama-server.
# This is a local interface recipe, not a quality or dispatch acceptance claim.
LEX_EDGE_GGUF=models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf
# LEX_EDGE_BIN=container/edge-runtime/windows/llama-server.exe
LEX_EDGE_CTX_SIZE=32768
LEX_EDGE_BATCH_SIZE=2048
LEX_EDGE_UBATCH_SIZE=512
LEX_EDGE_N_GPU_LAYERS=99
LEX_EDGE_FLASH_ATTN=on
# LEX_EDGE_SECOND_PASS_THINKING=0
# LEX_EDGE_EXTRACT_MAX_FACTS=40
# LEX_EDGE_EXTRACT_MAX_EVENTS=8
# LEX_EDGE_EXTRACT_MAX_EVENT_CHARS=80
# LEX_EDGE_EXTRACT_MAX_TOKENS=3072
# LEX_EDGE_IDLE_UNLOAD_SECONDS=300
LEX_EDGE_URL=http://127.0.0.1:8080/v1
LEX_EDGE_MODEL=lexaegis-qwen3-4b-grpo
LEX_EDGE_OUTBOUND_REVIEW=1
# LEX_DEMO_LIVE_EDGE_REVIEW=0"""
        text, replacements = re.subn(
            r"# Native GGUF \(llama-server\):.*?LEX_EDGE_MODEL=edge-small",
            replacement, text, count=1, flags=re.DOTALL,
        )
        if replacements != 1:
            raise SystemExit("无法替换比赛版 .env.example 的旧边侧模型配置")
    else:
        text = text.replace("LEX_EDGE_MODEL=edge-small", "LEX_EDGE_MODEL=edge-small\n# LEX_EDGE_OUTBOUND_REVIEW=0")
    path.write_text(text, encoding="utf-8")


def _write_competition_runtime_overrides(target: Path, mode: str) -> None:
    """Remove root-repository legacy runtime wording from the competition copy."""
    if mode != "bundled":
        return
    compose_path = target / "compose.yaml"
    compose = compose_path.read_text(encoding="utf-8")
    old_model = "/models/MiniCPM5-2B-Q4_K_M.gguf"
    if old_model not in compose or "--alias, edge-small" not in compose:
        raise SystemExit("比赛版 compose.yaml 未找到可替换的旧边侧模型配置")
    compose = compose.replace(old_model, "/models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf")
    compose = compose.replace("--alias, edge-small", "--alias, lexaegis-qwen3-4b-grpo")
    compose = compose.replace("LEX_EDGE_MODEL: ${LEX_EDGE_MODEL:-}", "LEX_EDGE_MODEL: ${LEX_EDGE_MODEL:-lexaegis-qwen3-4b-grpo}")
    compose = compose.replace(
        "LEX_EDGE_MODEL: ${LEX_EDGE_MODEL:-lexaegis-qwen3-4b-grpo}\n",
        "LEX_EDGE_MODEL: ${LEX_EDGE_MODEL:-lexaegis-qwen3-4b-grpo}\n      LEX_EDGE_OUTBOUND_REVIEW: ${LEX_EDGE_OUTBOUND_REVIEW:-1}\n",
    )
    compose_path.write_text(compose, encoding="utf-8")
    (target / "docs" / "MODELS.md").write_text(COMPETITION_MODELS_GUIDE, encoding="utf-8")
    (target / "docs" / "DEPLOY.md").write_text(COMPETITION_DEPLOY_GUIDE, encoding="utf-8")
    (target / "docs" / "VALIDATION.md").write_text(COMPETITION_VALIDATION_GUIDE, encoding="utf-8")


def _safetensor_keys(path: Path) -> set[str]:
    with path.open("rb") as stream:
        size = int.from_bytes(stream.read(8), "little")
        if size <= 2 or size > 100 * 1024 * 1024:
            raise SystemExit(f"safetensors 头部无效：{path.name}")
        try:
            header = json.loads(stream.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"safetensors 头部无法读取：{path.name}") from error
    data_start = 8 + size
    file_size = path.stat().st_size
    for key, tensor in header.items():
        if key == "__metadata__":
            continue
        offsets = tensor.get("data_offsets") if isinstance(tensor, dict) else None
        if not isinstance(offsets, list) or len(offsets) != 2 or not all(isinstance(value, int) for value in offsets):
            raise SystemExit(f"safetensors 数据偏移无效：{path.name}/{key}")
        start, end = offsets
        if start < 0 or end < start or data_start + end > file_size:
            raise SystemExit(f"safetensors 数据范围超出文件：{path.name}/{key}")
    return {key for key in header if key != "__metadata__"}


def _edge_archive_entries(source: Path) -> tuple[dict, list[str]]:
    archive_path = source / EDGE_SOURCE_FILES["archive"]
    try:
        with zipfile.ZipFile(archive_path) as archive:
            index_name = EDGE_ARCHIVE_ROOT + "merged_16bit/model.safetensors.index.json"
            index = json.loads(archive.read(index_name).decode("utf-8"))
            selected = []
            for entry in archive.infolist():
                name = entry.filename
                if not name.startswith(EDGE_ARCHIVE_ROOT) or name.endswith("/"):
                    continue
                relative = name[len(EDGE_ARCHIVE_ROOT):]
                if relative.startswith("merged_16bit/.cache/"):
                    continue
                if relative.startswith("merged_16bit/") or relative.startswith("final_lora/"):
                    selected.append(name)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"无法读取边侧模型归档：{error}") from error
    return index, sorted(selected)


def validate_edge_assets(source: Path) -> tuple[dict, list[str]]:
    source = source.resolve()
    missing = [name for name in EDGE_SOURCE_FILES.values() if not (source / name).is_file()]
    if missing:
        raise SystemExit("边侧模型源不完整，缺少：" + "、".join(missing))
    source_integrity = {}
    for key, filename in EDGE_SOURCE_FILES.items():
        path = source / filename
        expected = EDGE_SOURCE_INTEGRITY[key]
        if path.stat().st_size != expected["size"]:
            raise SystemExit(f"边侧模型源大小不匹配：{filename}")
        actual_hash = sha256_file(path)
        if actual_hash != expected["sha256"]:
            raise SystemExit(f"边侧模型源 SHA-256 不匹配：{filename}")
        source_integrity[key] = {"filename": filename, **expected}
    gguf = source / EDGE_SOURCE_FILES["gguf"]
    with gguf.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise SystemExit("边侧 GGUF 文件头无效")
        version = int.from_bytes(stream.read(4), "little")
        tensors = int.from_bytes(stream.read(8), "little")
    if version < 2 or tensors < 100:
        raise SystemExit("边侧 GGUF 版本或 tensor 数不符合预期")
    index, selected = _edge_archive_entries(source)
    weight_map = index.get("weight_map") or {}
    expected = {
        "model-00001-of-00002.safetensors": source / EDGE_SOURCE_FILES["shard_one"],
        "model-00002-of-00002.safetensors": source / EDGE_SOURCE_FILES["shard_two"],
    }
    if set(weight_map.values()) != set(expected):
        raise SystemExit("边侧模型索引分片与预期不一致")
    actual = set().union(*(_safetensor_keys(path) for path in expected.values()))
    if set(weight_map) != actual:
        raise SystemExit("边侧 safetensors 键与索引不一致")
    for filename, path in expected.items():
        expected_keys = {key for key, shard in weight_map.items() if shard == filename}
        if _safetensor_keys(path) != expected_keys:
            raise SystemExit(f"边侧 safetensors 分片不匹配：{filename}")
    return {
        "gguf_version": version, "tensor_count": tensors, "weight_map": weight_map,
        "source_integrity": source_integrity,
    }, selected


def _extract_edge_archive(source: Path, target: Path, selected: list[str]) -> int:
    copied = 0
    with zipfile.ZipFile(source / EDGE_SOURCE_FILES["archive"]) as archive:
        for name in selected:
            relative = Path(name[len(EDGE_ARCHIVE_ROOT):])
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise SystemExit("边侧模型归档包含不安全路径")
            if relative.parts[0] == "merged_16bit":
                destination = target / "models" / "edge" / "qwen3-4b-grpo" / "transformers" / Path(*relative.parts[1:])
            else:
                destination = target / "models" / "edge" / "qwen3-4b-grpo" / "optional-lora" / Path(*relative.parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as input_stream, destination.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            copied += 1
    return copied


def _copy_edge_runtime(target: Path) -> int:
    source = ROOT / ".artifacts" / "llama-server"
    if not (source / "llama-server.exe").is_file():
        raise SystemExit("缺少随包 Windows llama-server 运行器")
    copied = copy_tree(source, target / "container" / "edge-runtime" / "windows", frozenset({"llama-server.pid"}))
    entries = []
    runtime = target / "container" / "edge-runtime" / "windows"
    for item in sorted(runtime.rglob("*")):
        if item.is_file():
            entries.append({"path": item.relative_to(target).as_posix(), "size": item.stat().st_size, "sha256": sha256_file(item)})
    (target / "container" / "edge-runtime" / "runtime-manifest.json").write_text(
        json.dumps({"schema_version": 1, "source": "llama.cpp Windows release asset", "files": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "container" / "edge-runtime" / "README.md").write_text(
        "# 边侧运行器（Windows）\n\n"
        "随包 `windows/llama-server.exe` 提供本机 OpenAI-compatible `/v1` 服务。请在交付根目录执行：\n\n"
        "```powershell\npython -m lexaegis.cli edge --start\n```\n\n"
        "默认模型、端口和别名来自 `.env.example`；`LEX_EDGE_GGUF`、`LEX_EDGE_BIN` 可覆盖。服务只应绑定受控本机地址。"
        "启动成功后先访问 `/v1/models`，再启动工作台。运行器文件完整性见 `runtime-manifest.json`。\n",
        encoding="utf-8",
    )
    return copied + 2


def copy_bundled_edge_assets(target: Path, source: Path) -> int:
    details, selected = validate_edge_assets(source)
    model_root = target / "models" / "edge" / "qwen3-4b-grpo"
    runtime = model_root / "runtime" / "Qwen3-4B-GRPO.Q4_K_M.gguf"
    copied = copy_file(source / EDGE_SOURCE_FILES["gguf"], runtime)
    transformers = model_root / "transformers"
    copied += copy_file(source / EDGE_SOURCE_FILES["shard_one"], transformers / "model-00001-of-00002.safetensors")
    copied += copy_file(source / EDGE_SOURCE_FILES["shard_two"], transformers / "model-00002-of-00002.safetensors")
    copied += _extract_edge_archive(source, target, selected)
    copied += copy_file(ROOT / "LICENSES" / "Apache-2.0.txt", model_root / "license-evidence" / "Apache-2.0.txt")
    files = []
    for item in sorted(model_root.rglob("*")):
        if item.is_file():
            files.append({"path": item.relative_to(target).as_posix(), "size": item.stat().st_size, "sha256": sha256_file(item)})
    manifest = {
        "schema_version": 1,
        "model_mode": "bundled",
        "default_runtime": {"format": "GGUF Q4_K_M", "path": EDGE_RUNTIME_GGUF, "served_model": "lexaegis-qwen3-4b-grpo"},
        "high_precision_option": {"format": "safetensors", "path": "models/edge/qwen3-4b-grpo/transformers", "automatic_lora_merge": False},
        "optional_lora": {"path": "models/edge/qwen3-4b-grpo/optional-lora", "automatic_application": False, "reason": "GGUF may already be merged; avoid double application"},
        "source": {
            "directory": str(source), "files": EDGE_SOURCE_FILES,
            "integrity": details["source_integrity"],
            "archive_entries_included": [name[len(EDGE_ARCHIVE_ROOT):] for name in selected],
        },
        "validation": {"gguf_version": details["gguf_version"], "tensor_count": details["tensor_count"], "safetensors_index_tensor_count": len(details["weight_map"]), "status": "file_structure_and_hashes_verified"},
        "excluded_source_entries": ["merged_16bit/.cache", "checkpoint-100", "optimizer.pt", "rng_state.pth", "scheduler.pt", "trainer_state.json", "training_args.bin"],
        "license_status": "source_directory_did_not_include_complete_license_or_model_card; submitter_confirmation_required",
        "acceptance_scope": "artifact integrity and local interface preparation only; not a legal, quality, hardware, or formal-dispatch acceptance",
        "files": files,
    }
    (model_root / "ASSET_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (model_root / "README.md").write_text(
        "# Qwen3-4B GRPO 边侧资产\n\n"
        "默认运行的是 `runtime/Qwen3-4B-GRPO.Q4_K_M.gguf`，由随包 Windows llama-server 提供 `/v1`。"
        "`transformers/` 为规范命名后的高精度权重与 tokenizer；`optional-lora/` 是可选复现实验资产，"
        "不得与可能已融合的 GGUF 自动叠加。来源、哈希、排除项和许可待确认事项见 `ASSET_MANIFEST.json`。"
        "本目录不主张模型质量、法律适用性或正式外发已经验收。\n",
        encoding="utf-8",
    )
    return copied + 2 + _copy_edge_runtime(target)


def _copy_v2_knowledge(target: Path) -> int:
    copied = copy_tree(ROOT / "packs", target / "knowledge" / "packs")
    for name in LEGAL_SOURCE_FILES:
        copied += copy_file(ROOT / "legal" / "sources" / name, target / "knowledge" / "legal" / "sources" / name)
    for name in DATA_FILES:
        copied += copy_file(ROOT / "data" / name, target / "knowledge" / "data" / name)
    for name in DATA_TREES:
        copied += copy_tree(ROOT / "data" / name, target / "knowledge" / "data" / name)
    return copied


def _write_inventory(target: Path) -> None:
    rows = []
    for item in sorted(target.rglob("*")):
        if item.is_file() and item.name != "FILE_INVENTORY.sha256":
            rows.append(f"{sha256_file(item).removeprefix('sha256:')}  {item.relative_to(target).as_posix()}")
    (target / "FILE_INVENTORY.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _load_validation_record(path: Path | None) -> dict:
    if path is None:
        return {"status": "not_run", "note": "装配前未提供外部测试记录"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value.get("validation", value)
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"无法读取验证记录：{error}") from error


def _write_delivery_status(target: Path, mode: str, validation: dict, self_check: str) -> None:
    data = {
        "schema_version": 2,
        "edition": "competition",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "model_mode": mode,
        "edge_model_artifact_status": (
            "bundled_runtime_smoke_verified_model_quality_unvalidated"
            if mode == "bundled" and validation.get("edge_model_runtime_smoke", {}).get("status") == "passed"
            else "bundled_unvalidated_candidate" if mode == "bundled" else "deferred"
        ),
        "formal_dispatch": "blocked",
        "demo_boundaries": [
            {"id": "linkage_risk", "edge_review": "block_external", "human_review": "not_reached"},
            {"id": "human_review_veto", "edge_review": "allow_human_review", "human_review": "reject_current_request"},
            {"id": "complete_disclosure", "edge_review": "allow_human_review", "human_review": "allow_processing", "execution": "cloud"},
            {"id": "active_stop", "edge_review": "block_external", "state": "stopped_persists_after_refresh"},
        ],
        "validation": validation,
        "delivery_self_check": self_check,
        "archive": {"status": "created_after_directory_validation", "algorithm": "sha256", "verification": "reopen_and_file_by_file_reextract_hash"},
    }
    (target / "DELIVERY_STATUS.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_competition_v2(
    target: Path, mode: str, edge_source: Path | None, three_layer_evidence: Path | None
) -> int:
    copied = 0
    for name, extra in COMPETITION_V2_TREES:
        copied += copy_tree(ROOT / name, target / name, extra)
    copied += copy_tree(ROOT / "tests", target / "tests", COMPETITION_V2_TEST_EXCLUDES)
    copied += copy_tree(ROOT / "examples", target / "examples")
    copied += copy_tree(SCREENSHOT_SOURCE, target / "examples" / "four_boundary_demo")
    for name in ("synthetic_labor.docx", "synthetic_scan.pdf"):
        copied += copy_file(ROOT / "examples" / name, target / "examples" / "formal_upload" / name)
    for name in ROOT_FILES:
        copied += copy_file(ROOT / name, target / name)
    for name in _competition_scripts(mode):
        copied += copy_file(ROOT / "scripts" / name, target / "scripts" / name)
    copied += copy_file(ROOT / "scripts" / "start_competition.ps1", target / "start-competition.ps1")
    for name in DOC_FILES + ("EDGE_MODEL_INTERFACE.md",):
        copied += copy_file(ROOT / "docs" / name, target / "docs" / name)
    for name in DOC_LEGAL_FILES:
        copied += copy_file(ROOT / "docs" / "legal" / name, target / "docs" / "legal" / name)
    for name in DATA_FILES:
        copied += copy_file(ROOT / "data" / name, target / "data" / name)
    for name in DATA_TREES:
        copied += copy_tree(ROOT / "data" / name, target / "data" / name)
    for name in LEGAL_SOURCE_FILES:
        copied += copy_file(ROOT / "legal" / "sources" / name, target / "legal" / "sources" / name)
    for name in LEGAL_TEMPLATE_FILES:
        copied += copy_file(ROOT / "legal" / "templates" / name, target / "legal" / "templates" / name)
    copied += _copy_v2_knowledge(target)
    for name, extra in COMPETITION_V2_TREES:
        copied += copy_tree(ROOT / name, target / "src" / name, extra)
    copied += _copy_generated_tree(ROOT / "frontend" / "dist", target / "frontend" / "dist")
    copied += _copy_generated_tree(ROOT / "frontend" / "dist", target / "src" / "frontend" / "dist")
    for name in _competition_scripts(mode):
        copied += copy_file(ROOT / "scripts" / name, target / "src" / "scripts" / name)
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "requirements.lock"):
        copied += copy_file(ROOT / name, target / "src" / name)
    (target / "src" / "README.md").write_text(SOURCE_README, encoding="utf-8")
    (target / "knowledge" / "README.md").write_text(KNOWLEDGE_README, encoding="utf-8")
    (target / "container").mkdir(parents=True, exist_ok=True)
    copied += copy_file(ROOT / "container" / "docker-entrypoint.sh", target / "container" / "docker-entrypoint.sh")
    (target / "container" / "README.md").write_text(CONTAINER_README, encoding="utf-8")
    _load_export_prompts().export(target / "prompts")
    _write_competition_env(target, mode)
    _write_competition_runtime_overrides(target, mode)
    copied += _copy_offline_wheelhouse(target)
    if three_layer_evidence is None:
        raise SystemExit("比赛版需要 --three-layer-evidence 提供实时模型三层验证证据")
    try:
        evidence = json.loads(three_layer_evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"无法读取三层验证证据：{error}") from error
    if evidence.get("status") != "passed":
        raise SystemExit("三层验证证据未通过")
    copied += copy_file(three_layer_evidence, target / "validation" / "live-three-layers.json")
    if mode == "bundled":
        if edge_source is None:
            raise SystemExit("bundled 模式需要 --edge-assets-dir")
        copied += copy_bundled_edge_assets(target, edge_source)
    (target / "README.md").write_text(COMPETITION_README, encoding="utf-8")
    (target / "SUBMISSION_MANIFEST.md").write_text(COMPETITION_MANIFEST_V2, encoding="utf-8")
    (target / "DEPENDENCIES.md").write_text(COMPETITION_DEPENDENCIES_V2, encoding="utf-8")
    (target / "THIRD_PARTY_NOTICES.md").write_text(COMPETITION_NOTICES_V2, encoding="utf-8")
    return copied + 7


def _promote_staging(staged: Path, target: Path, force: bool) -> Path | None:
    if target.exists() and not force and not (target / GENERATED_MARKER).is_file():
        raise SystemExit(f"目标目录已存在且不是本脚本产物，拒绝覆盖：{target}")
    backup = target.with_name(f".{target.name}.previous-{os.getpid()}")
    if backup.exists():
        shutil.rmtree(backup)
    moved_old = False
    try:
        if target.exists():
            target.rename(backup)
            moved_old = True
        staged.rename(target)
    except OSError:
        if moved_old and not target.exists() and backup.exists():
            backup.rename(target)
        raise
    return backup if backup.exists() else None


def _rollback_promotion(target: Path, backup: Path | None) -> None:
    """Restore the previous directory if archive creation fails after promotion."""
    if backup is None or not backup.exists():
        return
    failed = target.with_name(f".{target.name}.failed-{os.getpid()}")
    if failed.exists():
        shutil.rmtree(failed, ignore_errors=True)
    try:
        if target.exists():
            target.rename(failed)
        backup.rename(target)
    finally:
        if failed.exists():
            shutil.rmtree(failed, ignore_errors=True)


def _write_archive(out_root: Path, target: Path, force: bool) -> tuple[Path, str]:
    archive = out_root / f"{PART1}.zip"
    if archive.exists() and not force:
        raise SystemExit(f"ZIP 已存在，拒绝覆盖：{archive}")
    # Use a per-run name.  A prior interrupted build can leave its archive under
    # antivirus/indexer inspection on Windows; it must not block the next atomic
    # archive attempt or tempt the operator to remove an in-use file.
    temporary = out_root / f".{PART1}.zip.{os.getpid()}.{os.urandom(6).hex()}.tmp"
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as result:
            for item in sorted(target.rglob("*")):
                if item.is_file():
                    result.write(item, f"{PART1}/{item.relative_to(target).as_posix()}")
        expected = {
            f"{PART1}/{item.relative_to(target).as_posix()}": sha256_file(item).removeprefix("sha256:")
            for item in target.rglob("*") if item.is_file()
        }
        # Verify file count/CRC and re-extract every member through a disposable
        # file before comparing its SHA-256.  One-at-a-time extraction avoids a
        # second full copy of the multi-GB model bundle on disk.
        with tempfile.TemporaryDirectory(prefix=".zip-reextract-", dir=out_root) as extract_root:
            extracted = Path(extract_root) / "payload.bin"
            with zipfile.ZipFile(temporary) as result:
                names = {item.filename for item in result.infolist() if not item.is_dir()}
                if names != set(expected) or result.testzip() is not None:
                    raise SystemExit("ZIP 文件集合或 CRC 校验失败")
                for name, expected_hash in expected.items():
                    with result.open(name) as source, extracted.open("wb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    if sha256_file(extracted).removeprefix("sha256:") != expected_hash:
                        raise SystemExit(f"ZIP 重新解压哈希不匹配：{name}")
                    extracted.unlink()
        if archive.exists():
            archive.unlink()
        temporary.rename(archive)
        value = sha256_file(archive).removeprefix("sha256:")
        (out_root / f"{PART1}.zip.sha256").write_text(f"{value} *{archive.name}\n", encoding="utf-8")
        return archive, value
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_competition_v2(
    out_root: Path, *, model_mode: str, edge_source: Path | None,
    validation_record: Path | None, three_layer_evidence: Path | None,
    force: bool = False,
) -> int:
    out_root.mkdir(parents=True, exist_ok=True)
    target = out_root / PART1
    archive = out_root / f"{PART1}.zip"
    if archive.exists() and not force:
        raise SystemExit(f"ZIP 已存在，拒绝覆盖：{archive}")
    if target.exists() and not force and not (target / GENERATED_MARKER).is_file():
        raise SystemExit(f"目标目录已存在且不是本脚本产物，拒绝覆盖：{target}")
    stage_parent = Path(tempfile.mkdtemp(prefix=".competition-stage-", dir=out_root))
    staged = stage_parent / PART1
    staged.mkdir()
    (staged / GENERATED_MARKER).write_text("generated by scripts/build_submission.py\n", encoding="utf-8")
    backup: Path | None = None
    promoted = False
    try:
        copied = _copy_competition_v2(staged, model_mode, edge_source, three_layer_evidence)
        validation = _load_validation_record(validation_record)
        _write_delivery_status(staged, model_mode, validation, "pending")
        findings = scan_tree(staged)
        if findings:
            raise SystemExit("交付敏感内容扫描失败：\n" + "\n".join(findings[:20]))
        _write_inventory(staged)
        verifier = ROOT / "scripts" / "verify_competition_delivery.py"
        first = subprocess.run([sys.executable, str(verifier), str(staged)], text=True, capture_output=True)
        if first.returncode:
            raise SystemExit("交付目录自检失败：\n" + first.stdout + first.stderr)
        _write_delivery_status(staged, model_mode, validation, "passed")
        _write_inventory(staged)
        second = subprocess.run([sys.executable, str(verifier), str(staged)], text=True, capture_output=True)
        if second.returncode:
            raise SystemExit("交付目录终检失败：\n" + second.stdout + second.stderr)
        backup = _promote_staging(staged, target, force)
        promoted = True
        stage_parent.rmdir()
        archive, archive_hash = _write_archive(out_root, target, force)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
    except BaseException:
        if promoted:
            _rollback_promotion(target, backup)
        shutil.rmtree(stage_parent, ignore_errors=True)
        raise
    print(f"比赛版装配完成：{target}（{copied} 个源文件）")
    print(f"ZIP：{archive}（SHA-256 {archive_hash}，已重开并逐文件重新解压哈希校验）")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="装配比赛版与生产待签封版；--item5 仍装配第 5 项「开源代码」。"
    )
    parser.add_argument(
        "--edition", choices=("competition", "production", "both"),
        default="competition", help="交付形态（默认 competition）",
    )
    parser.add_argument(
        "--model-mode", choices=("interface-only", "bundled"),
        default="bundled",
        help="比赛版边侧模型形态（默认 bundled）",
    )
    parser.add_argument(
        "--model-assets-dir", "--edge-assets-dir", dest="edge_assets_dir", type=Path,
        default=Path(r"D:\边侧模型"),
        help="bundled 模式的边侧模型资产目录（默认 D:\\边侧模型）",
    )
    parser.add_argument(
        "--validation-record", type=Path, default=None,
        help="可选的本次验证结果 JSON；未提供的项目保持 not_run",
    )
    parser.add_argument(
        "--three-layer-evidence", type=Path, default=None,
        help="实时边侧模型三层验证结果 JSON（比赛版必需）",
    )
    parser.add_argument(
        "--competition-model-dir", type=Path,
        default=Path(os.environ["LEX_COMPETITION_MODEL_DIR"])
        if os.environ.get("LEX_COMPETITION_MODEL_DIR") else None,
        help=("固定 Hugging Face 提交 0573b584… 的 Qwen3-4B-Base 完整本地快照；"
              "也可设置 LEX_COMPETITION_MODEL_DIR"),
    )
    parser.add_argument(
        "--competition-repro-dir", type=Path,
        default=Path(os.environ["LEX_COMPETITION_REPRO_DIR"])
        if os.environ.get("LEX_COMPETITION_REPRO_DIR") else None,
        help=("包含固定 SHA-256 的 Qwen3_(4B)-GRPO.ipynb 的本地目录；"
              "也可设置 LEX_COMPETITION_REPRO_DIR"),
    )
    parser.add_argument("--item5", action="store_true",
                        help=f"装配第 5 项到 <out>/{ITEM5_NAME}（默认 out 为 deliverables/）")
    parser.add_argument("--out", default=None,
                        help="输出根目录（第 1 项默认 deliverables/competition_submission，第 5 项默认 deliverables/）")
    parser.add_argument("--audit", nargs="+", metavar="PATH",
                        help="只扫描给定路径的风险内容，不装配")
    parser.add_argument("--force", action="store_true",
                        help="目标目录已存在且非本脚本产物时强制覆盖")
    args = parser.parse_args(argv)

    if args.audit:
        return audit(args.audit)
    if args.item5:
        return build_item5(Path(args.out) if args.out else DELIVERABLES, force=args.force)
    out_root = Path(args.out) if args.out else DEFAULT_OUT
    if args.edition == "competition":
        return build_competition_v2(
            out_root, model_mode=args.model_mode, edge_source=args.edge_assets_dir,
            validation_record=args.validation_record,
            three_layer_evidence=args.three_layer_evidence, force=args.force,
        )
    if args.edition == "production":
        return build_production(out_root, force=args.force)
    competition = build_competition_v2(
        out_root, model_mode=args.model_mode, edge_source=args.edge_assets_dir,
        validation_record=args.validation_record,
        three_layer_evidence=args.three_layer_evidence, force=args.force,
    )
    if competition:
        return competition
    return build_production(out_root, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
