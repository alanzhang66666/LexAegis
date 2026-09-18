import json
from hashlib import sha256

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from lexaegis.evidence import EvidenceIntegrityError, EvidenceStore
from lexaegis.storage import Store


def make_evidence_store(tmp_path):
    business_store = Store(tmp_path / "business.sqlite")
    evidence_store = EvidenceStore(business_store, tmp_path / "controlled-evidence")
    return business_store, evidence_store


def test_registers_controlled_bytes_and_hash_centered_business_metadata(tmp_path):
    business_store, evidence_store = make_evidence_store(tmp_path)
    protected_content = b"synthetic protected evidence body"
    source_hint = "intake/synthetic-evidence.pdf"

    artifact = evidence_store.register_artifact(
        content=protected_content,
        media_type="application/pdf",
        source_path_hint=source_hint,
        actor="auditor-001",
    )

    assert artifact.content_hash == sha256(protected_content).hexdigest()
    assert artifact.storage_ref == f"sha256:{artifact.content_hash}"
    assert evidence_store.read_artifact(artifact.id) == protected_content
    with business_store.read() as repo:
        stored = repo.get(artifact.id, "evidence_artifact")
        audit_record = next(
            item for item in repo.list("audit") if item["event"] == "evidence.registered"
        )
    assert stored == artifact.model_dump(mode="json")
    assert stored["media_type"] == "application/pdf"
    assert stored["source_path_hint"] == source_hint
    assert stored["storage_ref"] == artifact.storage_ref
    serialized_audit = json.dumps(audit_record, ensure_ascii=False)
    assert protected_content.decode() not in serialized_audit
    assert source_hint not in serialized_audit
    assert audit_record["metadata"] == {
        "evidence_id": artifact.id,
        "content_hash": artifact.content_hash,
        "media_type": "application/pdf",
        "storage_ref": artifact.storage_ref,
    }


def test_equal_content_reuses_one_controlled_blob_but_keeps_business_references(tmp_path):
    business_store, evidence_store = make_evidence_store(tmp_path)
    content = b"same protected bytes"

    first = evidence_store.register_artifact(
        content=content,
        media_type="application/pdf",
        source_path_hint="first.pdf",
        actor="reviewer-001",
    )
    second = evidence_store.register_artifact(
        content=content,
        media_type="image/png",
        source_path_hint="second.png",
        actor="reviewer-002",
    )

    assert first.id != second.id
    assert first.storage_ref == second.storage_ref
    assert len(list((tmp_path / "controlled-evidence").rglob(first.content_hash))) == 1
    with business_store.read() as repo:
        assert {item["id"] for item in repo.list("evidence_artifact")} == {
            first.id,
            second.id,
        }


def test_rejects_invalid_registration_and_detects_tampered_content(tmp_path):
    _, evidence_store = make_evidence_store(tmp_path)
    with pytest.raises(ValueError, match="nonempty bytes"):
        evidence_store.register_artifact(
            content=b"",
            media_type="application/pdf",
            source_path_hint="blank.pdf",
            actor="reviewer-001",
        )

    artifact = evidence_store.register_artifact(
        content=b"original",
        media_type="application/octet-stream",
        source_path_hint="synthetic.bin",
        actor="reviewer-001",
    )
    blob = next((tmp_path / "controlled-evidence").rglob(artifact.content_hash))
    blob.write_bytes(b"tampered")

    with pytest.raises(EvidenceIntegrityError, match="hash mismatch"):
        evidence_store.read_artifact(artifact.id)
    with pytest.raises(EvidenceIntegrityError, match="integrity check"):
        evidence_store.register_artifact(
            content=b"original",
            media_type="application/octet-stream",
            source_path_hint="synthetic-copy.bin",
            actor="reviewer-001",
        )


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.binary(min_size=1, max_size=4096))
def test_content_address_round_trips_arbitrary_bytes(tmp_path, content):
    """**Validates: Requirements 2.4, 14.3, 14.4**"""
    _, evidence_store = make_evidence_store(tmp_path)

    artifact = evidence_store.register_artifact(
        content=content,
        media_type="application/octet-stream",
        source_path_hint="property-generated.bin",
        actor="property-reviewer",
    )

    expected_hash = sha256(content).hexdigest()
    assert artifact.content_hash == expected_hash
    assert artifact.storage_ref == f"sha256:{expected_hash}"
    assert evidence_store.read_artifact(artifact.id) == content
