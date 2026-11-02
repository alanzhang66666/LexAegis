"""Build-provenance collection for fail-closed formal releases.

This module only creates diagnostic/verified manifests.  It does not arm a
release policy or expose runtime identities to API, worker, or gateway code.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import ValidationError

from .contracts import (
    READINESS_CHECK_IDS,
    ReadinessCheck,
    ReadinessReport,
    ReleaseBuildManifest,
)
from .util import canonical, now


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BUILD_MANIFEST_IDENTITY_FIELDS = (
    "source_commit",
    "worktree_clean",
    "source_tree_hash",
    "documentation_hash",
    "frontend_dist_hash",
    "wheel_hash",
    "lockfile_hashes",
    "runtime_pack_hash",
    "container_image_digests",
    "migration_revision",
    "validation_results_hash",
    "status",
)
DRIFT_SENSITIVE_FIELDS = (
    "source_commit",
    "source_tree_hash",
    "documentation_hash",
    "frontend_dist_hash",
    "wheel_hash",
    "lockfile_hashes",
    "runtime_pack_hash",
    "container_image_digests",
    "migration_revision",
    "validation_results_hash",
)
DEFAULT_SOURCE_PATHS = ("lexaegis",)
DEFAULT_DOCUMENTATION_PATHS = ("docs",)
DEFAULT_FRONTEND_DIST_PATH = "frontend/dist"
DEFAULT_LOCKFILE_PATHS = ("requirements.lock", "frontend/pnpm-lock.yaml")
_MAX_INPUT_JSON_BYTES = 1024 * 1024
ReferenceStatus = Literal["absent", "matching", "drifted", "unreadable"]
ValidationReportStatus = Literal["absent", "loaded", "unreadable"]
_IGNORED_TREE_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "playwright-report",
        "test-results",
    }
)


@dataclass(frozen=True)
class WorktreeState:
    """Observed Git identity. Any inspection failure is conservatively dirty."""

    source_commit: str = ""
    clean: bool = False
    changes: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class BuildInputs:
    """Explicit artifact inputs used to construct a release build manifest.

    Paths are explicit so a repository draft pack can never be silently treated
    as the independently reviewed Runtime Pack.
    """

    source_paths: Sequence[Path | str] = ()
    documentation_paths: Sequence[Path | str] = ()
    frontend_dist_path: Path | str | None = None
    wheel_path: Path | str | None = None
    lockfile_paths: Sequence[Path | str] = ()
    runtime_pack_path: Path | str | None = None
    container_image_digests: Mapping[str, str] = field(default_factory=dict)
    migration_revision: str = ""


@dataclass(frozen=True)
class ValidationResults:
    """Named release validations and their content-addressed evidence hashes."""

    checks: Mapping[str, bool] = field(default_factory=dict)
    evidence_hashes: Mapping[str, str] = field(default_factory=dict)
    readiness: Mapping[str, ReadinessCheck] = field(default_factory=dict)
    source_commit: str = ""
    build_manifest_hash: str = ""
    request_hash: str = ""
    image_digests: Mapping[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(result is True for result in self.checks.values())

    def content_hash(self) -> str:
        if not self.checks:
            return ""
        payload = {
            "checks": dict(sorted(self.checks.items())),
            "evidence_hashes": dict(sorted(self.evidence_hashes.items())),
        }
        if self.readiness:
            payload["readiness"] = {
                key: value.model_dump(mode="json")
                for key, value in sorted(self.readiness.items())
            }
        for key, value in (
            ("source_commit", self.source_commit),
            ("build_manifest_hash", self.build_manifest_hash),
            ("request_hash", self.request_hash),
        ):
            if value:
                payload[key] = value
        if self.image_digests:
            payload["image_digests"] = dict(sorted(self.image_digests.items()))
        return _sha256(canonical(payload).encode("utf-8"))


class ReleaseBuildVerifier:
    """Collect build provenance and fail closed unless every input is verified."""

    def __init__(self, repository: Path | str):
        self.repository = Path(repository).resolve()

    def inspect_worktree(self, repository: Path | str | None = None) -> WorktreeState:
        root = Path(repository).resolve() if repository is not None else self.repository
        try:
            commit = self._git(root, "rev-parse", "--verify", "HEAD").strip()
            status = self._git(
                root,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            )
        except (OSError, subprocess.SubprocessError) as error:
            return WorktreeState(error=f"git_inspection_failed:{type(error).__name__}")

        changes = tuple(line for line in status.splitlines() if line)
        if not commit:
            return WorktreeState(
                changes=changes,
                error="git_inspection_failed:empty_commit",
            )
        return WorktreeState(
            source_commit=commit,
            clean=not changes,
            changes=changes,
        )

    def build_manifest(
        self,
        inputs: BuildInputs,
        results: ValidationResults,
        *,
        created_at: str | None = None,
        verified_by: str | None = None,
    ) -> ReleaseBuildManifest:
        """Collect all required hashes and return pending unless all gates pass.

        In particular, ``status`` is never accepted from the caller. A dirty or
        uninspectable worktree always produces a pending manifest.
        """

        worktree = self.inspect_worktree()
        source_tree_hash = self._hash_collection(inputs.source_paths)
        documentation_hash = self._hash_collection(inputs.documentation_paths)
        frontend_dist_hash = self._hash_directory(inputs.frontend_dist_path)
        wheel_hash = self._hash_file(inputs.wheel_path)
        lockfile_hashes = self._hash_lockfiles(inputs.lockfile_paths)
        runtime_pack_hash = self._hash_file(inputs.runtime_pack_path)
        image_digests = dict(sorted(inputs.container_image_digests.items()))
        validation_results_hash = results.content_hash()

        required_artifacts_present = all(
            (
                worktree.source_commit,
                source_tree_hash,
                documentation_hash,
                frontend_dist_hash,
                wheel_hash,
                runtime_pack_hash,
                inputs.migration_revision.strip(),
                validation_results_hash,
            )
        )
        lockfiles_complete = bool(lockfile_hashes) and all(lockfile_hashes.values())
        images_complete = bool(image_digests) and all(
            name.strip() and _SHA256_RE.fullmatch(digest) is not None
            for name, digest in image_digests.items()
        )
        verified = (
            worktree.clean
            and required_artifacts_present
            and lockfiles_complete
            and images_complete
            and results.passed
        )

        identity = {
            "source_commit": worktree.source_commit,
            "worktree_clean": worktree.clean,
            "source_tree_hash": source_tree_hash,
            "documentation_hash": documentation_hash,
            "frontend_dist_hash": frontend_dist_hash,
            "wheel_hash": wheel_hash,
            "lockfile_hashes": lockfile_hashes,
            "runtime_pack_hash": runtime_pack_hash,
            "container_image_digests": image_digests,
            "migration_revision": inputs.migration_revision.strip(),
            "validation_results_hash": validation_results_hash,
            "status": "verified" if verified else "pending",
        }
        identity_hash = build_manifest_identity_hash(identity)
        manifest_id = f"build_{identity_hash.removeprefix('sha256:')[:24]}"
        return ReleaseBuildManifest(
            id=manifest_id,
            source_commit=worktree.source_commit,
            worktree_clean=worktree.clean,
            source_tree_hash=source_tree_hash,
            documentation_hash=documentation_hash,
            frontend_dist_hash=frontend_dist_hash,
            wheel_hash=wheel_hash,
            lockfile_hashes=lockfile_hashes,
            runtime_pack_hash=runtime_pack_hash,
            container_image_digests=image_digests,
            migration_revision=inputs.migration_revision.strip(),
            validation_results_hash=validation_results_hash,
            status="verified" if verified else "pending",
            created_at=created_at or now(),
            verified_by=verified_by if verified else None,
        )

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=message,
            )
        return completed.stdout

    def _resolve(self, path: Path | str | None) -> Path | None:
        if path is None:
            return None
        candidate = Path(path)
        return candidate.resolve() if candidate.is_absolute() else (self.repository / candidate).resolve()

    def _hash_file(self, path: Path | str | None) -> str:
        resolved = self._resolve(path)
        if resolved is None or not resolved.is_file() or resolved.is_symlink():
            return ""
        try:
            return _sha256(resolved.read_bytes())
        except OSError:
            return ""

    def _hash_directory(self, path: Path | str | None) -> str:
        resolved = self._resolve(path)
        if resolved is None or not resolved.is_dir() or resolved.is_symlink():
            return ""
        entries = self._tree_entries(resolved, label_root=resolved)
        return _hash_entries(entries)

    def _hash_collection(self, paths: Sequence[Path | str]) -> str:
        if not paths:
            return ""
        entries: list[dict[str, str | int]] = []
        for declared in paths:
            resolved = self._resolve(declared)
            if resolved is None or not resolved.exists() or resolved.is_symlink():
                return ""
            label = self._stable_label(resolved)
            if resolved.is_file():
                try:
                    content = resolved.read_bytes()
                except OSError:
                    return ""
                entries.append({"path": label, "sha256": _sha256(content), "size": len(content)})
            elif resolved.is_dir():
                nested = self._tree_entries(resolved, label_root=self.repository)
                if not nested:
                    return ""
                entries.extend(nested)
            else:
                return ""
        return _hash_entries(entries)

    def _hash_lockfiles(self, paths: Sequence[Path | str]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for declared in paths:
            resolved = self._resolve(declared)
            label = self._stable_label(resolved) if resolved is not None else str(declared)
            hashes[label] = self._hash_file(declared)
        return dict(sorted(hashes.items()))

    def _tree_entries(self, root: Path, *, label_root: Path) -> list[dict[str, str | int]]:
        entries: list[dict[str, str | int]] = []
        try:
            candidates = sorted(root.rglob("*"), key=lambda item: item.as_posix())
            for candidate in candidates:
                relative_parts = candidate.relative_to(root).parts
                if any(part in _IGNORED_TREE_PARTS for part in relative_parts):
                    continue
                if candidate.is_symlink():
                    return []
                if not candidate.is_file():
                    continue
                content = candidate.read_bytes()
                try:
                    label = candidate.relative_to(label_root).as_posix()
                except ValueError:
                    label = candidate.relative_to(root).as_posix()
                entries.append({"path": label, "sha256": _sha256(content), "size": len(content)})
        except OSError:
            return []
        return entries

    def _stable_label(self, path: Path) -> str:
        try:
            return path.relative_to(self.repository).as_posix()
        except ValueError:
            return f"external/{path.name}"


def build_manifest_identity_input(
    manifest: ReleaseBuildManifest | Mapping[str, object],
) -> dict[str, object]:
    """Return the public, canonical build identity shared by every runtime.

    Operational metadata such as the verifier identity and creation time is
    intentionally excluded. Only the frozen provenance fields participate.
    """

    values: Mapping[str, object]
    if isinstance(manifest, ReleaseBuildManifest):
        values = manifest.model_dump()
    else:
        values = manifest
    return {field: values[field] for field in BUILD_MANIFEST_IDENTITY_FIELDS}


def build_manifest_identity_hash(
    manifest: ReleaseBuildManifest | Mapping[str, object],
) -> str:
    """Hash the allowlisted build identity without exposing manifest content."""

    return _sha256(canonical(build_manifest_identity_input(manifest)).encode("utf-8"))


def manifest_drift(
    reference: ReleaseBuildManifest | Mapping[str, object],
    candidate: ReleaseBuildManifest | Mapping[str, object],
) -> tuple[str, ...]:
    """Return the provenance fields that drifted away from a frozen manifest.

    Any drift invalidates the reference manifest for formal release; the caller
    must collect a new verified manifest and re-freeze the request.
    """

    frozen = build_manifest_identity_input(reference)
    observed = build_manifest_identity_input(candidate)
    return tuple(
        field_name
        for field_name in DRIFT_SENSITIVE_FIELDS
        if frozen.get(field_name) != observed.get(field_name)
    )


def incomplete_manifest_inputs(manifest: ReleaseBuildManifest) -> tuple[str, ...]:
    """Name the provenance inputs that are missing, empty, or malformed."""

    missing: list[str] = []
    if not manifest.source_commit:
        missing.append("source_commit")
    for field_name in (
        "source_tree_hash",
        "documentation_hash",
        "frontend_dist_hash",
        "wheel_hash",
        "runtime_pack_hash",
        "validation_results_hash",
    ):
        if not getattr(manifest, field_name):
            missing.append(field_name)
    if not manifest.lockfile_hashes or not all(manifest.lockfile_hashes.values()):
        missing.append("lockfile_hashes")
    if not manifest.container_image_digests or not all(
        name.strip() and _SHA256_RE.fullmatch(digest) is not None
        for name, digest in manifest.container_image_digests.items()
    ):
        missing.append("container_image_digests")
    if not manifest.migration_revision:
        missing.append("migration_revision")
    return tuple(missing)


def build_readiness_report(
    manifest: ReleaseBuildManifest,
    results: ValidationResults | None = None,
    *,
    request_hash: str = "",
    mode: Literal["report_only", "enforced"] = "report_only",
    generated_at: str | None = None,
) -> ReadinessReport:
    """Build the fixed readiness view without creating a second release state machine.

    The build check is derived from the observed manifest. Other checks may be
    supplied by command-generated or manually registered validation evidence;
    absent evidence remains pending. Report bindings are checked before a
    result can influence eligibility, so a stale report is fail-closed.
    """

    results = results or ValidationResults()
    timestamp = generated_at or now()
    manifest_hash = build_manifest_identity_hash(manifest)
    binding_errors: list[str] = []
    if results.source_commit and results.source_commit != manifest.source_commit:
        binding_errors.append("source_commit 与当前构建不一致")
    if results.build_manifest_hash and results.build_manifest_hash != manifest_hash:
        binding_errors.append("build_manifest_hash 与当前构建不一致")
    if results.request_hash and results.request_hash != request_hash:
        binding_errors.append("request_hash 与当前请求不一致")
    if results.image_digests and dict(results.image_digests) != dict(manifest.container_image_digests):
        binding_errors.append("镜像 digest 与当前构建不一致")

    build_status = "pass" if manifest.status == "verified" else "pending"
    build_reason = "verified build manifest" if build_status == "pass" else (
        "构建清单未验证：" + ", ".join(incomplete_manifest_inputs(manifest))
    )
    checks: dict[str, ReadinessCheck] = {
        "build_manifest": ReadinessCheck(
            status=build_status,
            artifact_ids=[manifest.id] if manifest.status == "verified" else [],
            source_kind="command_generated",
            source_command="lexaegis release verify-candidate",
            environment={"source_commit": manifest.source_commit or "unknown"},
            generated_at=timestamp,
            valid_until=None,
            redaction_profile="synthetic-v1",
            reason=build_reason,
        )
    }
    supplied = dict(results.readiness)
    for check_id in READINESS_CHECK_IDS:
        if check_id == "build_manifest":
            continue
        value = supplied.get(check_id)
        if value is None:
            value = ReadinessCheck(
                status="pending",
                source_kind="manual_upload" if check_id in {"host_firewall", "supply_chain"} else "command_generated",
                source_command="",
                environment={},
                generated_at=timestamp,
                redaction_profile="synthetic-v1",
                reason="尚未登记与当前构建绑定的证据",
            )
        elif value.valid_until:
            try:
                expiry = datetime.fromisoformat(value.valid_until.replace("Z", "+00:00"))
                if expiry <= datetime.now(timezone.utc) and value.status == "pass":
                    value = value.model_copy(update={"status": "expired", "reason": "证据已过有效期"})
            except (TypeError, ValueError):
                value = value.model_copy(update={"status": "fail", "reason": "证据有效期格式无法核验"})
        checks[check_id] = value
    if binding_errors:
        reason = "；".join(binding_errors)
        for check_id, value in list(checks.items()):
            checks[check_id] = value.model_copy(update={
                "status": "fail",
                "reason": f"readiness 绑定失败：{reason}",
            })
    required = ("build_manifest", "compose_isolation", "host_firewall", "supply_chain")
    state = "eligible" if all(checks[name].status == "pass" for name in required) and not binding_errors else "blocked"
    return ReadinessReport(
        mode=mode,
        state=state,
        source_commit=manifest.source_commit,
        build_manifest_hash=manifest_hash,
        request_hash=request_hash,
        checks=checks,
        generated_at=timestamp,
    )


def readiness_for_context(
    context: Mapping[str, object] | None,
    *,
    request_hash: str = "",
    mode: Literal["report_only", "enforced"] = "report_only",
) -> ReadinessReport:
    """Return a report for an API context, preserving a blocked empty baseline."""
    context = context or {}
    manifest = context.get("build_manifest")
    if not isinstance(manifest, ReleaseBuildManifest):
        manifest = ReleaseBuildManifest(id="build_unverified", created_at=now())
    results = context.get("validation_results")
    if not isinstance(results, ValidationResults):
        results = ValidationResults()
    return build_readiness_report(manifest, results, request_hash=request_hash, mode=mode)


@dataclass(frozen=True)
class ReleaseCandidateReport:
    """Read-only release-candidate verdict safe to print on an operator console.

    The report deliberately carries only field names, counts, and content
    addresses. No secret, case text, identity mapping, frozen request, provider
    payload, or absolute repository path is included.
    """

    manifest_id: str
    status: str
    identity_hash: str
    worktree_clean: bool
    worktree_change_count: int
    worktree_error: str | None
    incomplete_inputs: tuple[str, ...]
    failed_validations: tuple[str, ...]
    validation_report_status: ValidationReportStatus
    reference_status: ReferenceStatus
    drift_fields: tuple[str, ...]
    build_baseline_verified: bool
    product_dispatch_state: str
    readiness: ReadinessReport | None = None
    policy_installed: bool = False
    dispatch_attempted: bool = False
    read_only: bool = True

    def public(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "status": self.status,
            "identity_hash": self.identity_hash,
            "worktree_clean": self.worktree_clean,
            "worktree_change_count": self.worktree_change_count,
            "worktree_error": self.worktree_error,
            "incomplete_inputs": list(self.incomplete_inputs),
            "failed_validations": list(self.failed_validations),
            "validation_report_status": self.validation_report_status,
            "reference_status": self.reference_status,
            "drift_fields": list(self.drift_fields),
            "build_baseline_verified": self.build_baseline_verified,
            "product_dispatch_state": self.product_dispatch_state,
            "readiness": self.readiness.model_dump(mode="json") if self.readiness else None,
            "policy_installed": self.policy_installed,
            "dispatch_attempted": self.dispatch_attempted,
            "read_only": self.read_only,
        }


def default_release_candidate_inputs(
    *,
    wheel_path: Path | str | None = None,
    runtime_pack_path: Path | str | None = None,
    container_image_digests: Mapping[str, str] | None = None,
    migration_revision: str | None = None,
    frontend_dist_path: Path | str | None = None,
    lockfile_paths: Sequence[Path | str] | None = None,
) -> BuildInputs:
    """Describe the repository-relative inputs of a candidate build.

    Artifacts produced outside the source tree stay unset unless the operator
    names them, so an unbuilt or unreviewed input can only remain pending.
    """

    return BuildInputs(
        source_paths=DEFAULT_SOURCE_PATHS,
        documentation_paths=DEFAULT_DOCUMENTATION_PATHS,
        frontend_dist_path=(
            DEFAULT_FRONTEND_DIST_PATH if frontend_dist_path is None else frontend_dist_path
        ),
        wheel_path=wheel_path,
        lockfile_paths=DEFAULT_LOCKFILE_PATHS if lockfile_paths is None else tuple(lockfile_paths),
        runtime_pack_path=runtime_pack_path,
        container_image_digests=dict(container_image_digests or {}),
        migration_revision=(
            declared_migration_revision() if migration_revision is None else migration_revision
        ),
    )


def declared_migration_revision() -> str:
    """Report the storage revision this build declares, or empty when unknown."""

    try:
        from .storage import CURRENT_REVISION
    except ImportError:
        return ""
    return CURRENT_REVISION


def parse_image_digest_arguments(values: Sequence[str]) -> dict[str, str]:
    """Parse ``name=sha256:<64 hex>`` operator arguments without guessing."""

    digests: dict[str, str] = {}
    for value in values:
        name, _, digest = str(value).partition("=")
        digests[name.strip()] = digest.strip()
    return dict(sorted(digests.items()))


def load_validation_results(
    path: Path | str | None,
) -> tuple[ValidationResults, ValidationReportStatus]:
    """Load named validation outcomes; any defect keeps the results empty."""

    if path is None:
        return ValidationResults(), "absent"
    payload = _read_json_document(path)
    if not isinstance(payload, dict):
        return ValidationResults(), "unreadable"
    checks = payload.get("checks")
    evidence = payload.get("evidence_hashes", {})
    if not isinstance(checks, dict) or not checks or not isinstance(evidence, dict):
        return ValidationResults(), "unreadable"
    if not all(isinstance(name, str) and name.strip() for name in checks):
        return ValidationResults(), "unreadable"
    readiness: dict[str, ReadinessCheck] = {}
    raw_readiness = payload.get("readiness", {})
    if raw_readiness is not None and not isinstance(raw_readiness, dict):
        return ValidationResults(), "unreadable"
    try:
        for name, value in (raw_readiness or {}).items():
            if name not in READINESS_CHECK_IDS or not isinstance(value, dict):
                return ValidationResults(), "unreadable"
            readiness[name] = ReadinessCheck.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        return ValidationResults(), "unreadable"
    source_commit = payload.get("source_commit", "")
    build_manifest_hash = payload.get("build_manifest_hash", "")
    request_hash = payload.get("request_hash", "")
    image_digests = payload.get("image_digests", {})
    if not all(isinstance(item, str) for item in (source_commit, build_manifest_hash, request_hash)):
        return ValidationResults(), "unreadable"
    if source_commit and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        return ValidationResults(), "unreadable"
    if build_manifest_hash and not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", build_manifest_hash):
        return ValidationResults(), "unreadable"
    if request_hash and not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", request_hash):
        return ValidationResults(), "unreadable"
    if not isinstance(image_digests, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in image_digests.items()
    ):
        return ValidationResults(), "unreadable"
    if not all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in image_digests.values()):
        return ValidationResults(), "unreadable"
    return (
        ValidationResults(
            checks={name: result is True for name, result in checks.items()},
            evidence_hashes={
                name: value
                for name, value in evidence.items()
                if isinstance(name, str) and isinstance(value, str)
            },
            readiness=readiness,
            source_commit=source_commit,
            build_manifest_hash=build_manifest_hash,
            request_hash=request_hash,
            image_digests=image_digests,
        ),
        "loaded",
    )


def load_reference_manifest(
    path: Path | str | None,
) -> tuple[ReleaseBuildManifest | None, bool]:
    """Load a frozen manifest for drift comparison. Returns (manifest, readable)."""

    if path is None:
        return None, True
    payload = _read_json_document(path)
    if payload is None:
        return None, False
    try:
        return ReleaseBuildManifest.model_validate(payload), True
    except (TypeError, ValidationError):
        return None, False


def verify_release_candidate(
    repository: Path | str,
    inputs: BuildInputs,
    results: ValidationResults,
    *,
    reference: ReleaseBuildManifest | Mapping[str, object] | None = None,
    reference_readable: bool = True,
    validation_report_status: ValidationReportStatus = "absent",
    created_at: str | None = None,
    request_hash: str = "",
    readiness_mode: Literal["report_only", "enforced"] = "report_only",
) -> ReleaseCandidateReport:
    """Verify a release candidate without writing state or arming anything.

    The function only observes: it never installs a Formal Release Policy, never
    issues a grant, never performs provider I/O, and never modifies the
    inspected worktree.
    """

    from .outbound_gate import product_dispatch_state

    verifier = ReleaseBuildVerifier(repository)
    worktree = verifier.inspect_worktree()
    manifest = verifier.build_manifest(inputs, results, created_at=created_at)
    readiness = build_readiness_report(
        manifest, results, request_hash=request_hash, mode=readiness_mode, generated_at=created_at
    )
    drift = manifest_drift(reference, manifest) if reference is not None else ()
    if not reference_readable:
        reference_status: ReferenceStatus = "unreadable"
    elif reference is None:
        reference_status = "absent"
    elif drift:
        reference_status = "drifted"
    else:
        reference_status = "matching"
    return ReleaseCandidateReport(
        manifest_id=manifest.id,
        status=manifest.status,
        identity_hash=build_manifest_identity_hash(manifest),
        worktree_clean=manifest.worktree_clean,
        worktree_change_count=len(worktree.changes),
        worktree_error=worktree.error,
        incomplete_inputs=incomplete_manifest_inputs(manifest),
        failed_validations=tuple(
            sorted(name for name, result in results.checks.items() if result is not True)
        ),
        validation_report_status=validation_report_status,
        reference_status=reference_status,
        drift_fields=drift,
        build_baseline_verified=(
            manifest.status == "verified" and not drift and reference_readable
        ),
        product_dispatch_state=product_dispatch_state(),
        readiness=readiness,
    )


def _read_json_document(path: Path | str) -> object | None:
    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return None
        if candidate.stat().st_size > _MAX_INPUT_JSON_BYTES:
            return None
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _hash_entries(entries: Sequence[Mapping[str, str | int]]) -> str:
    if not entries:
        return ""
    ordered = sorted(entries, key=lambda entry: str(entry["path"]))
    return _sha256(canonical(ordered).encode("utf-8"))
