from __future__ import annotations

import pytest

from lexaegis.contracts import FormalReleasePolicy, ReleaseBuildManifest, OneTimeDispatchGrant
from lexaegis.formal_release import (
    FIRST_RELEASE_TUPLE,
    FormalReleaseError,
    evaluate_release,
    freeze_request,
    gateway_claim,
    install_policy,
    _tuple_for_request,
)
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.storage import Store
from lexaegis.util import digest
from lexaegis import service


def _hash(char: str) -> str:
    return "sha256:" + char * 64


def _manifest():
    return ReleaseBuildManifest(
        id="build-verified",
        source_commit="a" * 40,
        worktree_clean=True,
        source_tree_hash=_hash("a"),
        documentation_hash=_hash("b"),
        frontend_dist_hash=_hash("c"),
        wheel_hash=_hash("d"),
        lockfile_hashes={"requirements.lock": _hash("e")},
        runtime_pack_hash=_hash("f"),
        container_image_digests={"api": _hash("a"), "worker": _hash("b"), "gateway": _hash("c")},
        migration_revision="0003_formal_release_uniques",
        validation_results_hash=_hash("d"),
        status="verified",
        created_at="2026-09-19T00:00:00Z",
        verified_by="release-ci",
    )


def _identities(manifest):
    identity_hash = build_manifest_identity_hash(manifest)
    return [
        {"process": name, "status": "verified", "runtime_identity_hash": identity_hash}
        for name in ("api", "worker", "gateway")
    ]


def _task(repo):
    pack = {"id": "rules-v1", "status": "published", "schema_version": 2, "version": "1",
            "published_scope": FIRST_RELEASE_TUPLE}
    repo.put("pack", pack)
    profile = {
        "id": "deepseek-profile",
        "status": "reviewed",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
    }
    repo.put("provider", profile)
    request = {
        "request_id": "request-001",
        "case_id": "LA-001",
        "task_id": "task-001",
        "mode": "formal",
        "transport": "cloud",
        "target": profile["endpoint"],
        "wire_payload": {"facts": [{"id": "fact-1", "text": "合成事实"}]},
        "body": {"model": profile["model"], "messages": [{"role": "system", "content": "只摘要给定事实"}]},
        "dependencies": {
            "primary_provider_id": profile["id"],
            "primary_provider_hash": digest(profile),
            "provider_id": profile["id"],
            "provider_hash": digest(profile),
            "material_versions": {},
            "pack_hash": digest(pack),
            "mapping_version": 1,
            "ledger_version": 0,
            "combination_input_hash": "f" * 64,
            "risk_protocol_hashes": {"identity": "1" * 64},
            "dual_slot": {"primary": {"target": profile["endpoint"], "model": profile["model"]}},
            "runtime_profile": "production",
            "data_origin": "customer_material",
        },
        "policy": {"approved_for_dispatch": True, "demo_exception": False, "risk_completion": "complete"},
    }
    task = {
        "id": "task-001",
        "case_id": "LA-001",
        "type": "fact_summary",
        "status": "review",
        "transport": "cloud",
        "sub_purpose": "R_fact_summary",
        "version": 1,
        "mapping_version": 1,
        "pack_id": "rules-v1",
        "request": request,
        "request_hash": digest(request),
    }
    case = {"id": "LA-001", "domain": "labor", "revision": 1,
            "runtime_profile": "production", "data_origin": "customer_material"}
    repo.put("case", case)
    repo.put("task", task, "LA-001")
    return task, case


@pytest.fixture
def repo(tmp_path):
    store = Store(tmp_path / "formal-release.sqlite")
    try:
        with store.transaction() as repository:
            yield repository
    finally:
        store.engine.dispose()


def test_policy_install_starts_blocked_and_rejects_wide_or_armed_scope(repo):
    policy = FormalReleasePolicy(
        id="policy-la001-once",
        tuple=FIRST_RELEASE_TUPLE,
        build_manifest_hash=_hash("a"),
        allowed_target="https://api.deepseek.com/v1/chat/completions",
        allowed_model="deepseek-chat",
        allowed_provider_profile_hash="b" * 64,
        maximum_dispatches=1,
    )
    installed = install_policy(repo, policy, actor="admin-1", actor_role="admin")
    assert installed.status == "blocked"
    assert installed.installed_by == "admin-1"

    armed = policy.model_copy(update={"status": "armed_once"})
    with pytest.raises(FormalReleaseError, match="start blocked"):
        install_policy(repo, armed, actor="admin-2", actor_role="admin")


def test_freeze_binds_existing_approval_hash_and_verified_runtime_identities(repo):
    manifest = _manifest()
    task, case = _task(repo)
    frozen = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                            runtime_identities=_identities(manifest))
    assert frozen.request_hash == task["request_hash"]
    assert frozen.target == task["request"]["target"]
    assert frozen.model == task["request"]["body"]["model"]
    assert frozen.build_manifest_hash == build_manifest_identity_hash(manifest)


def test_freeze_accepts_real_create_task_general_subpurpose(tmp_path, monkeypatch):
    """The registered task type defines R scope; UI sub-purpose is explanatory text."""
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    # Use an isolated initialized store so this follows the real create_case,
    # fact, and create_task code paths rather than a hand-written task fixture.
    store = Store(tmp_path / "create-task-purpose.sqlite")
    manifest = _manifest()
    try:
        service.initialize(store)
        with store.transaction() as live:
            pack = {
                "id": "rules-real-create", "domain_id": "labor", "schema_version": 2,
                "version": "1", "status": "published", "task_ids": ["fact_summary"],
                "fact_fields": ["event"], "rules": [], "task_field_matrix": [],
                "published_scope": FIRST_RELEASE_TUPLE, "dispatch_allowed": True,
                "legal_status": "reviewed",
            }
            live.put("pack", pack)
            profile = {"id": "deepseek-profile", "status": "reviewed",
                       "endpoint": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"}
            live.put("provider", profile)
            settings = live.get("settings")
            provider_base = "https://api.deepseek.com/v1"
            settings.update(provider_id=profile["id"], cloud_url=provider_base, cloud_model=profile["model"],
                            cloud_primary={"provider_id": profile["id"], "url": provider_base, "model": profile["model"]})
            live.put("settings", settings)
            case = service.create_case(live, "创建任务路径测试", reference_code="LA-001")
            live.put("fact", {"id": "fact-real-create", "case_id": case["id"], "field": "event",
                               "value": "合成的劳动事实", "source_ids": ["block-real-create"],
                               "origin": "manual", "confirmed": True, "stale": False}, case["id"])
            task = service.create_task(live, case["id"], "cloud", "fact_summary", pack_id=pack["id"])
            assert task["type"] == "fact_summary"
            assert task["sub_purpose"] == "劳动争议文书事实保真整理"
            request = {
                "request_id": "request-real-create", "case_id": case["id"], "mode": "formal",
                "transport": "cloud", "target": profile["endpoint"],
                "wire_payload": {"facts": [{"id": "fact-real-create", "text": "合成的劳动事实"}]},
                "body": {"model": profile["model"], "messages": [{"role": "system", "content": "仅摘要已批准事实"}]},
                "dependencies": {
                    "primary_provider_id": profile["id"], "primary_provider_hash": digest(profile),
                    "material_versions": {}, "pack_hash": digest(pack), "mapping_version": 1,
                    "ledger_version": 0, "combination_input_hash": _hash("1"),
                    "risk_protocol_hashes": {"identity": _hash("2")},
                    "runtime_profile": "production", "data_origin": "customer_material",
                },
                "policy": {"approved_for_dispatch": True, "risk_completion": "complete"},
            }
            task.update(status="review", transport="cloud", request=request, request_hash=digest(request))
            live.put("task", task, case["id"])
            case.update(runtime_profile="production", data_origin="customer_material")
            live.put("case", case)
            frozen = freeze_request(live, task=task, case=case, build_manifest=manifest,
                                    runtime_identities=_identities(manifest))
            assert frozen.tuple == FIRST_RELEASE_TUPLE
    finally:
        store.engine.dispose()


def test_freeze_rejects_runtime_identity_drift(repo):
    manifest = _manifest()
    task, case = _task(repo)
    identities = _identities(manifest)
    identities[1]["runtime_identity_hash"] = _hash("9")
    with pytest.raises(FormalReleaseError, match="identities"):
        freeze_request(repo, task=task, case=case, build_manifest=manifest,
                       runtime_identities=identities)


def test_freeze_rejects_rule_scope_for_another_primary_recipient(repo):
    manifest = _manifest()
    task, case = _task(repo)
    case["domain"] = "labor"
    repo.put("case", case)
    pack = repo.get(task["pack_id"], "pack")
    pack["published_scope"] = {"domain": "labor", "purpose": "R_fact_summary", "recipient": "provider-A"}
    pack["scope_kind"] = "request"
    repo.put("pack", pack)
    runtime_pack = {"id": "runtime-pack-scope-mismatch", "status": "published", "scope_kind": "request",
                    "published_scope": dict(pack["published_scope"])}
    repo.put("runtime_pack", runtime_pack)
    repo.put("runtime_pack_activation", {"id": "activation-scope-mismatch", "pack_id": pack["id"],
                                          "runtime_pack_id": runtime_pack["id"],
                                          "artifact_sha256": manifest.runtime_pack_hash})
    task["request"]["dependencies"]["pack_hash"] = digest(pack)
    task["request_hash"] = digest(task["request"])
    repo.put("task", task, case["id"])
    candidate = FormalReleasePolicy(
        id="policy-scope-mismatch", scope_kind="request", bound_request_hash=task["request_hash"],
        tuple=_tuple_for_request(case, task, task["request"], include_pilot=False),
        build_manifest_hash=build_manifest_identity_hash(manifest), allowed_target=task["request"]["target"],
        allowed_model=task["request"]["body"]["model"],
        allowed_provider_profile_hash=task["request"]["dependencies"]["primary_provider_hash"],
    )
    install_policy(repo, candidate, actor="admin", actor_role="admin")
    task = repo.get(task["id"], "task")
    with pytest.raises(FormalReleaseError, match="published rule scope"):
        freeze_request(repo, task=task, case=case, build_manifest=manifest,
                       runtime_identities=_identities(manifest))


def test_release_evaluation_fails_closed_without_policy_and_signed_evidence(repo):
    manifest = _manifest()
    task, case = _task(repo)
    frozen = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                            runtime_identities=_identities(manifest))
    # Even the exact scope and verified build are insufficient without the
    # controlled evidence intake, current role actions, receipts, and isolation.
    decision = evaluate_release(repo, frozen=frozen, task=task, case=case,
                                build_manifest=manifest, runtime_identities=_identities(manifest),
                                evidence_intake=None)
    assert decision.approval_eligible is False
    assert decision.dispatch_allowed is False
    assert decision.system_readiness == "blocked"
    assert any(hit.reason_code == "formal_release_blocked" for hit in decision.hits)


def test_isolation_receipt_rejects_nonexistent_legal_confirmation(repo):
    manifest = _manifest()
    task, case = _task(repo)
    frozen = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                            runtime_identities=_identities(manifest))
    provider_hash = task["request"]["dependencies"]["primary_provider_hash"]
    policy = FormalReleasePolicy(
        id="policy-la001-once", tuple=FIRST_RELEASE_TUPLE,
        build_manifest_hash=frozen.build_manifest_hash, allowed_target=frozen.target,
        allowed_model=frozen.model, allowed_provider_profile_hash=provider_hash,
    )
    repo.put("formal_release_policy", policy.model_dump(mode="json"))
    repo.put("isolation_receipt", {
        "id": "isolation-1", "request_hash": frozen.request_hash,
        "tuple": FIRST_RELEASE_TUPLE,
        "build_manifest_hash": frozen.build_manifest_hash, "deployment_mode": "isolated",
        "deployment_identity_hash": _hash("1"), "compose_hash": _hash("2"),
        "image_digests": manifest.container_image_digests,
        "api_no_egress": True, "worker_no_egress": True, "gateway_no_case_volume": True,
        "redteam_no_secrets": True, "benchmark_no_secrets": True,
        "probe_output_hash": _hash("3"), "host_firewall_evidence_hash": _hash("4"),
        "supply_chain_evidence_hash": _hash("5"), "generated_at": "2026-09-19T00:00:00Z",
        "expires_at": "2026-09-20T00:00:00Z", "attested_by": "security-reviewer",
        "legal_confirmation_receipt_id": "receipt-does-not-exist", "status": "valid",
    }, "LA-001")

    class EmptyEvidenceIntake:
        def resolve_evidence(self, *args, **kwargs):
            return []

    decision = evaluate_release(
        repo, frozen=frozen, task=task, case=case, build_manifest=manifest,
        runtime_identities=_identities(manifest), evidence_intake=EmptyEvidenceIntake(),
        at="2026-09-19T00:01:00Z",
    )
    assert decision.approval_eligible is False
    assert any(hit.reason_code == "isolation_receipt_missing" for hit in decision.hits)


def test_policy_install_requires_named_admin_and_exact_provider_build_scope(repo):
    policy = FormalReleasePolicy(
        id="policy-la001-once",
        tuple=FIRST_RELEASE_TUPLE,
        build_manifest_hash=_hash("a"),
        allowed_target="https://api.deepseek.com/v1/chat/completions",
        allowed_model="deepseek-chat",
        allowed_provider_profile_hash="b" * 64,
    )
    with pytest.raises(FormalReleaseError, match="administrator"):
        install_policy(repo, policy, actor="operator", actor_role="case_operator")


def test_gateway_claim_is_durable_before_send_and_exact_replay_never_resends(repo):
    manifest = _manifest()
    task, case = _task(repo)
    frozen = freeze_request(repo, task=task, case=case, build_manifest=manifest,
                            runtime_identities=_identities(manifest))
    profile_hash = task["request"]["dependencies"]["primary_provider_hash"]
    policy = FormalReleasePolicy(
        id="policy-la001-once", tuple=FIRST_RELEASE_TUPLE,
        build_manifest_hash=frozen.build_manifest_hash,
        allowed_target=frozen.target, allowed_model=frozen.model,
        allowed_provider_profile_hash=profile_hash,
        status="armed_once", valid_from="2026-09-18T00:00:00Z",
        valid_until="2026-09-20T00:00:00Z", installed_by="admin-1",
        installed_at="2026-09-18T00:00:00Z",
    )
    repo.put("formal_release_policy", policy.model_dump(mode="json"))
    grant = OneTimeDispatchGrant(
        id="grant-1", nonce="one-use-nonce", request_hash=frozen.request_hash,
        gate_snapshot_hash=_hash("1"), evidence_manifest_hash=_hash("2"),
        build_manifest_hash=frozen.build_manifest_hash, release_policy_id=policy.id,
        tuple=FIRST_RELEASE_TUPLE, actor="approver-1", actor_role="approver",
        issued_at="2026-09-19T00:00:00Z", expires_at="2026-09-19T00:30:00Z", state="issued",
    )
    repo.put("one_time_dispatch_grant", grant.model_dump(mode="json"))
    approval = {"actor": "approver-1", "actor_role": "approver",
                "request_hash": frozen.request_hash, "expires_at": "2026-09-19T00:30:00Z"}
    projection = {"request_hash": frozen.request_hash, "target": frozen.target, "model": frozen.model}
    identity = _identities(manifest)[2]
    first = gateway_claim(repo, frozen=frozen, approval=approval, grant_id=grant.id,
                          gateway_request_id=frozen.request_id, projection=projection,
                          runtime_identity=identity, build_manifest=manifest,
                          at="2026-09-19T00:01:00Z")
    assert first["state"] == "claimed"
    assert first["replay"] is False

    replay = gateway_claim(repo, frozen=frozen, approval=approval, grant_id=grant.id,
                           gateway_request_id=frozen.request_id, projection=projection,
                           runtime_identity=identity, build_manifest=manifest,
                           at="2026-09-19T00:02:00Z")
    assert replay["id"] == first["id"]
    assert replay["state"] == "claimed"
    assert replay["replay"] is True

    with pytest.raises(FormalReleaseError, match="request ID differs"):
        gateway_claim(repo, frozen=frozen, approval=approval, grant_id=grant.id,
                      gateway_request_id="different-request-id", projection=projection,
                      runtime_identity=identity, build_manifest=manifest,
                      at="2026-09-19T00:03:00Z")


def test_request_policies_allow_second_request_but_never_cross_replay(repo):
    manifest = _manifest()
    first, case = _task(repo)
    pack = repo.get(first["pack_id"], "pack")
    pack["published_scope"] = {"domain": "labor", "purpose": "R_fact_summary",
                               "recipient":"deepseek-profile"}
    repo.put("pack", pack)
    runtime_pack = {"id": "runtime-pack-test", "status": "published", "scope_kind": "request",
                    "published_scope": dict(pack["published_scope"])}
    repo.put("runtime_pack", runtime_pack)
    repo.put("runtime_pack_activation", {
        "id": "activation-test", "pack_id": first["pack_id"],
        "runtime_pack_id": "runtime-pack-test", "artifact_sha256": manifest.runtime_pack_hash,
    })
    for task in (first,):
        task["request"]["dependencies"]["pack_hash"] = digest(pack)
        task["request_hash"] = digest(task["request"])
        repo.put("task", task, case["id"])
    repo.put("formal_release_policy", FormalReleasePolicy(
        id="legacy-first-acceptance-consumed", tuple=FIRST_RELEASE_TUPLE,
        build_manifest_hash=build_manifest_identity_hash(manifest), allowed_target=first["request"]["target"],
        allowed_model=first["request"]["body"]["model"],
        allowed_provider_profile_hash=first["request"]["dependencies"]["primary_provider_hash"],
        status="consumed", consumed_dispatches=1,
    ).model_dump(mode="json"))
    second = {**first, "id": "task-002", "request": {**first["request"]}}
    second["request"].update(request_id="request-002", task_id="task-002")
    second["request"]["body"] = {**second["request"]["body"], "messages": [
        {"role": "system", "content": "只摘要第二次请求给定事实"}
    ]}
    second["request_hash"] = digest(second["request"])
    repo.put("task", second, case["id"])

    other_case = {**case, "id": "CASE-002", "reference_code": "CASE-002"}
    repo.put("case", other_case)
    third = {**first, "id": "task-003", "case_id": other_case["id"], "request": {**first["request"]}}
    third["request"].update(request_id="request-003", task_id="task-003", case_id=other_case["id"])
    third["request_hash"] = digest(third["request"])
    repo.put("task", third, other_case["id"])
    def policy_for(task, scope_case, suffix):
        scope = _tuple_for_request(scope_case, task, task["request"], include_pilot=False)
        candidate = FormalReleasePolicy(
            id=f"request-policy-{suffix}", scope_kind="request",
            bound_request_hash=task["request_hash"], tuple=scope,
            build_manifest_hash=build_manifest_identity_hash(manifest),
            allowed_target=task["request"]["target"],
            allowed_model=task["request"]["body"]["model"],
            allowed_provider_profile_hash=task["request"]["dependencies"]["primary_provider_hash"],
        )
        return install_policy(repo, candidate, actor="admin", actor_role="admin")

    p1, p2, p3 = policy_for(first, case, "one"), policy_for(second, case, "two"), policy_for(third, other_case, "three")
    assert len({p1.id, p2.id, p3.id}) == 3
    f1 = freeze_request(repo, task=first, case=case, build_manifest=manifest,
                        runtime_identities=_identities(manifest))
    f2 = freeze_request(repo, task=second, case=case, build_manifest=manifest,
                        runtime_identities=_identities(manifest))
    f3 = freeze_request(repo, task=third, case=other_case, build_manifest=manifest,
                        runtime_identities=_identities(manifest))
    assert len({f1.request_hash, f2.request_hash, f3.request_hash}) == 3
    assert f1.tuple == f2.tuple == p1.tuple == p2.tuple
    assert f3.tuple == p3.tuple and f3.tuple["case_id"] == "CASE-002"

    def armed(policy):
        value = policy.model_copy(update={"status": "armed_once", "valid_from": "2026-09-18T00:00:00Z",
                                          "valid_until": "2026-09-20T00:00:00Z"})
        repo.put("formal_release_policy", value.model_dump(mode="json"))
        return value

    p1, p2, p3 = armed(p1), armed(p2), armed(p3)
    g1 = OneTimeDispatchGrant(
        id="grant-request-one", nonce="nonce-request-one", request_hash=f1.request_hash,
        gate_snapshot_hash=_hash("1"), evidence_manifest_hash=_hash("2"),
        build_manifest_hash=f1.build_manifest_hash, release_policy_id=p1.id, tuple=f1.tuple,
        actor="approver", actor_role="approver", issued_at="2026-09-19T00:00:00Z",
        expires_at="2026-09-19T00:30:00Z", state="issued",
    )
    g2 = g1.model_copy(update={"id": "grant-request-two", "nonce": "nonce-request-two",
                               "request_hash": f2.request_hash, "release_policy_id": p2.id})
    g3 = g1.model_copy(update={"id": "grant-request-three", "nonce": "nonce-request-three",
                               "request_hash": f3.request_hash, "release_policy_id": p3.id, "tuple": f3.tuple})
    repo.put("one_time_dispatch_grant", g1.model_dump(mode="json"))
    repo.put("one_time_dispatch_grant", g2.model_dump(mode="json"))
    repo.put("one_time_dispatch_grant", g3.model_dump(mode="json"))
    identity = _identities(manifest)[2]

    def claim(frozen, grant_id):
        approval = {"actor": "approver", "actor_role": "approver", "request_hash": frozen.request_hash,
                    "expires_at": "2026-09-19T00:30:00Z"}
        projection = {"request_hash": frozen.request_hash, "target": frozen.target, "model": frozen.model}
        return gateway_claim(repo, frozen=frozen, approval=approval, grant_id=grant_id,
                             gateway_request_id=frozen.request_id, projection=projection,
                             runtime_identity=identity, build_manifest=manifest,
                             at="2026-09-19T00:01:00Z")

    assert claim(f1, g1.id)["state"] == "claimed"
    assert claim(f2, g2.id)["state"] == "claimed"
    assert claim(f3, g3.id)["state"] == "claimed"
    with pytest.raises(FormalReleaseError, match="out of scope"):
        claim(f2, g1.id)
