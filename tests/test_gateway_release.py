from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from lexaegis.contracts import (
    FormalReleasePolicy,
    FrozenFormalRequest,
    OneTimeDispatchGrant,
    ReleaseBuildManifest,
)
from lexaegis.gateway import create_gateway
from lexaegis.release_build import build_manifest_identity_hash
from lexaegis.runtime_profile import synthetic_manifest_hash
from lexaegis.demo import SCENARIOS
from lexaegis.task_engine import request_system_prompt
from lexaegis.util import digest, sign


SECRET = "gateway-formal-test-secret-with-32-characters"
TARGET = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"
PROVIDER_HASH = "b" * 64


def _hash(char):
    return "sha256:" + char * 64


def _manifest():
    return ReleaseBuildManifest(
        id="manifest-test", source_commit="a" * 40, worktree_clean=True,
        source_tree_hash=_hash("a"), documentation_hash=_hash("b"),
        frontend_dist_hash=_hash("c"), wheel_hash=_hash("d"),
        lockfile_hashes={"requirements.lock": _hash("e")}, runtime_pack_hash=_hash("f"),
        container_image_digests={"api": _hash("a"), "worker": _hash("b"), "gateway": _hash("c")},
        migration_revision="0003_formal_release_uniques", validation_results_hash=_hash("d"),
        status="verified", created_at="2026-09-19T00:00:00Z", verified_by="test-ci",
    )


def _request(profile="production", mode="formal", transport="cloud"):
    if profile in {"demo", "integration"}:
        origin = "bundled_synthetic"
        manifest_hash = synthetic_manifest_hash("success")
        mode = "demo"
    else:
        origin = "customer_material"
        manifest_hash = None
    dependencies = {
        "runtime_profile": profile,
        "data_origin": origin,
        "synthetic_manifest_hash": manifest_hash,
        "primary_provider_id": "deepseek-profile",
        "primary_provider_hash": PROVIDER_HASH,
        "dual_slot": {"primary": {"target": TARGET, "model": MODEL}},
    }
    if profile in {"demo", "integration"}:
        seed = SCENARIOS["success"]
        mappings = {value: f"[[LEX:P{index:04d}]]" for index, (field, value) in
                    enumerate((row for row in seed["facts"] if row[0] == "entity"), start=1)}
        facts = [{"id": f"fact_{index:016x}", "field": field, "text": mappings.get(value, value)}
                 for index, (field, value) in enumerate(seed["facts"], start=1)]
        wire = {"contract_version": 2, "task": {"id": "fact_summary", "version": "2.0"}, "facts": facts}
        messages = [{"role": "system", "content": request_system_prompt("fact_summary")},
                    {"role": "user", "content": json.dumps(wire, ensure_ascii=False)}]
    else:
        wire = {"contract_version": 2, "task": "fact_summary", "facts": [{"id": "f1", "text": "合成测试事实"}]}
        messages = [{"role": "system", "content": "仅总结给定事实"}, {"role": "user", "content": "{}"}]
    return {
        "request_id": "request-formal-001",
        "case_id": "case-customer-001",
        "task_id": "task-001",
        "mode": mode,
        "transport": transport,
        "target": TARGET,
        "wire_payload": wire,
        "body": {"model": MODEL, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}},
        "dependencies": dependencies,
        "policy": {"approved_for_dispatch": True, "demo_exception": mode == "demo", "risk_completion": "complete"},
    }


def _bundle(request, manifest):
    now = datetime.now(timezone.utc)
    build_hash = build_manifest_identity_hash(manifest)
    request_hash = digest(request)
    frozen = FrozenFormalRequest(
        request_id=request["request_id"],
        tuple={"case_id": "LA-001", "purpose": "R_fact_summary", "recipient": "D_DeepSeek_official_API"},
        wire_payload=request["wire_payload"], prompt="仅总结给定事实", target=request["target"], model=MODEL,
        provider_profile_hash=PROVIDER_HASH, runtime_pack_hash=_hash("f"), material_versions={"doc-1": 1},
        rule_versions={"rules": _hash("e")}, task_version=1, mapping_version=1, ledger_version=0,
        combination_input_hash=_hash("1"), attack_protocol_hashes={"identity": _hash("2")},
        build_manifest_hash=build_hash, request_hash=request_hash, created_at=now.isoformat(),
    )
    policy = FormalReleasePolicy(
        id="policy-la001-once", tuple=frozen.tuple, build_manifest_hash=build_hash,
        allowed_target=TARGET, allowed_model=MODEL, allowed_provider_profile_hash=PROVIDER_HASH,
        maximum_dispatches=1, status="armed_once", valid_from=(now - timedelta(minutes=1)).isoformat(),
        valid_until=(now + timedelta(minutes=30)).isoformat(), installed_by="admin-1", installed_at=now.isoformat(),
    )
    grant = OneTimeDispatchGrant(
        id="grant-once", nonce="grant-nonce-once", request_hash=request_hash,
        gate_snapshot_hash=_hash("3"), evidence_manifest_hash=_hash("4"), build_manifest_hash=build_hash,
        release_policy_id=policy.id, tuple=frozen.tuple, actor="approver-1", actor_role="approver",
        issued_at=now.isoformat(), expires_at=(now + timedelta(minutes=20)).isoformat(), state="issued",
    )
    return {"version": 1, "frozen_request": frozen.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"), "grant": grant.model_dump(mode="json"),
            "projection": {"request_hash": request_hash, "target": TARGET, "model": MODEL,
                           "provider_profile_hash": PROVIDER_HASH}}


def _envelope(request, formal_release=None, include_bundle_in_signature=True):
    approval = {"actor": "approver-1", "actor_role": "approver", "request_hash": digest(request),
                "dependencies": request["dependencies"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    content = {"request": request, "approval": approval}
    if formal_release is not None and include_bundle_in_signature:
        content["formal_release"] = formal_release
    result = {**content, "signature": sign(content, SECRET)}
    if formal_release is not None:
        result["formal_release"] = formal_release
    return result


class _Outcome:
    status = "complete"
    result = {"claims": [], "unused_fact_ids": [], "gaps": []}

    def ledger_fields(self):
        return {"selected_slot": "primary", "attempts": [], "authorized_recipients": []}


class _Provider:
    primary_key = "test-primary-key"
    standby_key = "test-standby-key"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        self.slots = []

    def dispatch(self, target, body, dual_slot=None, persist_attempt=None):
        self.calls += 1
        self.slots.append(dual_slot)
        if self.fail:
            raise RuntimeError("simulated crash after claim")
        return _Outcome()


def test_production_cloud_requires_signed_formal_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider()
    app = create_gateway(tmp_path / "gateway-prod", secret=SECRET, provider=provider)
    request = _request()
    with TestClient(app) as client:
        response = client.post("/dispatch", json=_envelope(request))
    assert response.status_code == 403
    assert "one-time grant" in response.text
    assert provider.calls == 0


def test_formal_bundle_must_be_covered_by_hmac_signature(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    app = create_gateway(tmp_path / "gateway-sign", secret=SECRET, provider=_Provider(), build_manifest=_manifest())
    request = _request()
    bundle = _bundle(request, _manifest())
    with TestClient(app) as client:
        response = client.post("/dispatch", json=_envelope(request, bundle, include_bundle_in_signature=False))
    assert response.status_code == 403
    assert "signature" in response.text.lower()


def test_verified_production_grant_is_claimed_before_send_and_replay_never_calls_provider_twice(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider()
    manifest = _manifest()
    app = create_gateway(tmp_path / "gateway-success", secret=SECRET, provider=provider, build_manifest=manifest)
    request = _request()
    bundle = _bundle(request, manifest)
    envelope = _envelope(request, bundle)
    with TestClient(app) as client:
        first = client.post("/dispatch", json=envelope)
        second = client.post("/dispatch", json=envelope)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "complete"
    assert second.json() == first.json()
    assert provider.calls == 1
    assert provider.slots[0].get("standby") is None
    with app.state.store.read() as repo:
        assert repo.get("grant-once", "one_time_dispatch_grant")["state"] == "consumed"
        assert repo.get("policy-la001-once", "formal_release_policy")["consumed_dispatches"] == 1
        claim = repo.get(first.json()["formal_claim_id"], "formal_release_claim")
        assert claim["state"] == "complete"


def test_uncertain_provider_result_keeps_grant_consumed_and_does_not_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    provider = _Provider(fail=True)
    manifest = _manifest()
    app = create_gateway(tmp_path / "gateway-unknown", secret=SECRET, provider=provider, build_manifest=manifest)
    request = _request()
    envelope = _envelope(request, _bundle(request, manifest))
    with TestClient(app) as client:
        first = client.post("/dispatch", json=envelope)
        second = client.post("/dispatch", json=envelope)
    assert first.status_code == 200
    assert first.json()["status"] == "unknown"
    assert second.json() == first.json()
    assert provider.calls == 1
    with app.state.store.read() as repo:
        assert repo.get("grant-once", "one_time_dispatch_grant")["state"] == "consumed"


def test_demo_profile_rejects_cloud_dispatch_even_with_signed_demo_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "demo")
    app = create_gateway(tmp_path / "gateway-demo", secret=SECRET, provider=_Provider())
    request = _request(profile="demo", mode="demo", transport="cloud")
    with TestClient(app) as client:
        response = client.post("/dispatch", json=_envelope(request))
    assert response.status_code == 403
    assert "offline" in response.text.lower() or "demo" in response.text.lower()


def test_integration_profile_allows_synthetic_cloud_without_consuming_formal_grant(monkeypatch, tmp_path):
    monkeypatch.setenv("LEX_RUN_PROFILE", "integration")
    provider = _Provider()
    app = create_gateway(tmp_path / "gateway-integration", secret=SECRET, provider=provider)
    request = _request(profile="integration", mode="demo", transport="cloud")
    with TestClient(app) as client:
        response = client.post("/dispatch", json=_envelope(request))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "complete"
    assert provider.calls == 1
    with app.state.store.read() as repo:
        assert repo.list("formal_release_claim") == []
