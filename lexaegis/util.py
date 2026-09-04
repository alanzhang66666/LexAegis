import hashlib
import hmac
import json
import os
import uuid
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


def audit(repo, scope, event, **metadata):
    repo.put("audit", {"id": uid("evt"), "at": now(), "actor": "local-lawyer", "event": event, "metadata": metadata}, scope)
