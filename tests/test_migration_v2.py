import json
import sqlite3
import pytest

from lexaegis.storage import CURRENT_REVISION, Store


def test_v1_database_is_backed_up_and_migrated_without_rewriting_records(tmp_path):
    path=tmp_path/"legacy.sqlite"
    connection=sqlite3.connect(path)
    connection.executescript("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL); INSERT INTO alembic_version VALUES('0001_aggregates'); CREATE TABLE records(id VARCHAR PRIMARY KEY,kind VARCHAR NOT NULL,scope VARCHAR NOT NULL,body TEXT NOT NULL); CREATE INDEX records_kind_scope ON records(kind,scope);")
    body={"id":"case_old","name":"历史案件","mapping":{"林甲":"主体1"}}
    connection.execute("INSERT INTO records VALUES(?,?,?,?)",("case_old","case","",json.dumps(body,ensure_ascii=False)))
    connection.commit();connection.close()
    store=Store(path)
    with store.read() as repo:
        assert repo.get("case_old","case")==body
    check=sqlite3.connect(path)
    assert check.execute("SELECT version_num FROM alembic_version").fetchone()[0]==CURRENT_REVISION
    assert check.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    check.close()
    backup=path.with_name(path.name+".pre-0002.bak")
    assert backup.exists()
    old=sqlite3.connect(backup)
    assert old.execute("SELECT version_num FROM alembic_version").fetchone()[0]=="0001_aggregates"
    assert json.loads(old.execute("SELECT body FROM records WHERE id='case_old'").fetchone()[0])==body
    old.close()


def test_failed_migration_keeps_v1_revision_and_verified_backup(tmp_path):
    path=tmp_path/"conflict.sqlite"
    connection=sqlite3.connect(path)
    connection.executescript("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL); INSERT INTO alembic_version VALUES('0001_aggregates'); CREATE TABLE records(id VARCHAR PRIMARY KEY,kind VARCHAR NOT NULL,scope VARCHAR NOT NULL,body TEXT NOT NULL); CREATE INDEX records_kind_scope ON records(kind,scope); CREATE INDEX records_scope_kind ON records(scope,kind);")
    connection.commit();connection.close()
    with pytest.raises(Exception):
        Store(path)
    check=sqlite3.connect(path)
    assert check.execute("SELECT version_num FROM alembic_version").fetchone()[0]=="0001_aggregates"
    assert check.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    check.close()
    assert path.with_name(path.name+".pre-0002.bak").exists()
