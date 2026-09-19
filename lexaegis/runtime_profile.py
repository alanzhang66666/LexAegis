"""Immutable startup profile and storage-directory binding.

Profiles are selected before services start. A marker beside each storage root
prevents accidentally opening data under a different profile or storage role.
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from .demo import SCENARIOS
from .util import restrict_mode

ENV_NAME = "LEX_RUN_PROFILE"
PROFILES = ("production", "demo", "integration")
PORTS = {"production": 38765, "demo": 48765, "integration": 58765}
MARKER = ".lexaegis-runtime.json"
BINDING_LOCK = ".lexaegis-runtime.binding.lock"
RESTORE_IN_PROGRESS = ".lexaegis-restore-in-progress"
def current_profile() -> str:
    """Return the validated profile captured by the service at startup."""
    return selected_profile()


def selected_profile(profile: str | None = None) -> str:
    """Resolve the process startup setting; services should capture this value."""
    requested = profile or os.environ.get(ENV_NAME) or "production"
    if requested not in PROFILES:
        raise ValueError(f"{ENV_NAME} must be one of: {', '.join(PROFILES)}")
    configured = os.environ.get(ENV_NAME)
    if configured and configured != requested:
        raise ValueError(f"{ENV_NAME} is already fixed to {configured}")
    os.environ[ENV_NAME] = requested
    _BOOT_PROFILE = requested
    return requested


def profile_config(profile: str | None = None) -> dict[str, Any]:
    profile = selected_profile(profile)
    base = Path(os.environ.get("LEX_PROFILE_ROOT", ".data/profiles")).expanduser().absolute()
    root = base / profile
    app_dir = Path(os.environ["LEX_DATA_DIR"]).expanduser().absolute() if os.environ.get("LEX_DATA_DIR") else root / "app"
    gateway_dir = Path(os.environ["LEX_GATEWAY_DIR"]).expanduser().absolute() if os.environ.get("LEX_GATEWAY_DIR") else root / "gateway"
    return {
        "runtime_profile": profile,
        "root": root,
        "app_dir": app_dir,
        "gateway_dir": gateway_dir,
        "api_port": int(os.environ.get("LEX_API_PORT", PORTS[profile])),
        "gateway_port": int(os.environ.get("LEX_GATEWAY_PORT", PORTS[profile] + 1)),
    }


def _has_payload(directory: Path) -> bool:
    return any(item.name not in (MARKER, BINDING_LOCK) for item in directory.iterdir())


def _check_restore_marker(path: Path) -> None:
    marker = path / RESTORE_IN_PROGRESS
    if marker.is_symlink():
        raise ValueError("restore-in-progress marker cannot be a symlink")
    if marker.exists():
        raise RuntimeError("runtime restore is incomplete; startup is blocked until restore is safely completed")


def _reject_symlink_path(path: Path) -> None:
    # Resolve only for normalization; inspect the lexical path so existing
    # symlink components cannot silently redirect a profile's data.
    absolute = Path(os.path.abspath(path))
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"runtime data path contains a symlink: {cursor}")


@contextmanager
def _binding_lock(path: Path):
    """Serialize first-time binding in the writable data volume itself."""
    lock_path = path / BINDING_LOCK
    if lock_path.is_symlink():
        raise ValueError("runtime binding lock cannot be a symlink")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    handle = os.fdopen(fd, "r+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt" and not handle.closed:
            import msvcrt
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        elif not handle.closed:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def bind_runtime(root: str | Path, role: str, profile: str | None = None) -> dict[str, str]:
    """Bind a storage root to one immutable profile and storage role.

    Unmarked non-empty legacy directories are refused. Empty directories can
    be initialized safely. Roles should describe storage (e.g. ``app`` or
    ``gateway``), not the process that happens to access it.
    """
    if not role or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in role.lower()):
        raise ValueError("runtime storage role must be a simple identifier")
    chosen = selected_profile(profile)
    path = Path(root).expanduser().absolute()
    _reject_symlink_path(path)
    path.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(path)
    with _binding_lock(path):
        _check_restore_marker(path)
        marker_path = path / MARKER
        expected = {"version": 1, "runtime_profile": chosen, "role": role}
        if marker_path.exists():
            if marker_path.is_symlink():
                raise ValueError("runtime marker cannot be a symlink")
            try:
                actual = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("runtime marker is unreadable") from exc
            if actual != expected:
                raise ValueError(
                    f"runtime directory binding mismatch (found profile={actual.get('runtime_profile')!r}, "
                    f"role={actual.get('role')!r}; requested profile={chosen!r}, role={role!r})"
                )
        elif _has_payload(path):
            raise ValueError("unmarked non-empty runtime directory; migrate explicitly before use")
        else:
            # O_EXCL makes creation itself atomic; the lock serializes readers
            # so no process accepts a partially written marker.
            fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as marker_file:
                marker_file.write(json.dumps(expected, sort_keys=True) + "\n")
                marker_file.flush()
                os.fsync(marker_file.fileno())
    return {**expected, "root": str(path), "marker": str(marker_path)}


def migrate_legacy_runtime(root: str | Path, role: str, profile: str,
                           declared_legacy_profile: str) -> dict[str, str]:
    """Explicitly mark an existing legacy directory after operator attestation."""
    if not role or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in role.lower()):
        raise ValueError("runtime storage role must be a simple identifier")
    if declared_legacy_profile != profile:
        raise ValueError("legacy data must retain its declared original profile")
    chosen = selected_profile(profile)
    path = Path(root).expanduser().absolute()
    _reject_symlink_path(path)
    if not path.is_dir() or not _has_payload(path):
        raise ValueError("legacy migration requires an existing populated directory")
    marker = path / MARKER
    with _binding_lock(path):
        _check_restore_marker(path)
        if marker.exists():
            if marker.is_symlink():
                raise ValueError("runtime marker cannot be a symlink")
            try:
                actual = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("runtime marker is unreadable") from exc
            if actual != {"version": 1, "runtime_profile": chosen, "role": role}:
                raise ValueError("runtime directory binding mismatch")
            return {**actual, "root": str(path), "marker": str(marker)}
        expected = {"version": 1, "runtime_profile": chosen, "role": role}
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as marker_file:
            marker_file.write(json.dumps(expected, sort_keys=True) + "\n")
            marker_file.flush()
            os.fsync(marker_file.fileno())
    return {**expected, "root": str(path), "marker": str(marker)}


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def restore_in_progress(app_root: str | Path, gateway_root: str | Path, profile: str | None = None):
    """Persist fail-closed startup markers on both roots throughout restoration.

    Both roots remain locked while files are installed and their databases are
    invalidated. An interrupted restore leaves the markers in place so normal
    app, worker, and gateway binding refuses to start from a partial snapshot.
    """
    chosen = selected_profile(profile)
    app = Path(app_root).expanduser().absolute()
    gateway = Path(gateway_root).expanduser().absolute()
    if app == gateway:
        raise ValueError("app and gateway restore targets must be separate directories")
    _reject_symlink_path(app)
    _reject_symlink_path(gateway)
    app.mkdir(parents=True, exist_ok=True)
    gateway.mkdir(parents=True, exist_ok=True)
    bind_runtime(app, "app", chosen)
    bind_runtime(gateway, "gateway", chosen)
    roots = sorted((app, gateway), key=lambda item: str(item))
    restore_id = os.urandom(16).hex()
    marker_data = json.dumps({"version": 1, "profile": chosen, "restore_id": restore_id}, sort_keys=True) + "\n"
    written: list[Path] = []
    with ExitStack() as stack:
        for root in roots:
            stack.enter_context(_binding_lock(root))
        for root in roots:
            _check_restore_marker(root)
        try:
            for root in (app, gateway):
                marker = root / RESTORE_IN_PROGRESS
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(marker_data)
                    handle.flush()
                    os.fsync(handle.fileno())
                restrict_mode(marker, 0o600)
                _fsync_directory(root)
                written.append(marker)
            yield {"restore_id": restore_id, "runtime_profile": chosen,
                   "app_marker": str(app / RESTORE_IN_PROGRESS),
                   "gateway_marker": str(gateway / RESTORE_IN_PROGRESS)}
        except BaseException:
            # A partial restore must remain unstartable; retain every marker.
            raise
        else:
            for marker in written:
                marker.unlink()
                _fsync_directory(marker.parent)


def validate_case_creation(scenario: str | None) -> None:
    profile = selected_profile()
    if profile != "demo" and SCENARIOS.get(scenario, {}).get("offline_only"):
        raise ValueError("recording cases are restricted to the offline demo profile")
    if profile in ("demo", "integration"):
        if scenario not in SCENARIOS:
            raise ValueError(f"{profile} profile accepts bundled synthetic scenarios only")
    elif scenario is not None:
        raise ValueError(f"{profile} profile cannot create demo scenarios")


def require_case_scope(case: dict[str, Any]) -> None:
    profile = selected_profile()
    mode = case.get("mode")
    if profile != "demo" and SCENARIOS.get(case.get("scenario"), {}).get("offline_only"):
        raise ValueError("recording cases are restricted to the offline demo profile")
    if profile == "production" and (mode == "demo" or case.get("scenario")):
        raise ValueError("production profile rejects demo cases")
    if profile == "demo":
        if mode != "demo" or case.get("scenario") not in SCENARIOS:
            raise ValueError("demo profile accepts bundled synthetic cases only")
    if profile == "integration":
        if mode != "demo" or case.get("scenario") not in SCENARIOS:
            raise ValueError("integration profile accepts registered synthetic cases only")
    if profile in ("demo", "integration"):
        scenario = case.get("scenario")
        if case.get("runtime_profile") != profile or case.get("data_origin") != "bundled_synthetic":
            raise ValueError("synthetic case profile and origin must be explicitly bound")
        if case.get("synthetic_manifest_hash") != synthetic_manifest_hash(scenario):
            raise ValueError("synthetic case manifest hash does not match the bundled scenario")


def validate_transport(case: dict[str, Any], transport: str) -> None:
    profile = selected_profile()
    require_case_scope(case)
    if profile == "production" and transport == "mock":
        raise ValueError("production profile rejects mock transport")
    if profile == "demo" and transport not in ("local", "mock"):
        raise ValueError("demo profile is offline; cloud transport is disabled")
    if profile == "integration" and transport not in ("local", "cloud"):
        raise ValueError("integration profile permits local or cloud transport only")


def dispatch_scope(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a frozen request's profile and synthetic provenance."""
    profile = selected_profile()
    dependencies = (request.get("dependencies") or {})
    data_origin = dependencies.get("data_origin")
    manifest_hash = dependencies.get("synthetic_manifest_hash")
    transport = request.get("transport")
    bound_profile = dependencies.get("runtime_profile")
    if bound_profile != profile:
        raise ValueError("request runtime profile does not match this gateway")
    if profile == "production":
        if request.get("mode") == "demo" or data_origin in ("synthetic", "bundled_synthetic"):
            raise ValueError("production profile rejects synthetic/demo dispatch")
        if transport not in ("local", "cloud"):
            raise ValueError("production profile permits local or cloud transport only")
    elif profile == "demo":
        if request.get("mode") != "demo" or data_origin != "bundled_synthetic" or manifest_hash not in _bundled_manifest_hashes() or transport not in ("local", "mock"):
            raise ValueError("demo requests must be bundled synthetic and offline")
    else:
        if request.get("mode") != "demo" or data_origin != "bundled_synthetic" or manifest_hash not in _bundled_manifest_hashes(include_offline=False):
            raise ValueError("integration requests must bind a synthetic manifest")
        if transport not in ("local", "cloud"):
            raise ValueError("integration requests permit local or cloud transport only")
    return {"runtime_profile": profile, "data_origin": data_origin,
            "synthetic_manifest_hash": manifest_hash, "transport": transport,
            "allowed": True}


def synthetic_manifest_hash(scenario: str) -> str:
    if scenario not in SCENARIOS:
        raise ValueError("unknown bundled synthetic scenario")
    from .util import digest
    return digest(SCENARIOS[scenario])


def _bundled_manifest_hashes(include_offline: bool = True) -> set[str]:
    return {synthetic_manifest_hash(scenario) for scenario, seed in SCENARIOS.items()
            if include_offline or not seed.get("offline_only")}


def backup_bindings(app_root: str | Path, gateway_root: str | Path, profile: str | None = None) -> dict[str, Any]:
    profile = selected_profile(profile)
    bind_runtime(app_root, "app", profile)
    bind_runtime(gateway_root, "gateway", profile)
    return {"version": 1, "runtime_profile": profile,
            "app": {"version": 1, "runtime_profile": profile, "role": "app"},
            "gateway": {"version": 1, "runtime_profile": profile, "role": "gateway"}}


def validate_backup_bindings(bindings: dict[str, Any], profile: str | None = None) -> None:
    chosen = selected_profile(profile)
    if bindings.get("version") != 1 or bindings.get("runtime_profile") != chosen:
        raise ValueError("backup runtime profile does not match destination")
    for role in ("app", "gateway"):
        item = bindings.get(role) or {}
        if item.get("runtime_profile") != chosen or item.get("role") != role:
            raise ValueError("backup storage role/profile mismatch")
