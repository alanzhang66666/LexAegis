"""Local account storage and password hashing. No external identity provider."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from contextvars import ContextVar

from .util import now


USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")
ROLES = {"admin", "case_operator", "technical_reviewer", "legal_reviewer", "approver"}
current_actor = ContextVar("lexaegis_actor", default="system")


def password_hash(password: str, salt: str | None = None) -> tuple[str, str]:
    if len(password) < 12:
        raise ValueError("本地账户口令至少 12 个字符")
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return salt, derived.hex()


def verify_password(password: str, user: dict) -> bool:
    try:
        _, candidate = password_hash(password, user["password_salt"])
        return hmac.compare_digest(candidate, user["password_hash"])
    except (KeyError, ValueError, TypeError):
        return False


def public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key not in ("password_hash", "password_salt")}


def create_user_record(username: str, display_name: str, role: str, password: str, *, created_by: str) -> dict:
    username = username.strip().lower()
    if not USERNAME.fullmatch(username):
        raise ValueError("用户名须为 3–32 位小写字母、数字、点、下划线或连字符")
    if role not in ROLES:
        raise ValueError("未知本地角色")
    display_name = display_name.strip()
    if not display_name or len(display_name) > 80:
        raise ValueError("显示名称不能为空或超过 80 字符")
    salt, hashed = password_hash(password)
    return {"id": "user:" + username, "username": username, "display_name": display_name,
            "role": role, "status": "active", "password_salt": salt, "password_hash": hashed,
            "auth_version": 1, "created_at": now(), "created_by": created_by, "updated_at": now()}


def ensure_initial_admin(store, password: str, display_name: str, *, reset_password: bool = False):
    with store.transaction() as repo:
        users = repo.list("user")
        if users:
            if reset_password:
                admin = repo.get("user:admin", "user")
                admin["password_salt"], admin["password_hash"] = password_hash(password)
                admin["auth_version"] = int(admin.get("auth_version", 1)) + 1
                admin["updated_at"] = now()
                repo.put("user", admin)
            return
        repo.put("user", create_user_record("admin", display_name or "本地管理员", "admin", password,
                                             created_by="system-bootstrap"))
