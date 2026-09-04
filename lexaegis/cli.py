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
from .util import app_dir, exclusive_lock, restrict_mode


@contextmanager
def exclusive_worker_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(root / "worker.lock", error=ValueError("请停止 API、工作进程和网关后执行备份或恢复")):
        yield


def backup(root, gateway, destination):
    """Offline backup; SQLite backup API includes committed WAL contents."""
    root, gateway, destination = Path(root), Path(gateway), Path(destination)
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
        for file in (root / "files").glob("*"):
            if file.is_file() and not file.is_symlink():
                entries[f"app/files/{file.name}"] = file.read_bytes()
        manifest = {"version": 1, "files": {k: hashlib.sha256(v).hexdigest() for k, v in entries.items()}}
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, data in entries.items():
                archive.writestr(name, data)
        restrict_mode(destination, 0o600)


def restore(archive_path, root, gateway):
    root, gateway = Path(root), Path(gateway)
    if (root / "app.sqlite").exists() or (gateway / "gateway.sqlite").exists() or any((root / "files").glob("*")):
        raise ValueError("恢复仅支持空目标目录；不会覆盖现有案件")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > 2*1024**3:
            raise ValueError("备份解压内容超出限制")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("version") != 1:
            raise ValueError("不支持的备份版本")
        files = {}
        for name, checksum in manifest["files"].items():
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or not (name in ("app/app.sqlite", "gateway/gateway.sqlite") or (len(parts)==3 and parts[:2]==("app", "files"))):
                raise ValueError("备份含不允许的路径")
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError("备份校验失败")
            files[name] = content
        for name, content in files.items():
            parts = Path(name).parts
            target = (root if parts[0] == "app" else gateway).joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as file:
                file.write(content)
            restrict_mode(target, 0o600)


def main():
    parser = argparse.ArgumentParser(description="LexAegis local maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("import-pack")
    p.add_argument("file", type=Path)
    p = commands.add_parser("backup")
    p.add_argument("destination", type=Path)
    p.add_argument("--offline-confirm", action="store_true", required=True, help="Confirm API, worker and gateway are stopped")
    p = commands.add_parser("restore")
    p.add_argument("archive", type=Path)
    p.add_argument("--target", type=Path, required=True)
    p.add_argument("--gateway-target", type=Path, required=True)
    commands.add_parser("start", help="启动本机 API、worker 和独立网关")
    commands.add_parser("doctor", help="检查平台、目录、前端和可选能力")
    commands.add_parser("check-isolation", help="从宿主机验证 Compose 出口与卷/密钥隔离并记录结果")
    commands.add_parser("_record-isolation", help=argparse.SUPPRESS)
    p = commands.add_parser("bench", help="运行隔离实验能力检查")
    p.add_argument("--profile", choices=["ianvs-pipl"], required=True)
    p.add_argument("--input", type=Path, help="显式实验向量、显著性和真实模型输出 JSON")
    p.add_argument("--output", type=Path, help="离线 JSON 报告；拒绝覆盖现有文件")
    p.add_argument("--real-target-outputs", type=Path)
    p.add_argument("--seed", type=int, default=23)
    p.add_argument("--target-dim", type=int, default=2)
    p.add_argument("--max-norm", type=float, default=1.0)
    p.add_argument("--noise-multiplier", type=float, default=1.0)
    p.add_argument("--delta", type=float, default=1e-5)
    p.add_argument("--mask-fraction", type=float, default=.25)
    p.add_argument("--epsilon-budget", type=float)
    args = parser.parse_args()
    if args.command == "import-pack":
        store = Store(app_dir()/"app.sqlite")
        with store.transaction() as repo:
            pack = import_pack(repo, json.loads(args.file.read_text(encoding="utf-8")))
        print("Imported:", pack["id"])
    elif args.command == "backup":
        backup(app_dir(), Path(os.getenv("LEX_GATEWAY_DIR", ".data/gateway")), args.destination)
        print("Backup created:", args.destination)
    elif args.command == "restore":
        restore(args.archive, args.target, args.gateway_target)
        print("Restored. Local account password hashes are included; gateway/cloud secrets are not. Reconfigure secrets and restart services.")
    elif args.command == "start":
        from .launcher import run
        run()
    elif args.command == "doctor":
        from .diagnostics import doctor_report
        report = doctor_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["ok"] else 1)
    elif args.command == "check-isolation":
        from .diagnostics import compose_isolation_report
        report = compose_isolation_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["ok"]:
            subprocess = __import__("subprocess")
            subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-m", "lexaegis.cli", "_record-isolation"], check=True)
        raise SystemExit(0 if report["ok"] else 2)
    elif args.command == "_record-isolation":
        from .diagnostics import isolation_report
        from .util import audit, now
        report = isolation_report()
        if not report["ok"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        store = Store(app_dir()/"app.sqlite")
        with store.transaction() as repo:
            settings = repo.get("settings")
            settings.update(isolation_verified=True, deployment_mode="isolated", isolation_checked_at=now())
            repo.put("settings", settings)
            audit(repo, "", "isolation.verified", checks=report["checks"])
        print("Isolation attestation recorded in the API data store.")
    elif args.command == "bench":
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


if __name__ == "__main__":
    main()
