from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from lexaegis.contracts import READINESS_CHECK_IDS, ReadinessCheck, ReadinessReport, ReleaseBuildManifest
from lexaegis.release_build import ValidationResults, build_manifest_identity_hash, build_readiness_report, load_validation_results


def _manifest() -> ReleaseBuildManifest:
    return ReleaseBuildManifest(
        id="build-readiness",
        source_commit="a" * 40,
        worktree_clean=True,
        source_tree_hash="sha256:" + "1" * 64,
        documentation_hash="sha256:" + "2" * 64,
        frontend_dist_hash="sha256:" + "3" * 64,
        wheel_hash="sha256:" + "4" * 64,
        lockfile_hashes={"requirements.lock": "sha256:" + "5" * 64},
        runtime_pack_hash="sha256:" + "6" * 64,
        container_image_digests={"api": "sha256:" + "7" * 64},
        migration_revision="0001",
        validation_results_hash="sha256:" + "8" * 64,
        status="verified",
        created_at="2026-09-30T00:00:00Z",
    )


def _check(status="pass", *, valid_until=None):
    return ReadinessCheck(
        status=status,
        artifact_ids=["artifact-1"] if status == "pass" else [],
        source_kind="command_generated",
        source_command="synthetic command",
        environment={"synthetic_only": "true"},
        generated_at="2026-09-30T00:00:00Z",
        valid_until=valid_until,
        redaction_profile="synthetic-v1",
        reason="synthetic",
    )


def test_report_requires_exact_five_checks_and_rejects_extra_fields():
    checks = {name: _check("pending") for name in READINESS_CHECK_IDS}
    with pytest.raises(ValidationError):
        ReadinessReport(mode="report_only", state="blocked", source_commit="bad", checks=checks,
                        generated_at="now")
    with pytest.raises(ValidationError):
        ReadinessCheck.model_validate({**_check().model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        ReadinessReport(mode="report_only", state="blocked", source_commit="a" * 40,
                        build_manifest_hash="sha256:" + "b" * 64, request_hash="sha256:" + "c" * 64,
                        checks={name: _check("pending") for name in READINESS_CHECK_IDS},
                        generated_at="now", extra=True)


def test_readiness_rejects_expired_evidence_and_bad_bindings():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    checks = {name: _check("pending") for name in READINESS_CHECK_IDS}
    checks.update({"compose_isolation": _check("pass", valid_until=past),
                   "host_firewall": _check("pass"), "supply_chain": _check("pass")})
    report = build_readiness_report(_manifest(), ValidationResults(readiness=checks))
    assert report.state == "blocked"
    assert report.checks["compose_isolation"].status == "expired"
    bound = build_readiness_report(
        _manifest(), ValidationResults(readiness=checks, source_commit="f" * 40)
    )
    assert bound.state == "blocked"
    assert all(item.status == "fail" for item in bound.checks.values())


def test_readiness_eligibility_needs_build_compose_firewall_and_supply_chain():
    checks = {name: _check("pending") for name in READINESS_CHECK_IDS}
    checks.update({name: _check("pass") for name in ("compose_isolation", "host_firewall", "supply_chain")})
    report = build_readiness_report(_manifest(), ValidationResults(readiness=checks))
    assert report.state == "eligible"
    assert report.checks["k8s_conformance"].status == "pending"
    assert report.build_manifest_hash == build_manifest_identity_hash(_manifest())


def test_validation_report_rejects_malformed_hash_and_accepts_readiness(tmp_path):
    path = tmp_path / "validation.json"
    payload = {
        "checks": {"pytest": True},
        "evidence_hashes": {},
        "source_commit": "a" * 40,
        "build_manifest_hash": "sha256:" + "b" * 64,
        "readiness": {"compose_isolation": _check("pass").model_dump(mode="json")},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    results, status = load_validation_results(path)
    assert status == "loaded" and results.readiness["compose_isolation"].status == "pass"
    payload["source_commit"] = "not-a-commit"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, status = load_validation_results(path)
    assert status == "unreadable"
