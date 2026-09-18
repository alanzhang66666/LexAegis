import hashlib
import json
import sys
from pathlib import Path

import pytest

from lexaegis import cli
from lexaegis.runtime_pack import (
    FIRST_RELEASE_SCOPE,
    PUBLICATION_EFFECT,
    create_runtime_pack_draft,
    publish_runtime_pack,
    review_runtime_pack,
    runtime_pack_content_hash,
)
from lexaegis.storage import Store


SOURCE_PACK = Path(__file__).resolve().parent.parent / "packs" / "labor_v2_draft.json"
RISK_WEIGHTS = {
    "entity": 0.2,
    "density": 0.2,
    "context": 0.2,
    "combination": 0.2,
    "cross_round": 0.2,
}
LAW_05_BYTES = b"completed synthetic law-05 review evidence"
LAW_05_HASH = hashlib.sha256(LAW_05_BYTES).hexdigest()


def write_report(path: Path, marker: str = "pending") -> bytes:
    content = json.dumps(
        {"schema_version": 1, "status": marker, "synthetic_pass_count": 0},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"
    path.write_bytes(content)
    return content


def create_draft(store: Store, tmp_path: Path) -> tuple[dict, bytes]:
    source = tmp_path / "labor_v2_draft.json"
    source_bytes = SOURCE_PACK.read_bytes()
    source.write_bytes(source_bytes)
    report = tmp_path / "import-report.json"
    write_report(report)
    with store.transaction() as repo:
        draft = create_runtime_pack_draft(repo, source, report)
        repo.put("evidence_artifact", {
            "id": "evidence-law-05",
            "content_hash": LAW_05_HASH,
            "media_type": "application/pdf",
            "source_path_hint": "controlled/law-05.pdf",
            "template_kind": "法05_门5_规则发布法学签署",
            "created_at": "2026-09-14T00:00:00+00:00",
            "registered_by": "legal-reviewer-1",
            "storage_ref": f"sha256:{LAW_05_HASH}",
        })
    return draft, source_bytes


def valid_review_arguments() -> dict:
    return {
        "actor": "legal-reviewer-1",
        "review_record": "LAW05-LA001-20260914",
        "law_05_evidence_id": "evidence-law-05",
        "legal_status": "reviewed",
        "dispatch_allowed": True,
        "published_scope": dict(FIRST_RELEASE_SCOPE),
        "risk_weights": dict(RISK_WEIGHTS),
        "references": [
            "G-2026-09-12-v1.0",
            "docs/legal/案隐盾_系统法学规则与验收标准_v1.0.md",
        ],
    }


def test_create_runtime_pack_draft_copies_content_and_records_provenance(tmp_path):
    source = tmp_path / "labor_v2_draft.json"
    source_bytes = SOURCE_PACK.read_bytes()
    source.write_bytes(source_bytes)
    report = tmp_path / "import-report.json"
    report_bytes = write_report(report)
    store = Store(tmp_path / "app.sqlite")

    with store.transaction() as repo:
        record = create_runtime_pack_draft(repo, source, report)

    assert source.read_bytes() == source_bytes
    assert record["source_pack_hash"] == "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    assert record["import_report_hash"] == "sha256:" + hashlib.sha256(report_bytes).hexdigest()
    assert record["runtime_pack_hash"].startswith("sha256:")
    assert record["id"] == "runtime-pack:" + record["runtime_pack_hash"].removeprefix("sha256:")
    assert record["status"] == "draft"
    assert record["dispatch_allowed"] is False
    assert record["pack"]["version"] == "2.0.0-draft.3"
    assert record["pack"]["status"] == "draft"
    assert record["pack"]["dispatch_allowed"] is False

    source.unlink()
    with store.read() as repo:
        persisted = repo.get(record["id"], "runtime_pack")
    assert persisted["pack"] == record["pack"]


def test_runtime_pack_address_is_idempotent_and_changes_with_import_report(tmp_path):
    source = tmp_path / "labor_v2_draft.json"
    source.write_bytes(SOURCE_PACK.read_bytes())
    report = tmp_path / "import-report.json"
    write_report(report)
    store = Store(tmp_path / "app.sqlite")

    with store.transaction() as repo:
        first = create_runtime_pack_draft(repo, source, report)
        repeated = create_runtime_pack_draft(repo, source, report)
    assert repeated == first

    write_report(report, marker="pending-with-different-report")
    with store.transaction() as repo:
        changed = create_runtime_pack_draft(repo, source, report)
        records = repo.list("runtime_pack")

    assert changed["id"] != first["id"]
    assert changed["source_pack_hash"] == first["source_pack_hash"]
    assert changed["import_report_hash"] != first["import_report_hash"]
    assert len(records) == 2
    assert all(item["status"] == "draft" for item in records)
    assert all(item["dispatch_allowed"] is False for item in records)


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", "other"), ("version", "2.0.0"), ("dispatch_allowed", True)],
)
def test_runtime_pack_rejects_a_source_that_is_not_the_fixed_repository_draft(tmp_path, field, value):
    source_data = json.loads(SOURCE_PACK.read_text(encoding="utf-8"))
    source_data[field] = value
    source = tmp_path / "source.json"
    source.write_text(json.dumps(source_data, ensure_ascii=False), encoding="utf-8")
    report = tmp_path / "import-report.json"
    write_report(report)
    store = Store(tmp_path / "app.sqlite")

    with store.transaction() as repo, pytest.raises(ValueError):
        create_runtime_pack_draft(repo, source, report)

    with store.read() as repo:
        assert repo.list("runtime_pack") == []


def test_runtime_pack_create_draft_cli_persists_only_a_blocked_draft(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "app"
    report = tmp_path / "import-report.json"
    write_report(report)
    monkeypatch.setenv("LEX_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lexaegis",
            "runtime-pack",
            "create-draft",
            "--source",
            str(SOURCE_PACK),
            "--import-report",
            str(report),
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "draft"
    assert output["dispatch_allowed"] is False
    with Store(data_dir / "app.sqlite").read() as repo:
        records = repo.list("runtime_pack")
    assert len(records) == 1
    assert records[0]["id"] == output["id"]
    assert records[0]["status"] == "draft"
    assert records[0]["dispatch_allowed"] is False


def test_review_and_publish_runtime_pack_freezes_exact_scope_without_authorizing_send(tmp_path):
    store = Store(tmp_path / "app.sqlite")
    draft, source_bytes = create_draft(store, tmp_path)

    with store.transaction() as repo:
        reviewed = review_runtime_pack(repo, draft["id"], **valid_review_arguments())

    assert reviewed["status"] == "reviewed"
    assert reviewed["legal_status"] == "reviewed"
    assert reviewed["dispatch_allowed"] is True
    assert reviewed["published_scope"] == FIRST_RELEASE_SCOPE
    assert reviewed["risk_weights"] == RISK_WEIGHTS
    assert reviewed["risk_weights_frozen"] is True
    assert reviewed["law_05_evidence_hash"] == LAW_05_HASH
    assert reviewed["publication_effect"] == PUBLICATION_EFFECT
    assert reviewed["content_hash"] == runtime_pack_content_hash(reviewed)

    with store.transaction() as repo:
        published = publish_runtime_pack(repo, draft["id"], actor="runtime-pack-publisher-1")
        assert repo.list("formal_release_policy") == []
        assert repo.list("one_time_dispatch_grant") == []
        assert repo.list("dispatch_intent") == []
        assert repo.list("gateway_record") == []

    assert published["status"] == "published"
    assert published["published_by"] == "runtime-pack-publisher-1"
    assert published["content_hash"] == reviewed["content_hash"]
    assert published["content_hash"] == runtime_pack_content_hash(published)
    assert (tmp_path / "labor_v2_draft.json").read_bytes() == source_bytes
    assert SOURCE_PACK.read_bytes() == source_bytes
    assert published["pack"]["status"] == "draft"
    assert published["pack"]["dispatch_allowed"] is False


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("legal_status", "pending_legal_review"),
        ("dispatch_allowed", False),
        ("published_scope", {"case_id": "*", "purpose": "R_fact_summary", "recipient": "D_DeepSeek_official_API"}),
        ("published_scope", {**FIRST_RELEASE_SCOPE, "model": "*"}),
        ("published_scope", {**FIRST_RELEASE_SCOPE, "valid_until": "2026-09-15T00:00:00Z"}),
        ("risk_weights", {key: value for key, value in RISK_WEIGHTS.items() if key != "cross_round"}),
        ("risk_weights", {**RISK_WEIGHTS, "other": 0.1}),
        ("risk_weights", {**RISK_WEIGHTS, "entity": 1.1}),
        ("references", []),
        ("review_record", ""),
    ],
)
def test_runtime_pack_review_rejects_each_incomplete_publication_condition(tmp_path, field, invalid_value):
    store = Store(tmp_path / "app.sqlite")
    draft, _ = create_draft(store, tmp_path)
    arguments = valid_review_arguments()
    arguments[field] = invalid_value

    with store.transaction() as repo, pytest.raises(ValueError):
        review_runtime_pack(repo, draft["id"], **arguments)

    with store.read() as repo:
        persisted = repo.get(draft["id"], "runtime_pack")
    assert persisted["status"] == "draft"
    assert persisted["dispatch_allowed"] is False


@pytest.mark.parametrize("evidence_problem", ["missing", "wrong_template", "bad_hash", "bad_storage_ref"])
def test_runtime_pack_review_requires_existing_content_addressed_law_05_evidence(tmp_path, evidence_problem):
    store = Store(tmp_path / "app.sqlite")
    draft, _ = create_draft(store, tmp_path)
    arguments = valid_review_arguments()

    with store.transaction() as repo:
        if evidence_problem == "missing":
            arguments["law_05_evidence_id"] = "evidence-missing"
        else:
            evidence = repo.get("evidence-law-05", "evidence_artifact")
            if evidence_problem == "wrong_template":
                evidence["template_kind"] = "法01_来源人审"
            elif evidence_problem == "bad_hash":
                evidence["content_hash"] = "not-a-hash"
            else:
                evidence["storage_ref"] = "sha256:" + "0" * 64
            repo.put("evidence_artifact", evidence)

    with store.transaction() as repo, pytest.raises(ValueError):
        review_runtime_pack(repo, draft["id"], **arguments)

    with store.read() as repo:
        persisted = repo.get(draft["id"], "runtime_pack")
    assert persisted["status"] == "draft"


def test_runtime_pack_publish_revalidates_hash_and_leaves_reviewed_record_on_failure(tmp_path):
    store = Store(tmp_path / "app.sqlite")
    draft, _ = create_draft(store, tmp_path)
    with store.transaction() as repo:
        review_runtime_pack(repo, draft["id"], **valid_review_arguments())

    with pytest.raises(ValueError):
        with store.transaction() as repo:
            tampered = repo.get(draft["id"], "runtime_pack")
            tampered["risk_weights"] = {**tampered["risk_weights"], "entity": 0.9}
            repo.put("runtime_pack", tampered)
            publish_runtime_pack(repo, draft["id"], actor="publisher-1")

    with store.read() as repo:
        persisted = repo.get(draft["id"], "runtime_pack")
    assert persisted["status"] == "reviewed"
    assert persisted["risk_weights"] == RISK_WEIGHTS


def test_runtime_pack_cannot_publish_a_draft_directly(tmp_path):
    store = Store(tmp_path / "app.sqlite")
    draft, _ = create_draft(store, tmp_path)

    with store.transaction() as repo, pytest.raises(ValueError, match="reviewed"):
        publish_runtime_pack(repo, draft["id"], actor="publisher-1")

    with store.read() as repo:
        persisted = repo.get(draft["id"], "runtime_pack")
    assert persisted["status"] == "draft"
    assert persisted["dispatch_allowed"] is False


def _publish_runtime_pack_for_invalidation(store: Store, tmp_path: Path) -> tuple[dict, bytes]:
    draft, source_bytes = create_draft(store, tmp_path)
    with store.transaction() as repo:
        review_runtime_pack(repo, draft["id"], **valid_review_arguments())
        published = publish_runtime_pack(repo, draft["id"], actor="runtime-pack-publisher-1")
    return published, source_bytes


def test_retire_runtime_pack_invalidates_only_unclaimed_dependents_and_preserves_history(tmp_path):
    """Validates: Requirements 4.5, 13.2."""
    from lexaegis.runtime_pack import retire_runtime_pack

    store = Store(tmp_path / "app.sqlite")
    published, source_bytes = _publish_runtime_pack_for_invalidation(store, tmp_path)
    old_hash = published["runtime_pack_hash"]
    open_request = {
        "id": "frozen-open",
        "request_id": "request-open",
        "request_hash": "sha256:request-open",
        "runtime_pack_hash": old_hash,
    }
    claimed_request = {
        "id": "frozen-claimed",
        "request_id": "request-claimed",
        "request_hash": "sha256:request-claimed",
        "runtime_pack_hash": old_hash,
    }
    unknown_request = {
        "id": "frozen-unknown",
        "request_id": "request-unknown",
        "request_hash": "sha256:request-unknown",
        "runtime_pack_hash": old_hash,
    }
    unrelated_request = {
        "id": "frozen-unrelated",
        "request_id": "request-unrelated",
        "request_hash": "sha256:request-unrelated",
        "runtime_pack_hash": "sha256:" + "f" * 64,
    }
    claimed_snapshot = {
        "id": "snapshot-claimed",
        "request_hash": claimed_request["request_hash"],
        "status": "pass",
        "dispatch_allowed": True,
    }
    unknown_snapshot = {
        "id": "snapshot-unknown",
        "request_hash": unknown_request["request_hash"],
        "status": "pass",
        "dispatch_allowed": True,
    }
    claimed_grant = {
        "id": "grant-claimed",
        "request_hash": claimed_request["request_hash"],
        "state": "claimed",
        "gateway_attempt_id": "attempt-claimed",
    }
    unknown_grant = {
        "id": "grant-unknown",
        "request_hash": unknown_request["request_hash"],
        "state": "consumed",
        "gateway_attempt_id": "attempt-unknown",
    }
    claimed_gateway = {
        "id": "gateway-claimed",
        "request_id": claimed_request["request_id"],
        "request_hash": claimed_request["request_hash"],
        "status": "sending",
    }
    unknown_gateway = {
        "id": "gateway-unknown",
        "request_id": unknown_request["request_id"],
        "request_hash": unknown_request["request_hash"],
        "status": "unknown",
        "disclosure_state": "possible",
    }

    with store.transaction() as repo:
        for request in (open_request, claimed_request, unknown_request, unrelated_request):
            repo.put("frozen_formal_request", request)
        repo.put("gate_snapshot", {
            "id": "snapshot-open",
            "request_hash": open_request["request_hash"],
            "status": "pass",
            "approval_eligible": True,
            "dispatch_allowed": True,
        })
        repo.put("gate_snapshot", claimed_snapshot)
        repo.put("gate_snapshot", unknown_snapshot)
        repo.put("gate_evidence_receipt", {
            "id": "receipt-open",
            "gate_id": "G7",
            "request_hash": open_request["request_hash"],
            "conclusion": "pass",
        })
        repo.put("one_time_dispatch_grant", {
            "id": "grant-open",
            "request_hash": open_request["request_hash"],
            "state": "issued",
        })
        repo.put("one_time_dispatch_grant", claimed_grant)
        repo.put("one_time_dispatch_grant", unknown_grant)
        repo.put("dispatch_intent", {
            "id": "intent-open",
            "request_hash": open_request["request_hash"],
            "status": "pending",
        })
        repo.put("dispatch_intent", {
            "id": "intent-claimed",
            "request_hash": claimed_request["request_hash"],
            "status": "sending",
        })
        repo.put("gateway_record", claimed_gateway)
        repo.put("gateway_record", unknown_gateway)
        retired = retire_runtime_pack(
            repo,
            published["id"],
            actor="runtime-pack-admin-1",
            reason="runtime_pack_retired",
        )

    assert retired["status"] == "retired"
    assert retired["dispatch_allowed"] is False
    assert retired["dependent_invalidation"]["request_ids"] == ["request-open"]
    assert retired["dependent_invalidation"]["grant_ids"] == ["grant-open"]
    assert (tmp_path / "labor_v2_draft.json").read_bytes() == source_bytes
    assert SOURCE_PACK.read_bytes() == source_bytes

    with store.read() as repo:
        assert len(repo.list("frozen_formal_request")) == 4
        assert len(repo.list("gate_snapshot")) == 3
        assert len(repo.list("one_time_dispatch_grant")) == 3
        assert repo.get("frozen-open", "frozen_formal_request")["invalidation_status"] == "invalidated"
        invalidated_snapshot = repo.get("snapshot-open", "gate_snapshot")
        assert invalidated_snapshot["status"] == "invalidated"
        assert invalidated_snapshot["approval_eligible"] is False
        assert invalidated_snapshot["dispatch_allowed"] is False
        receipt = repo.get("receipt-open", "gate_evidence_receipt")
        assert receipt["conclusion"] == "pass"
        assert receipt["revocation_reason"] == "runtime_pack_retired"
        assert repo.get("intent-open", "dispatch_intent")["status"] == "cancelled"
        assert repo.get("grant-open", "one_time_dispatch_grant")["state"] == "revoked"
        assert repo.get("frozen-claimed", "frozen_formal_request") == claimed_request
        assert repo.get("frozen-unknown", "frozen_formal_request") == unknown_request
        assert repo.get("frozen-unrelated", "frozen_formal_request") == unrelated_request
        assert repo.get("snapshot-claimed", "gate_snapshot") == claimed_snapshot
        assert repo.get("snapshot-unknown", "gate_snapshot") == unknown_snapshot
        assert repo.get("grant-claimed", "one_time_dispatch_grant") == claimed_grant
        assert repo.get("grant-unknown", "one_time_dispatch_grant") == unknown_grant
        assert repo.get("gateway-claimed", "gateway_record") == claimed_gateway
        assert repo.get("gateway-unknown", "gateway_record") == unknown_gateway


def test_replace_runtime_pack_invalidates_old_hash_without_rewriting_repository_pack(tmp_path):
    """Validates: Requirements 4.5, 13.2."""
    from lexaegis.runtime_pack import replace_runtime_pack

    store = Store(tmp_path / "app.sqlite")
    published, source_bytes = _publish_runtime_pack_for_invalidation(store, tmp_path)
    replacement_source = tmp_path / "replacement-labor-v2.json"
    replacement_source.write_bytes(source_bytes)
    replacement_report = tmp_path / "replacement-report.json"
    write_report(replacement_report, marker="changed-review-input")
    with store.transaction() as repo:
        replacement = create_runtime_pack_draft(repo, replacement_source, replacement_report)
        review_runtime_pack(repo, replacement["id"], **valid_review_arguments())
        repo.put("frozen_formal_request", {
            "id": "frozen-former-hash",
            "request_id": "request-former-hash",
            "request_hash": "sha256:request-former-hash",
            "runtime_pack_hash": published["runtime_pack_hash"],
        })
        repo.put("one_time_dispatch_grant", {
            "id": "grant-former-hash",
            "request_hash": "sha256:request-former-hash",
            "state": "reserved",
        })
        changed = replace_runtime_pack(
            repo,
            published["id"],
            replacement["id"],
            actor="runtime-pack-admin-1",
        )

    assert changed["status"] == "published"
    assert changed["runtime_pack_hash"] != published["runtime_pack_hash"]
    assert changed["replaces_runtime_pack_id"] == published["id"]
    assert changed["dependent_invalidation"]["request_ids"] == ["request-former-hash"]
    assert (tmp_path / "labor_v2_draft.json").read_bytes() == source_bytes
    assert SOURCE_PACK.read_bytes() == source_bytes

    with store.read() as repo:
        former = repo.get(published["id"], "runtime_pack")
        assert former["status"] == "retired"
        assert former["replaced_by_runtime_pack_id"] == replacement["id"]
        assert repo.get("frozen-former-hash", "frozen_formal_request")["invalidation_status"] == "invalidated"
        assert repo.get("grant-former-hash", "one_time_dispatch_grant")["state"] == "revoked"
