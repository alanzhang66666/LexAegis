"""B5: standby slot inside request-scoped formal release.

first_acceptance stays primary-only; a scope_kind=request policy may carry an
explicit standby triple only when the frozen request itself binds a reviewed
standby profile.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from lexaegis.contracts import FormalReleasePolicy, FrozenFormalRequest, OneTimeDispatchGrant, ReleaseBuildManifest
from lexaegis.formal_release import (
    FIRST_RELEASE_TUPLE, FormalReleaseError, freeze_request, install_policy,
)
from lexaegis.gateway import create_gateway
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.storage import Store
from lexaegis.util import digest, sign

STANDBY_TARGET = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
STANDBY_MODEL = "qwen-plus"
PRIMARY_TARGET = "https://api.deepseek.com/v1/chat/completions"
PRIMARY_MODEL = "deepseek-chat"


def _hash(char):
    return "sha256:" + char * 64


def _manifest():
    return ReleaseBuildManifest(
        id="build-verified", source_commit="a" * 40, worktree_clean=True,
        source_tree_hash=_hash("a"), documentation_hash=_hash("b"),
        frontend_dist_hash=_hash("c"), wheel_hash=_hash("d"),
        lockfile_hashes={"requirements.lock": _hash("e")}, runtime_pack_hash=_hash("f"),
        container_image_digests={"api": _hash("a"), "worker": _hash("b"), "gateway": _hash("c")},
        migration_revision="0003_formal_release_uniques", validation_results_hash=_hash("d"),
        status="verified", created_at="2026-09-19T00:00:00Z", verified_by="release-ci",
    )


def _identities(manifest):
    identity_hash = build_manifest_identity_hash(manifest)
    return [{"process": name, "status": "verified", "runtime_identity_hash": identity_hash}
            for name in ("api", "worker", "gateway")]


PRIMARY = {"id": "deepseek-profile", "status": "reviewed",
           "endpoint": PRIMARY_TARGET, "model": PRIMARY_MODEL}
STANDBY = {"id": "qwen-profile", "status": "reviewed",
           "endpoint": STANDBY_TARGET, "model": STANDBY_MODEL}


def _request(standby=True, standby_status="reviewed"):
    standby_profile = {**STANDBY, "status": standby_status}
    dependencies = {
        "primary_provider_id": PRIMARY["id"], "primary_provider_hash": digest(PRIMARY),
        "provider_id": PRIMARY["id"], "provider_hash": digest(PRIMARY),
        "material_versions": {}, "pack_hash": None,  # filled by _task
        "mapping_version": 1, "ledger_version": 0,
        "combination_input_hash": "f" * 64,
        "risk_protocol_hashes": {"identity": "1" * 64},
        "dual_slot": {"primary": {"target": PRIMARY_TARGET, "model": PRIMARY_MODEL,
                                  "provider_id": PRIMARY["id"], "role": "primary"}},
        "runtime_profile": "production", "data_origin": "customer_material",
    }
    if standby:
        dependencies["standby_provider_id"] = standby_profile["id"]
        dependencies["standby_provider_hash"] = digest(standby_profile)
        dependencies["dual_slot"]["standby"] = {
            "target": STANDBY_TARGET, "model": STANDBY_MODEL,
            "provider_id": standby_profile["id"], "role": "standby"}
    return {
        "request_id": "request-standby-001", "case_id": "LA-777", "task_id": "task-s1",
        "mode": "formal", "transport": "cloud", "target": PRIMARY_TARGET,
        "wire_payload": {"contract_version": 2, "task": {"id": "fact_summary", "version": "2.0"},
                        "facts": [{"id": "fact-1", "text": "合成事实"}]},
        "body": {"model": PRIMARY_MODEL, "messages": [{"role": "system", "content": "只摘要给定事实"}]},
        "dependencies": dependencies,
        "policy": {"approved_for_dispatch": True, "demo_exception": False, "risk_completion": "complete"},
    }


def _task(repo, scope_kind="request", standby=True, standby_status="reviewed"):
    scope = {"case_id": "LA-777", "purpose": "R_fact_summary", "recipient": PRIMARY["id"]}
    pack = {"id": "rules-req", "status": "published", "schema_version": 2, "version": "1",
            "scope_kind": scope_kind,
            "published_scope": scope if scope_kind == "request" else FIRST_RELEASE_TUPLE}
    repo.put("pack", pack)
    repo.put("provider", dict(PRIMARY))
    request = _request(standby=standby, standby_status=standby_status)
    request["dependencies"]["pack_hash"] = digest(pack)
    if standby:
        profile = {**STANDBY, "status": standby_status}
        repo.put("provider", profile)
    task = {"id": "task-s1", "case_id": "LA-777", "type": "fact_summary", "status": "review",
            "transport": "cloud", "sub_purpose": "R_fact_summary", "version": 1,
            "mapping_version": 1, "pack_id": "rules-req", "request": request,
            "request_hash": digest(request)}
    case = {"id": "LA-777", "domain": "labor", "revision": 1,
            "runtime_profile": "production", "data_origin": "customer_material"}
    repo.put("case", case)
    repo.put("task", task, "LA-777")
    return task, case


@pytest.fixture
def repo(tmp_path):
    store = Store(tmp_path / "standby.sqlite")
    try:
        with store.transaction() as repository:
            yield repository
    finally:
        store.engine.dispose()


def test_request_scope_freeze_binds_reviewed_standby(repo):
    task, case = _task(repo)
    manifest = _manifest()
    frozen = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                            runtime_identities=_identities(manifest))
    assert frozen.standby_provider_id == STANDBY["id"]
    assert frozen.standby_target == STANDBY_TARGET
    assert frozen.standby_model == STANDBY_MODEL


def test_first_acceptance_pack_still_rejects_standby(repo):
    """A first-acceptance-scope pack keeps the primary-only rule even though
    standby review fields exist."""
    pack = {"id": "rules-fa", "status": "published", "schema_version": 2, "version": "1",
            "published_scope": FIRST_RELEASE_TUPLE}
    repo.put("pack", pack)
    repo.put("provider", dict(PRIMARY))
    request = _request(standby=True)
    request["case_id"] = "LA-001"
    request["target"] = PRIMARY_TARGET
    request["dependencies"]["pack_hash"] = digest(pack)
    task = {"id": "task-fa", "case_id": "LA-001", "type": "fact_summary", "status": "review",
            "transport": "cloud", "sub_purpose": "R_fact_summary", "version": 1,
            "mapping_version": 1, "pack_id": "rules-fa", "request": request,
            "request_hash": digest(request)}
    case = {"id": "LA-001", "domain": "labor", "revision": 1, "reference_code": "LA-001",
            "runtime_profile": "production", "data_origin": "customer_material"}
    repo.put("case", case)
    repo.put("provider", dict(STANDBY))
    repo.put("task", task, "LA-001")
    manifest = _manifest()
    with pytest.raises(FormalReleaseError, match="primary slot only"):
        freeze_request(repo, task=task, case=case, build_manifest=manifest,
                       runtime_identities=_identities(manifest))


def test_unreviewed_standby_profile_rejected(repo):
    task, case = _task(repo, standby_status="draft")
    manifest = _manifest()
    with pytest.raises(FormalReleaseError, match="standby provider profile is not reviewed"):
        freeze_request(repo, task=task, case=case, build_manifest=manifest,
                       runtime_identities=_identities(manifest))


def test_standby_hash_mismatch_rejected(repo):
    task, case = _task(repo)
    task["request"]["dependencies"]["standby_provider_hash"] = "0" * 64
    task["request_hash"] = digest(task["request"])
    repo.put("task", task, "LA-777")
    manifest = _manifest()
    with pytest.raises(FormalReleaseError, match="standby provider profile changed"):
        freeze_request(repo, task=task, case=case, build_manifest=manifest,
                       runtime_identities=_identities(manifest))


def test_policy_standby_fields_all_or_none():
    base = dict(id="p1", scope_kind="request", bound_request_hash="a" * 64,
                tuple={"case_id": "LA-777", "purpose": "R_fact_summary", "recipient": "deepseek-profile"},
                build_manifest_hash="a" * 64, allowed_target=PRIMARY_TARGET,
                allowed_model=PRIMARY_MODEL, allowed_provider_profile_hash="b" * 64,
                maximum_dispatches=1)
    with pytest.raises(ValueError):
        FormalReleasePolicy(**{**base, "allowed_standby_target": STANDBY_TARGET})
    ok = FormalReleasePolicy(**{**base,
                                "allowed_standby_target": STANDBY_TARGET,
                                "allowed_standby_model": STANDBY_MODEL,
                                "allowed_standby_provider_profile_hash": "c" * 64})
    assert ok.allowed_standby_model == STANDBY_MODEL


def test_first_acceptance_policy_rejects_standby_fields():
    with pytest.raises(ValueError, match="primary slot only"):
        FormalReleasePolicy(
            id="p2", scope_kind="first_acceptance", tuple=FIRST_RELEASE_TUPLE,
            build_manifest_hash="a" * 64, allowed_target=PRIMARY_TARGET,
            allowed_model=PRIMARY_MODEL, allowed_provider_profile_hash="b" * 64,
            allowed_standby_target=STANDBY_TARGET, allowed_standby_model=STANDBY_MODEL,
            allowed_standby_provider_profile_hash="c" * 64)


def _request_policy(repo, task, standby_fields=True):
    manifest = _manifest()
    fields = {}
    if standby_fields:
        fields = {"allowed_standby_target": STANDBY_TARGET,
                  "allowed_standby_model": STANDBY_MODEL,
                  "allowed_standby_provider_profile_hash": digest(STANDBY)}
    return FormalReleasePolicy(
        id="policy-s1", scope_kind="request", bound_request_hash=task["request_hash"],
        tuple={"case_id": "LA-777", "purpose": "R_fact_summary", "recipient": PRIMARY["id"]},
        build_manifest_hash=build_manifest_identity_hash(manifest),
        allowed_target=PRIMARY_TARGET, allowed_model=PRIMARY_MODEL,
        allowed_provider_profile_hash=digest(PRIMARY), maximum_dispatches=1, **fields)


def test_install_policy_standby_scope_must_match_frozen_slot(repo):
    task, case = _task(repo)
    install_policy(repo, _request_policy(repo, task), actor="admin-1", actor_role="admin")
    bad = _request_policy(repo, task).model_copy(
        update={"allowed_standby_target": "https://evil.example.com/v1"})
    with pytest.raises(FormalReleaseError, match="standby policy scope"):
        install_policy(repo, bad, actor="admin-1", actor_role="admin")


def test_policy_without_standby_rejects_request_carrying_standby(repo):
    task, case = _task(repo)
    with pytest.raises(FormalReleaseError, match="does not authorize"):
        install_policy(repo, _request_policy(repo, task, standby_fields=False),
                       actor="admin-1", actor_role="admin")


SECRET = "gateway-standby-test-secret-with-32-chars"


class _Outcome:
    status = "complete"
    result = {"claims": [], "unused_fact_ids": [], "gaps": []}

    def ledger_fields(self):
        return {"selected_slot": "primary", "attempts": [], "authorized_recipients": []}


class _Provider:
    primary_key = "test-primary-key"
    standby_key = "test-standby-key"
    def __init__(self):
        self.calls = 0
        self.slots = []
    def dispatch(self, target, body, dual_slot=None, persist_attempt=None):
        self.calls += 1
        self.slots.append(dual_slot)
        return _Outcome()


def _gateway_bundle(request, manifest, standby=True):
    now = datetime.now(timezone.utc)
    build_hash = build_manifest_identity_hash(manifest)
    request_hash = digest(request)
    frozen = FrozenFormalRequest(
        request_id=request["request_id"],
        tuple={"case_id": "LA-777", "purpose": "R_fact_summary", "recipient": PRIMARY["id"]},
        wire_payload=request["wire_payload"], prompt="只摘要给定事实",
        target=request["target"], model=PRIMARY_MODEL,
        provider_profile_hash=digest(PRIMARY),
        standby_provider_id=STANDBY["id"] if standby else None,
        standby_target=STANDBY_TARGET if standby else None,
        standby_model=STANDBY_MODEL if standby else None,
        standby_provider_profile_hash=digest(STANDBY) if standby else None,
        runtime_pack_hash=_hash("f"), material_versions={"doc-1": 1},
        rule_versions={"rules": _hash("e")}, task_version=1, mapping_version=1, ledger_version=0,
        combination_input_hash=_hash("1"), attack_protocol_hashes={"identity": _hash("2")},
        build_manifest_hash=build_hash, request_hash=request_hash, created_at=now.isoformat(),
    )
    policy = FormalReleasePolicy(
        id="policy-standby", scope_kind="request", bound_request_hash=request_hash,
        tuple=frozen.tuple, build_manifest_hash=build_hash,
        allowed_target=PRIMARY_TARGET, allowed_model=PRIMARY_MODEL,
        allowed_provider_profile_hash=digest(PRIMARY),
        allowed_standby_target=STANDBY_TARGET if standby else "",
        allowed_standby_model=STANDBY_MODEL if standby else "",
        allowed_standby_provider_profile_hash=digest(STANDBY) if standby else "",
        maximum_dispatches=1, status="armed_once",
        valid_from=(now - timedelta(minutes=1)).isoformat(),
        valid_until=(now + timedelta(minutes=30)).isoformat(),
        installed_by="admin-1", installed_at=now.isoformat())
    grant = OneTimeDispatchGrant(
        id="grant-standby", nonce="nonce-standby", request_hash=request_hash,
        gate_snapshot_hash=_hash("3"), evidence_manifest_hash=_hash("4"),
        build_manifest_hash=build_hash, release_policy_id=policy.id,
        tuple=frozen.tuple, actor="approver-1", actor_role="approver",
        issued_at=now.isoformat(), expires_at=(now + timedelta(minutes=20)).isoformat(),
        state="issued")
    return {"version": 1, "frozen_request": frozen.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"), "grant": grant.model_dump(mode="json"),
            "projection": {"request_hash": request_hash, "target": PRIMARY_TARGET,
                           "model": PRIMARY_MODEL, "provider_profile_hash": digest(PRIMARY)}}


def _envelope(request, bundle):
    approval = {"actor": "approver-1", "actor_role": "approver", "request_hash": digest(request),
                "dependencies": request["dependencies"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    content = {"request": request, "approval": approval, "formal_release": bundle}
    return {**content, "signature": sign(content, SECRET)}


def test_gateway_accepts_standby_when_request_policy_authorizes(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider()
    manifest = _manifest()
    app = create_gateway(tmp_path / "gateway-standby", secret=SECRET, provider=provider,
                         build_manifest=manifest)
    request = _request(standby=True)
    request["dependencies"]["pack_hash"] = "x" * 64
    envelope = _envelope(request, _gateway_bundle(request, manifest, standby=True))
    with TestClient(app) as client:
        response = client.post("/dispatch", json=envelope)
    assert response.status_code == 200, response.text
    assert provider.calls == 1
    assert provider.slots[0]["standby"]["target"] == STANDBY_TARGET


def test_gateway_rejects_standby_without_policy_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider()
    manifest = _manifest()
    app = create_gateway(tmp_path / "gateway-no-standby", secret=SECRET, provider=provider,
                         build_manifest=manifest)
    request = _request(standby=True)
    envelope = _envelope(request, _gateway_bundle(request, manifest, standby=False))
    with TestClient(app) as client:
        response = client.post("/dispatch", json=envelope)
    assert response.status_code == 403
    assert provider.calls == 0


def test_gateway_rejects_standby_target_outside_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider()
    manifest = _manifest()
    app = create_gateway(tmp_path / "gateway-evil-standby", secret=SECRET, provider=provider,
                         build_manifest=manifest)
    request = _request(standby=True)
    request["dependencies"]["dual_slot"]["standby"]["target"] = "https://evil.example.com/v1/chat/completions"
    request["dependencies"]["dual_slot"]["standby"]["model"] = "evil"
    envelope = _envelope(request, _gateway_bundle(request, manifest, standby=True))
    with TestClient(app) as client:
        response = client.post("/dispatch", json=envelope)
    assert response.status_code == 403
    assert provider.calls == 0
