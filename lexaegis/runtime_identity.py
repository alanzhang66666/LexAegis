"""Public runtime build identities for API, worker, and gateway.

The exposed value is derived only from the allowlisted provenance fields in a
ReleaseBuildManifest. Manifest contents, paths, parsing errors, credentials,
case data, requests, mappings, and provider responses are never returned.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pydantic import ValidationError

from .contracts import ReleaseBuildManifest
from .release_build import build_manifest_identity_hash
from .util import restrict_mode


RUNTIME_BUILD_MANIFEST_ENV = "LEX_RELEASE_BUILD_MANIFEST_PATH"
_MAX_MANIFEST_BYTES = 1024 * 1024
RuntimeProcess = Literal["api", "worker", "gateway"]
RuntimeIdentityStatus = Literal["verified", "pending", "revoked", "unconfigured", "invalid"]


@dataclass(frozen=True)
class RuntimeIdentity:
    process: RuntimeProcess
    status: RuntimeIdentityStatus
    runtime_identity_hash: str = ""

    def public(self) -> dict[str, str]:
        """Return the complete and deliberately minimal public representation."""

        return {
            "process": self.process,
            "status": self.status,
            "runtime_identity_hash": self.runtime_identity_hash,
        }


def runtime_identity(
    process: RuntimeProcess,
    manifest: ReleaseBuildManifest | Mapping[str, object] | None = None,
    *,
    manifest_path: Path | str | None = None,
) -> RuntimeIdentity:
    """Observe one process identity from the shared frozen manifest input.

    A missing or malformed input remains observable but fail-closed. Error
    details are intentionally suppressed because paths or parser messages can
    contain protected operational data.
    """

    if process not in ("api", "worker", "gateway"):
        raise ValueError("unsupported runtime process")

    loaded, failure = _load_manifest(manifest, manifest_path)
    if loaded is None:
        return RuntimeIdentity(process=process, status=failure)
    return RuntimeIdentity(
        process=process,
        status=loaded.status,
        runtime_identity_hash=build_manifest_identity_hash(loaded),
    )


def write_runtime_identity(path: Path | str, identity: RuntimeIdentity) -> None:
    """Atomically expose a worker identity through its local shared data volume."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(identity.public(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    restrict_mode(temporary, 0o600)
    temporary.replace(target)
    restrict_mode(target, 0o600)


def _load_manifest(
    manifest: ReleaseBuildManifest | Mapping[str, object] | None,
    manifest_path: Path | str | None,
) -> tuple[ReleaseBuildManifest | None, RuntimeIdentityStatus]:
    candidate: object = manifest
    if candidate is None:
        configured_path = manifest_path or os.getenv(RUNTIME_BUILD_MANIFEST_ENV, "").strip()
        if not configured_path:
            return None, "unconfigured"
        path = Path(configured_path)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_MANIFEST_BYTES:
                return None, "invalid"
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, "invalid"

    try:
        if isinstance(candidate, ReleaseBuildManifest):
            return candidate, candidate.status
        return ReleaseBuildManifest.model_validate(candidate), "verified"
    except (TypeError, ValidationError):
        return None, "invalid"
