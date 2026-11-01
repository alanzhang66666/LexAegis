"""Opt-in exact-request policy: all existing live gates remain authoritative."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from lexaegis import formal_release, release_service, service
from lexaegis.contracts import IsolationReceipt
from lexaegis.evidence import EvidenceIntakeService, EvidenceStore
from lexaegis.gateway import create_gateway
from lexaegis.runtime_profile import bind_runtime
from lexaegis.storage import Store
from lexaegis.util import digest
from lexaegis.worker import process_one
from tests.test_release_service_integration import (
    SECRET, _Provider, _hash, _identities, _manifest, _register_receipt, _seed_business_state,
)


@pytest.fixture
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", SECRET)
    monkeypatch.setenv("LEX_AUTO_REQUEST_POLICY", "1")
    manifest = _manifest()
    store = Store(tmp_path / "app.sqlite")
    root = tmp_path / "app"
    bind_runtime(root, "app")
    evidence = EvidenceStore(store, root / "release-evidence")
    intake = EvidenceIntakeService(evidence)
    provider = _Provider()
    gateway = create_gateway(tmp_path / "gateway", secret=SECRET, provider=provider, build_manifest=manifest)
    context = {"build_manifest": manifest, "runtime_identities": _identities(manifest), "evidence_intake": intake}
    try:
        with store.transaction() as repo:
            task, case, pack, profile = _seed_business_state(repo, manifest)
            scope = {"domain":"labor", "purpose":"R_fact_summary", "recipient":profile["id"]}
            repo.put("runtime_pack", {"id":"auto-runtime", "status":"published", "scope_kind":"request", "published_scope":scope})
            repo.put("runtime_pack_activation", {"id":"auto-activation", "pack_id":pack["id"],
                "runtime_pack_id":"auto-runtime", "artifact_sha256":manifest.runtime_pack_hash})
            frozen = formal_release.freeze_request(repo, task=task, case=case, build_manifest=manifest,
                                                    runtime_identities=_identities(manifest))
        scope = {"case_id":case["reference_code"], "purpose":"R_fact_summary", "recipient":profile["id"]}
        frozen = frozen.model_copy(update={"tuple":scope})
        versions = {"materials":digest(frozen.material_versions), "rules":digest(frozen.rule_versions),
                    "task":str(frozen.task_version), "mapping":str(frozen.mapping_version),
                    "ledger":str(frozen.ledger_version), "combination":frozen.combination_input_hash}
        def register(gate, template, role="legal_reviewer", technical=None, actor=None):
            return _register_receipt(intake, evidence, gate, template,
                actor=actor or ("审批人甲" if role == "approver" else ("技术甲" if role == "technical_reviewer" else "法学甲")),
                role=role, versions=versions, request_hash=frozen.request_hash, technical_template=technical,
                release_tuple=scope)
        g1 = register("G1", "法01")
        register("G2", "法02"); register("G3", "法03"); register("G3", "法04"); register("G5", "法05")
        register("G6", "技03", "technical_reviewer"); register("G7", "法08", technical="技04")
        g8 = register("G8", "法09", technical="技05"); register("G9", "法10", technical="技06")
        g10 = register("G10", "技08", "approver")
        # The fixture helper records under a generic operator. Bind the
        # synthetic G10 action to the synthetic authenticated account.
        with store.transaction() as repo:
            action = next(x for x in repo.list("evidence_role_action") if x.get("receipt_id") == g10.id)
            action["recorded_by"] = "synthetic-user"
            repo.put("evidence_role_action", action)
        stamp = datetime.now(timezone.utc)
        isolation = IsolationReceipt(
            id="auto-isolation", request_hash=frozen.request_hash, tuple=scope,
            build_manifest_hash=frozen.build_manifest_hash, deployment_mode="isolated",
            deployment_identity_hash=_hash("3"), compose_hash=_hash("4"), image_digests=manifest.container_image_digests,
            api_no_egress=True, worker_no_egress=True, gateway_no_case_volume=True,
            redteam_no_secrets=True, benchmark_no_secrets=True, probe_output_hash=_hash("5"),
            host_firewall_evidence_hash=_hash("6"), supply_chain_evidence_hash=_hash("7"),
            generated_at=(stamp-timedelta(minutes=1)).isoformat(), expires_at=(stamp+timedelta(minutes=20)).isoformat(),
            attested_by="synthetic-technical", legal_confirmation_receipt_id=g8.id, status="valid")
        with store.transaction() as repo:
            repo.put("isolation_receipt", isolation.model_dump(mode="json"), case["id"])
        monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: context)
        yield {"store":store,"root":root,"gateway":gateway,"provider":provider,"context":context,
               "task":task,"case":case,"intake":intake,"g1":g1,"g10":g10,"scope":scope}
    finally:
        store.engine.dispose(); gateway.state.store.engine.dispose()


def approve(f, repo, actor="审批人甲", role="approver", user="synthetic-user"):
    return service.approve_task(repo, f["task"]["id"], f["task"]["request_hash"], actor=actor,
                                actor_role=role, actor_user_id=user, release_context=f["context"])


def test_full_opt_in_approval_creates_one_request_policy_and_sends_once(ready):
    f = ready
    with f["store"].transaction() as repo:
        status = release_service.status(repo, f["task"], f["case"], f["context"])
        assert status["state"] == "blocked" and status["auto_policy_candidate"] is True
        assert repo.list("formal_release_policy") == []
        task = approve(f, repo)
        policies = repo.list("formal_release_policy")
        assert len(policies) == 1
        policy = policies[0]
        assert policy["scope_kind"] == "request" and policy["bound_request_hash"] == task["request_hash"]
        assert policy["tuple"] == f["scope"] and policy["status"] == "armed_once"
        assert policy["installed_by"] == "审批人甲" and policy["maximum_dispatches"] == 1
        assert task["formal_release"]["grant"]["state"] == "issued"
        events = [x for x in repo.list("audit", f["case"]["id"]) if x["event"] == "formal_release.policy_installed"]
        assert events[-1]["metadata"]["actor_role"] == "approver"
        assert events[-1]["metadata"]["actor_user_id"] == "synthetic-user"
        assert events[-1]["metadata"]["authorization_mode"] == "auto_request_g10"
        service.reserve_send(repo, task["id"], release_context=f["context"])
    with TestClient(f["gateway"]) as client:
        assert process_one(f["store"], f["root"], client)
        assert not process_one(f["store"], f["root"], client)
    assert f["provider"].calls == 1
    with f["store"].read() as repo:
        assert repo.get(task["id"], "task")["status"] == "complete"
        assert repo.list("formal_release_policy")[0]["status"] == "consumed"


def test_default_off_requires_existing_admin_policy(ready, monkeypatch):
    f = ready; monkeypatch.delenv("LEX_AUTO_REQUEST_POLICY", raising=False)
    with f["store"].transaction() as repo:
        assert "auto_policy_candidate" not in release_service.status(repo, f["task"], f["case"], f["context"])
        with pytest.raises(ValueError): approve(f, repo)
        assert repo.list("formal_release_policy") == [] and repo.list("one_time_dispatch_grant") == []


def test_tampered_controlled_evidence_never_creates_policy_or_grant(ready):
    f = ready
    evidence = f["intake"].evidence_store
    artifact = evidence.get_artifact(f["g1"].evidence_artifact_ids[0])
    evidence._path_for_ref(artifact.storage_ref).write_bytes(b"synthetic tampered evidence")
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError): approve(f, repo)
        assert repo.list("formal_release_policy") == [] and repo.list("one_time_dispatch_grant") == []


def test_missing_live_gate_rolls_back_candidate_even_if_caller_catches(ready):
    f = ready
    f["intake"].revoke_evidence(f["g1"].id, "synthetic revoke", actor="法学甲", actor_role="legal_reviewer")
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError, match="正式放行未满足"):
            approve(f, repo)
        assert repo.list("formal_release_policy") == [] and repo.list("one_time_dispatch_grant") == []
        assert repo.get(f["task"]["id"], "task")["approval"] is None


@pytest.mark.parametrize("actor,role,user", [("其他审批人","approver","user-2"), ("审批人甲","admin","user-1"), ("审批人甲","approver",None), ("审批人甲","approver","different-user")])
def test_wrong_or_unidentified_actor_cannot_create_policy(ready, actor, role, user):
    f = ready
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError): approve(f, repo, actor=actor, role=role, user=user)
        assert repo.list("formal_release_policy") == [] and repo.list("one_time_dispatch_grant") == []


def test_runtime_artifact_mismatch_never_installs_policy(ready):
    f = ready
    with f["store"].transaction() as repo:
        activation = repo.get("auto-activation", "runtime_pack_activation")
        activation["artifact_sha256"] = _hash("0")
        repo.put("runtime_pack_activation", activation)
        with pytest.raises(ValueError): approve(f, repo)
        assert repo.list("formal_release_policy") == []


def test_two_concurrent_approvals_create_at_most_one_grant(ready):
    f = ready
    def run(_):
        try:
            with f["store"].transaction() as repo:
                approve(f, repo)
            return "approved"
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ["approved", "rejected"]
    with f["store"].read() as repo:
        assert len(repo.list("formal_release_policy")) == 1 and len(repo.list("one_time_dispatch_grant")) == 1


def test_missing_g10_or_disabled_flag_cannot_install_approver_policy(ready, monkeypatch):
    f = ready
    with f["store"].transaction() as repo:
        candidate = release_service.auto_request_policy_candidate(repo, f["task"], f["case"], f["context"])
        monkeypatch.delenv("LEX_AUTO_REQUEST_POLICY", raising=False)
        with pytest.raises(ValueError):
            formal_release.install_policy(repo, candidate, actor="审批人甲", actor_role="approver")
        assert repo.list("formal_release_policy") == []
    monkeypatch.setenv("LEX_AUTO_REQUEST_POLICY", "1")
    f["intake"].revoke_evidence(f["g10"].id, "synthetic revoke", actor="审批人甲", actor_role="approver")
    with f["store"].transaction() as repo:
        with pytest.raises(ValueError, match="G10"):
            approve(f, repo)
        assert repo.list("formal_release_policy") == []


def test_failure_after_policy_creation_rolls_back_savepoint(ready, monkeypatch):
    f = ready
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic grant failure")
    monkeypatch.setattr(formal_release, "issue_grant", fail)
    with f["store"].transaction() as repo:
        with pytest.raises(RuntimeError, match="synthetic grant failure"):
            approve(f, repo)
        assert repo.list("formal_release_policy") == [] and repo.list("one_time_dispatch_grant") == []
        assert repo.get(f["task"]["id"], "task")["approval"] is None
        assert not [x for x in repo.list("audit", f["case"]["id"]) if x["event"] == "formal_release.policy_installed"]


def test_auto_policy_real_authenticated_http_approval(env, ready, monkeypatch):
    from tests.conftest import login_as
    f = ready
    # Copy only the synthetic business records; retain env's real local users.
    with f["store"].read() as source:
        rows = source.conn.execute(__import__("sqlalchemy").text("SELECT kind, scope, body FROM records")).all()
    import json
    kinds = {"case", "task", "pack", "provider", "settings", "document", "fact", "runtime_pack",
             "runtime_pack_activation", "gate_evidence_receipt", "evidence_role_action", "evidence_artifact", "isolation_receipt"}
    with env["app"].state.store.transaction() as target:
        for kind, scope, body in rows:
            if kind in kinds:
                data = json.loads(body)
                if kind == "gate_evidence_receipt" and data.get("id") == f["g10"].id:
                    continue
                if kind == "evidence_role_action" and data.get("receipt_id") == f["g10"].id:
                    continue
                target.put(kind, data, scope or "")
    login_as(env, "approver")
    with env["app"].state.store.transaction() as repo:
        user = repo.get("user:approver.test", "user")
        user["display_name"] = "审批人甲"
        repo.put("user", user)
    # Register G10 through the actual authenticated route so recorded_by is
    # established by the session, not supplied by the client.
    original = f["g10"]
    receipt_body = {"gate_id":"G10", "tuple":f["scope"], "template_kind":"技08",
                    "template_version":original.template_version, "template_artifact_id":original.template_artifact_id,
                    "bound_versions":{}, "request_hash":f["task"]["request_hash"], "conclusion":"pass",
                    "confirmed_by":"审批人甲", "confirmed_role":"approver", "confirmed_at":original.confirmed_at,
                    "valid_from":original.valid_from, "valid_until":original.valid_until,
                    "evidence_artifact_ids":original.evidence_artifact_ids}
    receipt_response = env["client"].post("/api/v1/formal-release/receipts", json=receipt_body)
    assert receipt_response.status_code == 200, receipt_response.text
    with env["app"].state.store.read() as repo:
        action = next(x for x in repo.list("evidence_role_action") if x.get("receipt_id") == receipt_response.json()["id"])
        assert action["recorded_by"] == user["id"]
    target_intake = EvidenceIntakeService(EvidenceStore(env["app"].state.store, env["root"] / "release-evidence"))
    monkeypatch.setattr(release_service, "collect_context", lambda *args, **kwargs: {**f["context"], "evidence_intake":target_intake})
    response = env["client"].post(f"/api/v1/tasks/{f['task']['id']}/approve", json={"request_hash":f["task"]["request_hash"]})
    assert response.status_code == 200, response.text
    assert response.json()["formal_release"]["policy"]["scope_kind"] == "request"
    with env["app"].state.store.read() as repo:
        assert len(repo.list("formal_release_policy")) == 1
        assert len(repo.list("one_time_dispatch_grant")) == 1
