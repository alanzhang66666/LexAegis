import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from .registry import import_pack
from .storage import Store
from .util import exclusive_lock, restrict_mode


def _profile_app_dir():
    from .runtime_profile import profile_config
    return profile_config()["app_dir"]


@contextmanager
def exclusive_worker_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(root / "worker.lock", error=ValueError("请停止 API、工作进程和网关后执行备份或恢复")):
        yield


def backup(root, gateway, destination, profile=None):
    """Offline backup; SQLite backup API includes committed WAL contents."""
    root, gateway, destination = Path(root), Path(gateway), Path(destination)
    from .runtime_profile import backup_bindings
    # Bind before the lock file is created, so a new empty runtime can be
    # initialized while populated legacy directories still require migration.
    bindings = backup_bindings(root, gateway, profile)
    with exclusive_worker_lock(root), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        entries = {}
        for label, folder, db in [("app", root, "app.sqlite"), ("gateway", gateway, "gateway.sqlite")]:
            source = folder / db
            if source.exists():
                copied = Path(temp) / db
                src = sqlite3.connect(source)
                try:
                    dst = sqlite3.connect(copied)
                    try:
                        src.backup(dst)
                        dst.commit()
                    finally:
                        dst.close()
                finally:
                    src.close()
                entries[f"{label}/{db}"] = copied.read_bytes()
                for leftover in (copied, Path(str(copied) + "-wal"), Path(str(copied) + "-shm")):
                    leftover.unlink(missing_ok=True)
        for folder in ("files", "legal-evidence", "release-evidence"):
            source_root = root / folder
            if not source_root.exists():
                continue
            if source_root.is_symlink() or not source_root.is_dir():
                raise ValueError(f"受控证据目录无效：{folder}")
            for file in source_root.rglob("*"):
                if file.is_symlink():
                    raise ValueError(f"受控证据目录含符号链接：{file.relative_to(root)}")
                if file.is_file():
                    relative = file.relative_to(root).as_posix()
                    entries[f"app/{relative}"] = file.read_bytes()
        for filename in ("api-runtime-identity.json", "worker-runtime-identity.json", "release-build-manifest.json"):
            file = root / filename
            if file.is_symlink():
                raise ValueError("运行身份元数据不能是符号链接")
            if file.is_file():
                entries[f"app/{filename}"] = file.read_bytes()
        manifest = {"version": 2, "runtime_bindings": bindings,
                    "release_image": os.environ.get("LEX_RELEASE_IMAGE"),
                    "route_image": os.environ.get("LEX_ROUTE_IMAGE"),
                    "files": {k: hashlib.sha256(v).hexdigest() for k, v in entries.items()}}
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, data in entries.items():
                archive.writestr(name, data)
        restrict_mode(destination, 0o600)


def restore(archive_path, root, gateway, profile=None):
    root, gateway = Path(root), Path(gateway)
    app_payloads = ("app.sqlite", "files", "legal-evidence", "release-evidence",
                    "api-runtime-identity.json", "worker-runtime-identity.json", "release-build-manifest.json")
    gateway_payloads = ("gateway.sqlite", "gateway-runtime-identity.json")
    if (any((root / name).exists() for name in app_payloads)
            or any((gateway / name).exists() for name in gateway_payloads)):
        raise ValueError("恢复仅支持空目标目录；不会覆盖现有案件")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > 100000 or sum(i.file_size for i in infos) > 2*1024**3:
            raise ValueError("备份解压内容超出限制")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("version") not in (1, 2):
            raise ValueError("不支持的备份版本")
        from .runtime_profile import bind_runtime, selected_profile, validate_backup_bindings
        chosen = selected_profile(profile)
        if manifest.get("version") == 1:
            raise ValueError("旧版备份缺少运行环境标记；需先按原数据归属执行显式迁移")
        validate_backup_bindings(manifest.get("runtime_bindings") or {}, chosen)
        bind_runtime(root, "app", chosen)
        bind_runtime(gateway, "gateway", chosen)
        files = {}
        if len({item.filename for item in infos}) != len(infos):
            raise ValueError("备份含重复路径")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as validation_dir:
            validation_root = Path(validation_dir)
            staged = {}
            for name, checksum in manifest["files"].items():
                parts = Path(name).parts
                allowed = (
                    name in ("app/app.sqlite", "gateway/gateway.sqlite")
                    or (len(parts) >= 3 and parts[:2] == ("app", "files"))
                    or (len(parts) >= 3 and parts[:2] == ("app", "legal-evidence"))
                    or (len(parts) >= 3 and parts[:2] == ("app", "release-evidence"))
                    or (len(parts) == 2 and parts[0] == "app" and parts[1] in ("api-runtime-identity.json", "worker-runtime-identity.json", "release-build-manifest.json"))
                )
                if name.startswith(("/", "\\")) or ".." in parts or not allowed:
                    raise ValueError("备份含不允许的路径")
                content = archive.read(name)
                if hashlib.sha256(content).hexdigest() != checksum:
                    raise ValueError("备份校验失败")
                files[name] = content
                staged[name] = content
            listed = set(manifest.get("files") or {})
            actual = {item.filename for item in infos if item.filename != "manifest.json"}
            if actual != listed:
                raise ValueError("备份目录与清单不一致")
            for dbname in ("app/app.sqlite", "gateway/gateway.sqlite"):
                if dbname in staged:
                    check = validation_root / dbname.replace("/", "_")
                    check.write_bytes(staged[dbname])
                    conn = sqlite3.connect(check)
                    try:
                        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("备份数据库完整性校验失败")
                    finally:
                        conn.close()
    from .runtime_profile import restore_in_progress
    from .upgrade import prepare_restore
    restore_state = {"review_required": True}
    with restore_in_progress(root, gateway, chosen):
        for name, content in files.items():
            parts = Path(name).parts
            target = (root if parts[0] == "app" else gateway).joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as file:
                file.write(content)
            restrict_mode(target, 0o600)
        # Revoke the gateway copy first so a crash cannot leave restored gateway
        # grants usable while the application still contains old approvals.
        if (gateway / "gateway.sqlite").is_file():
            restore_state["gateway"] = prepare_restore(Store(gateway / "gateway.sqlite"), role="gateway")
        if (root / "app.sqlite").is_file():
            restore_state["app"] = prepare_restore(Store(root / "app.sqlite"), role="app")
    return restore_state


def main():
    parser = argparse.ArgumentParser(description="LexAegis local maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("import-pack")
    p.add_argument("file", type=Path)
    p = commands.add_parser("runtime-pack", help="管理独立运行库pack生命周期")
    runtime_pack_commands = p.add_subparsers(dest="runtime_pack_command", required=True)
    p = runtime_pack_commands.add_parser(
        "create-draft",
        help="从仓库labor V2草稿和导入报告派生内容寻址的运行库draft",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json",
    )
    p.add_argument("--import-report", type=Path, required=True)
    p = commands.add_parser("release", help="只读校验发布候选来源，不安装policy、不发送")
    release_commands = p.add_subparsers(dest="release_command", required=True)
    p = release_commands.add_parser(
        "verify-candidate",
        help="只读比对工作树与发布制品，输出pending/verified和漂移字段；不修改任何文件",
    )
    p.add_argument("--repository", type=Path, default=None, help="默认当前仓库根目录")
    p.add_argument("--wheel", type=Path, help="候选 wheel；缺省即视为未构建")
    p.add_argument("--runtime-pack", type=Path, help="独立运行库pack文件；缺省即视为未评审")
    p.add_argument("--frontend-dist", type=Path, help="默认 frontend/dist")
    p.add_argument("--image", action="append", default=[], metavar="NAME=sha256:...")
    p.add_argument("--migration-revision", help="默认使用本构建声明的存储修订号")
    p.add_argument("--validation-report", type=Path, help="目标验证结果JSON；缺省即视为未验证")
    p.add_argument("--reference", type=Path, help="已冻结build manifest；用于报告漂移字段")
    p = commands.add_parser("backup")
    p.add_argument("destination", type=Path)
    p.add_argument("--profile", choices=["production", "demo", "integration"])
    p.add_argument("--offline-confirm", action="store_true", required=True, help="Confirm API, worker and gateway are stopped")
    p = commands.add_parser("restore")
    p.add_argument("archive", type=Path)
    p.add_argument("--target", type=Path, required=True)
    p.add_argument("--gateway-target", type=Path, required=True)
    p.add_argument("--profile", choices=["production", "demo", "integration"])
    p = commands.add_parser("migrate-runtime", help="显式标记已有运行目录；只用于确认归属的旧数据")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--role", choices=["app", "gateway"], required=True)
    p.add_argument("--profile", choices=["production", "demo", "integration"], required=True)
    p.add_argument("--declared-legacy-profile", choices=["production", "demo", "integration"], required=True)
    p.add_argument("--confirm-existing-data-is-this-profile", action="store_true", required=True)
    p = commands.add_parser("start", help="启动本机 API、worker 和独立网关")
    p.add_argument("--profile", choices=["production", "demo", "integration"])
    p = commands.add_parser("edge", help="探测或拉起本机边侧 llama-server")
    p.add_argument("--start", action="store_true", help="端口未监听时尝试启动本机 llama-server")
    commands.add_parser("doctor", help="检查平台、目录、前端和可选能力")
    commands.add_parser("check-isolation", help="从宿主机验证 Compose 出口与卷/密钥隔离并记录结果")
    commands.add_parser("_record-isolation", help=argparse.SUPPRESS)
    p = commands.add_parser("bench", help="运行隔离实验能力检查")
    p.add_argument("--profile", choices=["ianvs-pipl", "comparable"], required=True)
    p.add_argument("--input", type=Path, help="显式实验向量、显著性和真实模型输出 JSON")
    p.add_argument("--output", type=Path, help="离线 JSON 报告；拒绝覆盖现有文件")
    p.add_argument("--dataset-id", default="mock_labor", help="comparable 对照使用的仓库数据集")
    p.add_argument("--labels", type=Path, help="标注 JSON；缺省或 pending 不生成法学分")
    p.add_argument("--split", choices=["all", "development", "blind"], default="all")
    p.add_argument("--real-target-outputs", type=Path)
    p.add_argument("--seed", type=int, default=23)
    p.add_argument("--target-dim", type=int, default=2)
    p.add_argument("--max-norm", type=float, default=1.0)
    p.add_argument("--noise-multiplier", type=float, default=1.0)
    p.add_argument("--delta", type=float, default=1e-5)
    p.add_argument("--mask-fraction", type=float, default=.25)
    p.add_argument("--epsilon-budget", type=float)
    p = commands.add_parser("dataset", help="生成、冻结、校验仓库内评测数据集")
    dataset_commands = p.add_subparsers(dest="dataset_command", required=True)
    p = dataset_commands.add_parser("generate-mock")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--seed", type=int, default=20260905)
    p = dataset_commands.add_parser("freeze")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=20260905)
    p.add_argument("--dependency-lock", type=Path)
    p = dataset_commands.add_parser("run")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = dataset_commands.add_parser("generate-semi", help="生成 100 条半合成脚手架到被忽略目录，不写入 catalog")
    p.add_argument("destination", nargs="?", type=Path, default=None, help="默认 .data/semi_labor_v1")
    dataset_commands.add_parser("list", help="列出仓库 data/ 中的评测数据集")
    dataset_commands.add_parser("validate", help="校验 data/ 哈希、合成门禁与 catalog；若存在本机脚手架则另校验哈希")
    p = dataset_commands.add_parser(
        "promote-semi",
        help="校验半合成脚手架门禁；未完成标注则拒绝写入 catalog",
    )
    p.add_argument("src", nargs="?", type=Path, default=None, help="默认 .data/semi_labor_v1")
    p.add_argument("data_root", nargs="?", type=Path, default=None, help="默认仓库 data/")
    p = dataset_commands.add_parser("show", help="显示指定数据集清单")
    p.add_argument("dataset_id", metavar="id")
    p = dataset_commands.add_parser("compare", help="五组方法离线对照；评测专用，不外发")
    p.add_argument("--dataset-id", default="mock_labor")
    p.add_argument("--output", type=Path)
    p.add_argument("--labels", type=Path, help="标注 JSON；缺省或 pending 不生成法学分")
    p.add_argument("--split", choices=["all", "development", "blind"], default="all")
    p = dataset_commands.add_parser("labels-template", help="写出空的待标注 schema，不含标签")
    p.add_argument("--output", type=Path, required=True)
    p = dataset_commands.add_parser("probe-edge", help="对仓库合成集跑边侧抽取工程指标，无法学分")
    p.add_argument("--dataset-id", default="mock_labor")
    p.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "import-pack":
        store = Store(_profile_app_dir()/"app.sqlite")
        with store.transaction() as repo:
            pack = import_pack(repo, json.loads(args.file.read_text(encoding="utf-8")))
        print("Imported:", pack["id"])
    elif args.command == "runtime-pack":
        from .runtime_pack import create_runtime_pack_draft
        store = Store(_profile_app_dir()/"app.sqlite")
        with store.transaction() as repo:
            runtime_pack = create_runtime_pack_draft(repo, args.source, args.import_report)
        print(json.dumps({
            "id": runtime_pack["id"],
            "runtime_pack_hash": runtime_pack["runtime_pack_hash"],
            "source_pack_hash": runtime_pack["source_pack_hash"],
            "import_report_hash": runtime_pack["import_report_hash"],
            "status": runtime_pack["status"],
            "dispatch_allowed": runtime_pack["dispatch_allowed"],
        }, ensure_ascii=False, indent=2))
    elif args.command == "release":
        # Read-only: no store is opened, no policy is installed, nothing is sent.
        from .release_build import (
            default_release_candidate_inputs,
            load_reference_manifest,
            load_validation_results,
            parse_image_digest_arguments,
            verify_release_candidate,
        )
        repository = args.repository or Path(__file__).resolve().parent.parent
        results, validation_report_status = load_validation_results(args.validation_report)
        reference, reference_readable = load_reference_manifest(args.reference)
        report = verify_release_candidate(
            repository,
            default_release_candidate_inputs(
                wheel_path=args.wheel,
                runtime_pack_path=args.runtime_pack,
                container_image_digests=parse_image_digest_arguments(args.image),
                migration_revision=args.migration_revision,
                frontend_dist_path=args.frontend_dist,
            ),
            results,
            reference=reference,
            reference_readable=reference_readable,
            validation_report_status=validation_report_status,
        )
        print(json.dumps(report.public(), ensure_ascii=False, indent=2))
        if not report.build_baseline_verified:
            print("未验收：发布候选未形成可验证基线，正式外发保持 blocked")
        raise SystemExit(0 if report.build_baseline_verified else 1)
    elif args.command == "backup":
        from .runtime_profile import profile_config
        config = profile_config(args.profile)
        backup(config["app_dir"], config["gateway_dir"], args.destination, config["runtime_profile"])
        print("Backup created:", args.destination)
    elif args.command == "restore":
        result = restore(args.archive, args.target, args.gateway_target, args.profile)
        print("Restored in review-required state. Unstarted approvals and jobs were invalidated; sending/unknown tasks require reconciliation. Local account password hashes are included; gateway/cloud secrets are not. Reconfigure secrets and restart services.")
    elif args.command == "migrate-runtime":
        from .runtime_profile import migrate_legacy_runtime
        result = migrate_legacy_runtime(args.root, args.role, args.profile, args.declared_legacy_profile)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "start":
        from .launcher import run
        run(args.profile)
    elif args.command == "edge":
        from .edge_runtime import edge_status, start_edge
        if args.start:
            try:
                report = start_edge()
            except (FileNotFoundError, RuntimeError, TimeoutError) as error:
                print(json.dumps({"status": "unconfigured", "detail": str(error)}, ensure_ascii=False, indent=2))
                raise SystemExit(2)
        else:
            report = edge_status()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    elif args.command == "doctor":
        from .diagnostics import doctor_report
        report = doctor_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["ok"] else 1)
    elif args.command == "check-isolation":
        from .diagnostics import compose_isolation_report
        report = compose_isolation_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            print("未验收")
            for gap in report.get("gaps") or []:
                print(f"- {gap}")
        # Host CLI records only after every Compose probe passes; native never attests.
        if report["ok"]:
            subprocess = __import__("subprocess")
            subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-m", "lexaegis.cli", "_record-isolation"], check=True)
        raise SystemExit(0 if report["ok"] else 2)
    elif args.command == "_record-isolation":
        from .diagnostics import isolated_runtime, isolation_report
        from .util import audit, now
        if not isolated_runtime():
            print(json.dumps({
                "ok": False,
                "detail": "未验收：native 不能自证隔离，拒绝写入 isolation_verified",
            }, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        report = isolation_report()
        if not report["ok"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        store = Store(_profile_app_dir()/"app.sqlite")
        with store.transaction() as repo:
            settings = repo.get("settings")
            settings.update(isolation_verified=True, deployment_mode="isolated", isolation_checked_at=now())
            repo.put("settings", settings)
            audit(repo, "", "isolation.verified", checks=report["checks"])
        print("Isolation attestation recorded in the API data store.")
    elif args.command == "bench":
        if args.profile == "comparable":
            from .dataset import default_comparable_path, run_catalog_comparison
            result = run_catalog_comparison(args.dataset_id, labels_path=args.labels, split=args.split)
            output = args.output or default_comparable_path(args.dataset_id)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            restrict_mode(output, 0o600)
            print(json.dumps({
                "status": result["status"],
                "profile": result["profile"],
                "production_dispatch": result["production_dispatch"],
                "dispatch_allowed": result["dispatch_allowed"],
                "scale": result["scale"],
                "legal_availability": result["legal_availability"],
                "output": str(output),
            }, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        from .experiments import run_ianvs_profile
        payload = None
        if args.input:
            if args.input.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("实验输入超过 100MB")
            payload = json.loads(args.input.read_text(encoding="utf-8"))
        if args.real_target_outputs:
            if args.real_target_outputs.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("目标模型输出超过 100MB")
            payload = dict(payload or {})
            payload["target_outputs"] = json.loads(args.real_target_outputs.read_text(encoding="utf-8"))
        result = run_ianvs_profile(
            payload, seed=args.seed, target_dim=args.target_dim, max_norm=args.max_norm,
            noise_multiplier=args.noise_multiplier, delta=args.delta,
            mask_fraction=args.mask_fraction, epsilon_budget=args.epsilon_budget,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            restrict_mode(args.output, 0o600)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if any(item.get("budget", {}).get("status") == "exceeded" for item in result.get("transforms", [])):
            raise SystemExit(3)
    elif args.command == "dataset":
        from .dataset import build_mock_corpus, freeze_mock_corpus, run_mock_comparison

        def read_json(path):
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("模拟数据文件超过 20MB")
            return json.loads(path.read_text(encoding="utf-8"))

        def write_once(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            restrict_mode(path, 0o600)

        if args.dataset_command == "generate-mock":
            records = build_mock_corpus(args.count, args.seed)
            write_once(args.output, {
                "schema_version": 1,
                "kind": "fully_synthetic_mock_corpus",
                "records": records,
            })
            print("Synthetic mock corpus created:", args.output)
        elif args.dataset_command == "generate-semi":
            from .data_registry import default_local_scaffold_dir, write_semi_labor_v1
            dest = args.destination if args.destination is not None else default_local_scaffold_dir()
            manifest = write_semi_labor_v1(args.destination)
            print("Created 100 synthetic records; legal annotation and adjudication remain pending.")
            print(json.dumps({
                "id": manifest.id,
                "version": manifest.version,
                "kind": manifest.kind,
                "status": manifest.status,
                "count": manifest.count,
                "freeze_status": manifest.freeze_status,
                "dispatch_allowed": manifest.dispatch_allowed,
                "path": dest.as_posix(),
            }, ensure_ascii=False, indent=2))
        elif args.dataset_command == "freeze":
            records = read_json(args.input)["records"]
            lock = args.dependency_lock
            if lock is None and Path("requirements.lock").is_file():
                lock = Path("requirements.lock")
            dependency_hash = (
                "sha256:" + hashlib.sha256(lock.read_bytes()).hexdigest()
                if lock is not None else "unrecorded"
            )
            write_once(args.output, freeze_mock_corpus(
                records, seed=args.seed, dependency_hash=dependency_hash,
            ))
            print("Technical mock freeze created:", args.output)
        elif args.dataset_command == "run":
            records = read_json(args.input)["records"]
            manifest = read_json(args.manifest)
            write_once(args.output, run_mock_comparison(records, manifest))
            print("Technical mock comparison report created:", args.output)
        elif args.dataset_command == "list":
            from .data_registry import list_datasets
            print(json.dumps(list_datasets(), ensure_ascii=False, indent=2))
        elif args.dataset_command == "validate":
            from .data_registry import default_local_scaffold_dir, validate_local_scaffold, validate_tree
            report = validate_tree()
            scaffold = default_local_scaffold_dir()
            if (scaffold / "dataset.json").is_file():
                local = validate_local_scaffold(scaffold)
                report = {
                    **report,
                    "local_scaffold": local,
                    "ok": report["ok"] and local["ok"],
                    "problems": [*report["problems"], *local["problems"]],
                }
                if local.get("warnings"):
                    report["warnings"] = local["warnings"]
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(0 if report["ok"] else 1)
        elif args.dataset_command == "promote-semi":
            from .data_registry import promote_semi_labor
            report = promote_semi_labor(args.src, args.data_root)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(0 if report["ok"] else 1)
        elif args.dataset_command == "show":
            from .data_registry import find_dataset
            path, _manifest = find_dataset(args.dataset_id)
            print(path.read_text(encoding="utf-8"), end="")
        elif args.dataset_command == "compare":
            from .dataset import default_comparable_path, run_catalog_comparison
            result = run_catalog_comparison(args.dataset_id, labels_path=args.labels, split=args.split)
            output = args.output or default_comparable_path(args.dataset_id)
            write_once(output, result)
            print(json.dumps({
                "status": result["status"],
                "production_dispatch": result["production_dispatch"],
                "dispatch_allowed": result["dispatch_allowed"],
                "scale": result["scale"],
                "legal_availability": result["legal_availability"],
                "output": str(output),
            }, ensure_ascii=False, indent=2))
        elif args.dataset_command == "labels-template":
            from .experiments import pending_labels_document
            write_once(args.output, pending_labels_document())
            print("Pending labels template written:", args.output)
        elif args.dataset_command == "probe-edge":
            from .edge_eval import probe_edge, write_probe_report
            report = probe_edge(args.dataset_id)
            path = write_probe_report(report, args.output)
            print(json.dumps({**report, "output": str(path)}, ensure_ascii=False, indent=2))
            raise SystemExit(0)


if __name__ == "__main__":
    main()
