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
from .util import app_dir


@contextmanager
def exclusive_worker_lock(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("请停止 API、工作进程和网关后执行备份或恢复")
        yield


def backup(root, gateway, destination):
    """Offline backup; SQLite backup API includes committed WAL contents."""
    root, gateway, destination = Path(root), Path(gateway), Path(destination)
    with exclusive_worker_lock(root), tempfile.TemporaryDirectory() as temp:
        entries = {}
        for label, folder, db in [("app", root, "app.sqlite"), ("gateway", gateway, "gateway.sqlite")]:
            source = folder / db
            if source.exists():
                copied = Path(temp) / db
                with sqlite3.connect(source) as src, sqlite3.connect(copied) as dst:
                    src.backup(dst)
                entries[f"{label}/{db}"] = copied.read_bytes()
        for file in (root / "files").glob("*"):
            if file.is_file() and not file.is_symlink():
                entries[f"app/files/{file.name}"] = file.read_bytes()
        manifest = {"version": 1, "files": {k: hashlib.sha256(v).hexdigest() for k, v in entries.items()}}
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, data in entries.items():
                archive.writestr(name, data)
        destination.chmod(0o600)


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
            target.chmod(0o600)


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
    args = parser.parse_args()
    if args.command == "import-pack":
        store = Store(app_dir()/"app.sqlite")
        with store.transaction() as repo:
            pack = import_pack(repo, json.loads(args.file.read_text()))
        print("Imported:", pack["id"])
    elif args.command == "backup":
        backup(app_dir(), Path(os.getenv("LEX_GATEWAY_DIR", ".data/gateway")), args.destination)
        print("Backup created:", args.destination)
    elif args.command == "restore":
        restore(args.archive, args.target, args.gateway_target)
        print("Restored; credentials are not included. Reconfigure and restart services.")


if __name__ == "__main__":
    main()
