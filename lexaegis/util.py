import hashlib
import hmac
import json
import os
import platform
import re
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def uid(prefix="id"):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sign(value, secret):
    return hmac.new(secret.encode(), canonical(value).encode(), hashlib.sha256).hexdigest()


def edge_node_id():
    """V2.2 audit field: Kubernetes downward API injects spec.nodeName;
    unset on native runs — absent means no claim, not a failure."""
    return os.getenv("LEX_EDGE_NODE_ID") or None


def app_dir():
    return Path(os.getenv("LEX_DATA_DIR", ".data/app")).resolve()


def assert_local_filesystem(path) -> None:
    """Reject storage paths known to be on remote/network filesystems."""
    raw = str(path)
    if raw.startswith(("//", "\\\\")):
        raise ValueError("SQLite 数据目录不能位于网络文件系统")
    resolved = Path(path).resolve()
    system = platform.system()
    if system == "Windows":
        import ctypes
        drive = resolved.drive + "\\" if resolved.drive else ""
        if drive and ctypes.windll.kernel32.GetDriveTypeW(drive) == 4:
            raise ValueError("SQLite 数据目录不能位于映射网络驱动器")
        return
    mounts = []
    try:
        if system == "Linux":
            lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 3:
                    mounts.append((parts[1].replace("\\040", " "), parts[2]))
        elif system == "Darwin":
            output = subprocess.run(["mount"], capture_output=True, text=True, timeout=2, check=True).stdout
            for line in output.splitlines():
                match = re.search(r" on (.+) \(([^,]+)", line)
                if match:
                    mounts.append((match.group(1), match.group(2)))
    except (OSError, subprocess.SubprocessError):
        return
    network_types = {"nfs", "nfs4", "cifs", "smbfs", "sshfs", "fuse.sshfs", "9p"}
    candidates = [
        (Path(mount).resolve(), filesystem)
        for mount, filesystem in mounts
        if filesystem.lower() in network_types
    ]
    if any(resolved == mount or mount in resolved.parents for mount, _ in candidates):
        raise ValueError("SQLite 数据目录不能位于网络文件系统")


def restrict_mode(path, mode=0o600):
    """Best-effort Unix mode bits; on Windows NTFS this is largely a no-op."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@contextmanager
def exclusive_lock(path, *, error):
    """Non-blocking exclusive lock. Holds the handle until the context exits."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            try:
                fh.seek(0)
                if fh.read(1) == b"":
                    fh.write(b"\0")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise error from exc
        else:
            import fcntl
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fh.close()
                raise error
        yield fh
    finally:
        if os.name == "nt" and not fh.closed:
            import msvcrt
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        try:
            fh.close()
        except OSError:
            pass


def audit(repo, scope, event, **metadata):
    from .auth import current_actor
    actor = metadata.pop("actor", None) or current_actor.get()
    repo.put("audit", {"id": uid("evt"), "at": now(), "actor": actor, "event": event, "metadata": metadata}, scope)
