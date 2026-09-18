import json
import sqlite3

import pytest

from lexaegis.storage import CURRENT_REVISION, Store


LEGACY_REVISIONS = ("0001_aggregates", "0002_v2_contracts")


def _create_legacy_database(path, revision: str, *, conflicting_claim_table: bool = False):
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);"
        f"INSERT INTO alembic_version VALUES('{revision}');"
        "CREATE TABLE records("
        "id VARCHAR PRIMARY KEY,kind VARCHAR NOT NULL,scope VARCHAR NOT NULL,body TEXT NOT NULL"
        ");"
        "CREATE INDEX records_kind_scope ON records(kind,scope);"
    )
    if revision == "0002_v2_contracts":
        connection.execute("CREATE INDEX records_scope_kind ON records(scope,kind)")
    if conflicting_claim_table:
        connection.execute("CREATE TABLE formal_release_claims(sentinel TEXT)")
    body = {"id": "case_old", "name": "历史案件", "mapping": {"林甲": "主体1"}}
    connection.execute(
        "INSERT INTO records VALUES(?,?,?,?)",
        ("case_old", "case", "", json.dumps(body, ensure_ascii=False)),
    )
    connection.commit()
    connection.close()
    return body


def _revision(connection) -> str:
    return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _table_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


@pytest.mark.parametrize("legacy_revision", LEGACY_REVISIONS)
def test_legacy_database_is_backed_up_and_upgraded_to_0003_without_rewriting_records(
    tmp_path, legacy_revision
):
    path = tmp_path / f"legacy-{legacy_revision}.sqlite"
    body = _create_legacy_database(path, legacy_revision)

    store = Store(path)

    with store.read() as repo:
        assert repo.get("case_old", "case") == body

    check = sqlite3.connect(path)
    assert _revision(check) == CURRENT_REVISION
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "formal_release_claims" in _table_names(check)
    record_indexes = {row[1] for row in check.execute("PRAGMA index_list('records')")}
    assert {"records_kind_scope", "records_scope_kind"} <= record_indexes
    claim_indexes = {
        row[1]: bool(row[2])
        for row in check.execute("PRAGMA index_list('formal_release_claims')")
    }
    assert claim_indexes.items() >= {
        "formal_release_request_hash_unique": True,
        "formal_release_grant_nonce_unique": True,
        "formal_release_gateway_request_id_unique": True,
        "formal_release_policy_slot_unique": True,
    }.items()
    check.close()

    backup = path.with_name(path.name + ".pre-0003.bak")
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert _revision(old) == legacy_revision
    assert old.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "formal_release_claims" not in _table_names(old)
    assert json.loads(
        old.execute("SELECT body FROM records WHERE id='case_old'").fetchone()[0]
    ) == body
    old.close()


def _insert_claim(connection, claim):
    connection.execute(
        "INSERT INTO formal_release_claims("
        "id,request_hash,grant_nonce,gateway_request_id,policy_id,policy_slot"
        ") VALUES(?,?,?,?,?,?)",
        (
            claim["id"],
            claim["request_hash"],
            claim.get("grant_nonce"),
            claim.get("gateway_request_id"),
            claim.get("policy_id"),
            claim.get("policy_slot"),
        ),
    )


@pytest.mark.parametrize(
    ("unique_key", "first", "duplicate"),
    [
        (
            "request_hash",
            {"id": "claim-1", "request_hash": "request-1"},
            {"id": "claim-2", "request_hash": "request-1"},
        ),
        (
            "grant_nonce",
            {"id": "claim-1", "request_hash": "request-1", "grant_nonce": "nonce-1"},
            {"id": "claim-2", "request_hash": "request-2", "grant_nonce": "nonce-1"},
        ),
        (
            "gateway_request_id",
            {
                "id": "claim-1",
                "request_hash": "request-1",
                "gateway_request_id": "gateway-request-1",
            },
            {
                "id": "claim-2",
                "request_hash": "request-2",
                "gateway_request_id": "gateway-request-1",
            },
        ),
        (
            "policy_slot",
            {
                "id": "claim-1",
                "request_hash": "request-1",
                "policy_id": "policy-1",
                "policy_slot": 1,
            },
            {
                "id": "claim-2",
                "request_hash": "request-2",
                "policy_id": "policy-1",
                "policy_slot": 1,
            },
        ),
    ],
)
def test_formal_release_claim_keys_are_unique(tmp_path, unique_key, first, duplicate):
    path = tmp_path / f"duplicate-{unique_key}.sqlite"
    Store(path)
    connection = sqlite3.connect(path)
    _insert_claim(connection, first)
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_claim(connection, duplicate)
    connection.rollback()

    assert connection.execute("SELECT COUNT(*) FROM formal_release_claims").fetchone()[0] == 1
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


@pytest.mark.parametrize("legacy_revision", LEGACY_REVISIONS)
def test_failed_0003_migration_rolls_back_and_keeps_verified_backup(
    tmp_path, legacy_revision
):
    path = tmp_path / f"conflict-{legacy_revision}.sqlite"
    body = _create_legacy_database(
        path, legacy_revision, conflicting_claim_table=True
    )

    before = sqlite3.connect(path)
    original_schema = before.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='formal_release_claims'"
    ).fetchone()[0]
    original_record_indexes = {
        row[1] for row in before.execute("PRAGMA index_list('records')")
    }
    before.close()

    with pytest.raises(Exception):
        Store(path)

    check = sqlite3.connect(path)
    assert _revision(check) == legacy_revision
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert check.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='formal_release_claims'"
    ).fetchone()[0] == original_schema
    assert {row[1] for row in check.execute("PRAGMA index_list('records')")} == original_record_indexes
    assert not {
        row[1] for row in check.execute("PRAGMA index_list('formal_release_claims')")
    }
    assert json.loads(
        check.execute("SELECT body FROM records WHERE id='case_old'").fetchone()[0]
    ) == body
    check.close()

    backup = path.with_name(path.name + ".pre-0003.bak")
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert _revision(old) == legacy_revision
    assert old.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    old.close()
