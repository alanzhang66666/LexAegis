import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from lexaegis.cli import main as cli_main
from lexaegis.outbound_gate import product_dispatch_state
from lexaegis.release_build import (
    BuildInputs,
    ReleaseBuildVerifier,
    ValidationResults,
    build_manifest_identity_hash,
    manifest_drift,
)


IMAGE_DIGEST = "sha256:" + "a" * 64


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(repository: Path, relative_path: str, content: str) -> Path:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _release_repository(tmp_path: Path) -> tuple[Path, BuildInputs]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    _git(repository, "config", "user.name", "Release Test")

    _write(repository, "lexaegis/module.py", "VALUE = 1\n")
    _write(repository, "docs/README.md", "# Release documentation\n")
    _write(repository, "frontend/dist/index.html", "<main>release</main>\n")
    _write(repository, "dist/lexaegis-1.0.0-py3-none-any.whl", "synthetic-wheel\n")
    _write(repository, "requirements.lock", "pytest==9.1.1\n")
    _write(repository, "frontend/pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(repository, "runtime/runtime-pack.json", '{"status":"reviewed"}\n')

    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", "release fixture")

    inputs = BuildInputs(
        source_paths=("lexaegis",),
        documentation_paths=("docs",),
        frontend_dist_path="frontend/dist",
        wheel_path="dist/lexaegis-1.0.0-py3-none-any.whl",
        lockfile_paths=("requirements.lock", "frontend/pnpm-lock.yaml"),
        runtime_pack_path="runtime/runtime-pack.json",
        container_image_digests={"api": IMAGE_DIGEST, "gateway": IMAGE_DIGEST},
        migration_revision="0003_formal_release_uniques",
    )
    return repository, inputs


def _passed_validations() -> ValidationResults:
    return ValidationResults(
        checks={"pytest": True, "frontend_build": True},
        evidence_hashes={"pytest": "sha256:" + "b" * 64},
    )


def test_clean_complete_build_collects_all_provenance_and_is_verified(tmp_path):
    repository, inputs = _release_repository(tmp_path)
    verifier = ReleaseBuildVerifier(repository)

    manifest = verifier.build_manifest(
        inputs,
        _passed_validations(),
        created_at="2026-09-14T00:00:00Z",
        verified_by="release-automation",
    )

    assert manifest.status == "verified"
    assert manifest.worktree_clean is True
    assert manifest.source_commit == _git(repository, "rev-parse", "HEAD")
    assert manifest.source_tree_hash.startswith("sha256:")
    assert manifest.documentation_hash.startswith("sha256:")
    assert manifest.frontend_dist_hash.startswith("sha256:")
    assert manifest.wheel_hash.startswith("sha256:")
    assert manifest.runtime_pack_hash.startswith("sha256:")
    assert manifest.validation_results_hash.startswith("sha256:")
    assert set(manifest.lockfile_hashes) == {"requirements.lock", "frontend/pnpm-lock.yaml"}
    assert manifest.container_image_digests == {"api": IMAGE_DIGEST, "gateway": IMAGE_DIGEST}
    assert manifest.migration_revision == "0003_formal_release_uniques"
    assert manifest.verified_by == "release-automation"


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_dirty_tree_can_only_create_pending_manifest(tmp_path, dirty_kind):
    repository, inputs = _release_repository(tmp_path)
    if dirty_kind == "tracked":
        _write(repository, "lexaegis/module.py", "VALUE = 2\n")
    else:
        _write(repository, "lexaegis/new_module.py", "NEW = True\n")

    manifest = ReleaseBuildVerifier(repository).build_manifest(
        inputs,
        _passed_validations(),
        verified_by="must-not-survive",
    )

    assert manifest.worktree_clean is False
    assert manifest.status == "pending"
    assert manifest.verified_by is None


def test_incomplete_artifacts_or_failed_validation_remain_pending(tmp_path):
    repository, inputs = _release_repository(tmp_path)
    missing_runtime_pack = BuildInputs(
        source_paths=inputs.source_paths,
        documentation_paths=inputs.documentation_paths,
        frontend_dist_path=inputs.frontend_dist_path,
        wheel_path=inputs.wheel_path,
        lockfile_paths=inputs.lockfile_paths,
        runtime_pack_path="runtime/missing.json",
        container_image_digests=inputs.container_image_digests,
        migration_revision=inputs.migration_revision,
    )

    missing_manifest = ReleaseBuildVerifier(repository).build_manifest(
        missing_runtime_pack,
        _passed_validations(),
    )
    failed_manifest = ReleaseBuildVerifier(repository).build_manifest(
        inputs,
        ValidationResults(checks={"pytest": True, "frontend_build": False}),
    )

    assert missing_manifest.worktree_clean is True
    assert missing_manifest.runtime_pack_hash == ""
    assert missing_manifest.status == "pending"
    assert failed_manifest.worktree_clean is True
    assert failed_manifest.validation_results_hash.startswith("sha256:")
    assert failed_manifest.status == "pending"


def test_artifact_hashes_are_deterministic_for_identical_inputs(tmp_path):
    repository, inputs = _release_repository(tmp_path)
    verifier = ReleaseBuildVerifier(repository)

    first = verifier.build_manifest(inputs, _passed_validations())
    second = verifier.build_manifest(inputs, _passed_validations())

    assert first.id == second.id
    assert first.source_tree_hash == second.source_tree_hash
    assert first.documentation_hash == second.documentation_hash
    assert first.frontend_dist_hash == second.frontend_dist_hash
    assert first.validation_results_hash == second.validation_results_hash


# --- Task 4.3: worktree/artifact drift and read-only release-candidate verification ---

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FILE_DRIFT_CASES = {
    "source": ("lexaegis/module.py", "VALUE = 2\n", "source_tree_hash"),
    "documentation": ("docs/README.md", "# Release documentation drifted\n", "documentation_hash"),
    "frontend_dist": ("frontend/dist/index.html", "<main>drifted</main>\n", "frontend_dist_hash"),
    "wheel": ("dist/lexaegis-1.0.0-py3-none-any.whl", "drifted-wheel\n", "wheel_hash"),
    "runtime_pack": ("runtime/runtime-pack.json", '{"status":"reviewed","rev":2}\n', "runtime_pack_hash"),
    "lockfile": ("requirements.lock", "pytest==9.1.2\n", "lockfile_hashes"),
}


def _commit_all(repository: Path, message: str) -> None:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", message)


def _tree_snapshot(repository: Path) -> dict[str, str]:
    """Snapshot working files only; Git may refresh its own index during status."""

    snapshot: dict[str, str] = {}
    for path in sorted(repository.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(repository).parts:
            snapshot[path.relative_to(repository).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return snapshot


def _run_cli(monkeypatch, capsys, *arguments: str) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["lexaegis", "release", "verify-candidate", *arguments])
    with pytest.raises(SystemExit) as exit_info:
        cli_main()
    stdout = capsys.readouterr().out
    report, _end = json.JSONDecoder().raw_decode(stdout.lstrip())
    return int(exit_info.value.code), report


def _validation_report(tmp_path: Path) -> Path:
    path = tmp_path / "validation-results.json"
    path.write_text(
        json.dumps(
            {
                "checks": {"pytest": True, "frontend_build": True},
                "evidence_hashes": {"pytest": "sha256:" + "b" * 64},
            }
        ),
        encoding="utf-8",
    )
    return path


def _verified_cli_arguments(repository: Path, tmp_path: Path) -> list[str]:
    return [
        "--repository",
        str(repository),
        "--wheel",
        str(repository / "dist/lexaegis-1.0.0-py3-none-any.whl"),
        "--runtime-pack",
        str(repository / "runtime/runtime-pack.json"),
        "--image",
        f"api={IMAGE_DIGEST}",
        "--image",
        f"gateway={IMAGE_DIGEST}",
        "--migration-revision",
        "0003_formal_release_uniques",
        "--validation-report",
        str(_validation_report(tmp_path)),
    ]


@pytest.mark.parametrize("drift_kind", sorted(FILE_DRIFT_CASES))
def test_committed_artifact_drift_changes_manifest_identity(tmp_path, drift_kind):
    repository, inputs = _release_repository(tmp_path)
    verifier = ReleaseBuildVerifier(repository)
    baseline = verifier.build_manifest(inputs, _passed_validations())
    relative_path, content, expected_field = FILE_DRIFT_CASES[drift_kind]

    _write(repository, relative_path, content)
    _commit_all(repository, f"drift {drift_kind}")
    drifted = ReleaseBuildVerifier(repository).build_manifest(inputs, _passed_validations())

    assert baseline.status == "verified"
    assert drifted.status == "verified"
    assert expected_field in manifest_drift(baseline, drifted)
    assert "source_commit" in manifest_drift(baseline, drifted)
    assert build_manifest_identity_hash(drifted) != build_manifest_identity_hash(baseline)
    assert drifted.id != baseline.id


@pytest.mark.parametrize("drift_kind", sorted(FILE_DRIFT_CASES))
def test_uncommitted_artifact_drift_can_only_stay_pending(tmp_path, drift_kind):
    repository, inputs = _release_repository(tmp_path)
    baseline = ReleaseBuildVerifier(repository).build_manifest(inputs, _passed_validations())
    relative_path, content, expected_field = FILE_DRIFT_CASES[drift_kind]

    _write(repository, relative_path, content)
    drifted = ReleaseBuildVerifier(repository).build_manifest(inputs, _passed_validations())

    assert drifted.status == "pending"
    assert drifted.worktree_clean is False
    assert expected_field in manifest_drift(baseline, drifted)
    assert build_manifest_identity_hash(drifted) != build_manifest_identity_hash(baseline)


def test_declared_input_drift_changes_manifest_identity(tmp_path):
    repository, inputs = _release_repository(tmp_path)
    verifier = ReleaseBuildVerifier(repository)
    baseline = verifier.build_manifest(inputs, _passed_validations())
    other_digest = "sha256:" + "c" * 64
    mutations = {
        "container_image_digests": (
            replace(
                inputs,
                container_image_digests={"api": IMAGE_DIGEST, "gateway": other_digest},
            ),
            _passed_validations(),
        ),
        "migration_revision": (
            replace(inputs, migration_revision="0004_later_revision"),
            _passed_validations(),
        ),
        "validation_results_hash": (
            inputs,
            ValidationResults(
                checks={"pytest": True, "frontend_build": True},
                evidence_hashes={"pytest": "sha256:" + "d" * 64},
            ),
        ),
    }

    for expected_field, (drifted_inputs, drifted_results) in mutations.items():
        drifted = verifier.build_manifest(drifted_inputs, drifted_results)
        assert drifted.status == "verified", expected_field
        assert manifest_drift(baseline, drifted) == (expected_field,)
        assert build_manifest_identity_hash(drifted) != build_manifest_identity_hash(baseline)


def test_release_candidate_command_reports_verified_baseline_for_clean_complete_build(
    tmp_path, monkeypatch, capsys
):
    repository, _inputs = _release_repository(tmp_path)

    code, report = _run_cli(monkeypatch, capsys, *_verified_cli_arguments(repository, tmp_path))

    assert code == 0
    assert report["status"] == "verified"
    assert report["build_baseline_verified"] is True
    assert report["incomplete_inputs"] == []
    assert report["failed_validations"] == []
    assert report["validation_report_status"] == "loaded"
    assert report["reference_status"] == "absent"
    assert report["product_dispatch_state"] == "blocked"
    assert report["policy_installed"] is False
    assert report["dispatch_attempted"] is False


def test_release_candidate_command_reports_drift_against_frozen_reference(
    tmp_path, monkeypatch, capsys
):
    repository, inputs = _release_repository(tmp_path)
    arguments = _verified_cli_arguments(repository, tmp_path)
    code, verified = _run_cli(monkeypatch, capsys, *arguments)
    frozen = ReleaseBuildVerifier(repository).build_manifest(inputs, _passed_validations())
    reference = tmp_path / "reference-manifest.json"
    reference.write_text(json.dumps(frozen.model_dump()), encoding="utf-8")

    _write(repository, "docs/README.md", "# documentation drifted after freeze\n")
    _commit_all(repository, "documentation drift")
    drift_code, drift_report = _run_cli(
        monkeypatch, capsys, *arguments, "--reference", str(reference)
    )

    assert code == 0 and verified["build_baseline_verified"] is True
    assert verified["identity_hash"] == build_manifest_identity_hash(frozen)
    assert drift_code == 1
    assert drift_report["status"] == "verified"
    assert drift_report["reference_status"] == "drifted"
    assert set(drift_report["drift_fields"]) >= {"documentation_hash", "source_commit"}
    assert drift_report["build_baseline_verified"] is False
    assert drift_report["product_dispatch_state"] == "blocked"


def test_release_candidate_command_on_dirty_tree_is_pending_and_does_not_arm_product(
    tmp_path, monkeypatch, capsys
):
    repository, _inputs = _release_repository(tmp_path)
    _write(repository, "lexaegis/uncommitted.py", "DRIFT = True\n")
    before = _tree_snapshot(repository)
    before_head = _git(repository, "rev-parse", "HEAD")

    code, report = _run_cli(monkeypatch, capsys, *_verified_cli_arguments(repository, tmp_path))

    assert code == 1
    assert report["status"] == "pending"
    assert report["worktree_clean"] is False
    assert report["worktree_change_count"] >= 1
    assert report["build_baseline_verified"] is False
    assert report["product_dispatch_state"] == "blocked"
    assert product_dispatch_state() == "blocked"
    assert report["policy_installed"] is False
    assert report["dispatch_attempted"] is False
    assert _tree_snapshot(repository) == before
    assert _git(repository, "rev-parse", "HEAD") == before_head
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all")


def test_release_candidate_report_excludes_secrets_case_text_mapping_and_requests(
    tmp_path, monkeypatch, capsys
):
    repository, _inputs = _release_repository(tmp_path)
    markers = (
        "gateway-secret-key-marker",
        "案件正文原文标记",
        "mapping-original-value-marker",
        "full-frozen-request-marker",
    )
    _write(repository, "lexaegis/settings.py", f'GATEWAY_SECRET = "{markers[0]}"\n')
    _write(repository, "docs/case-notes.md", f"# {markers[1]}\n")
    _write(repository, "lexaegis/mapping.json", json.dumps({"当事人A": markers[2]}))
    _write(repository, "docs/frozen-request.json", json.dumps({"wire": markers[3]}))

    _code, report = _run_cli(monkeypatch, capsys, "--repository", str(repository))
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "pending"
    assert all(marker not in serialized for marker in markers)
    assert repository.as_posix() not in serialized
    assert str(repository) not in serialized
    assert "settings.py" not in serialized and "mapping.json" not in serialized


def test_release_candidate_command_leaves_this_repository_unchanged_and_pending(
    monkeypatch, capsys
):
    before_head = _git(REPOSITORY_ROOT, "rev-parse", "HEAD")
    before_status = _git(
        REPOSITORY_ROOT, "status", "--porcelain=v1", "--untracked-files=all"
    ).splitlines()

    code, report = _run_cli(monkeypatch, capsys, "--repository", str(REPOSITORY_ROOT))
    after_status = _git(
        REPOSITORY_ROOT, "status", "--porcelain=v1", "--untracked-files=all"
    ).splitlines()

    assert code == 1
    assert report["status"] == "pending"
    assert report["build_baseline_verified"] is False
    assert report["validation_report_status"] == "absent"
    assert {"wheel_hash", "runtime_pack_hash", "container_image_digests"} <= set(
        report["incomplete_inputs"]
    )
    assert report["product_dispatch_state"] == "blocked"
    assert _git(REPOSITORY_ROOT, "rev-parse", "HEAD") == before_head
    assert set(before_status) <= set(after_status)
