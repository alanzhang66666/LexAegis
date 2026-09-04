import hashlib
import hmac
import json
import os
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


def app_dir():
    return Path(os.getenv("LEX_DATA_DIR", ".data/app")).resolve()


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
            fh.seek(0)
            if fh.read(1) == b"":
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                fh.close()
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
        if os.name == "nt":
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
    repo.put("audit", {"id": uid("evt"), "at": now(), "actor": "local-lawyer", "event": event, "metadata": metadata}, scope)
