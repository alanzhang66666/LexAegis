"""Small JSON aggregate store, with SQLAlchemy and versioned SQL migrations.

Write transactions serialize business transitions; no network calls inside them.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from .util import assert_local_filesystem, restrict_mode


CURRENT_REVISION = "0003_formal_release_uniques"


def _backup_before_migration(path: Path, target_revision: str) -> Path:
    revision_number = target_revision.split("_", 1)[0]
    backup = path.with_name(path.name + f".pre-{revision_number}.bak")
    if backup.exists():
        check = sqlite3.connect(backup)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Existing migration backup failed integrity check")
        finally:
            check.close()
        return backup
    source = sqlite3.connect(path)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
        target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Migration backup failed integrity check")
    except BaseException:
        target.close()
        backup.unlink(missing_ok=True)
        raise
    else:
        target.close()
    finally:
        source.close()
    restrict_mode(backup, 0o600)
    return backup


def _create_formal_release_claims(op: Operations) -> None:
    """Add the durable keys used to enforce at-most-once formal dispatch."""
    op.create_table(
        "formal_release_claims",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("request_hash", sa.String, nullable=False),
        sa.Column("grant_nonce", sa.String, nullable=True),
        sa.Column("gateway_request_id", sa.String, nullable=True),
        sa.Column("policy_id", sa.String, nullable=True),
        sa.Column("policy_slot", sa.Integer, nullable=True),
        sa.CheckConstraint("request_hash <> ''", name="formal_release_request_hash_nonempty"),
        sa.CheckConstraint("grant_nonce IS NULL OR grant_nonce <> ''", name="formal_release_grant_nonce_nonempty"),
        sa.CheckConstraint(
            "gateway_request_id IS NULL OR gateway_request_id <> ''",
            name="formal_release_gateway_request_id_nonempty",
        ),
        sa.CheckConstraint(
            "(policy_id IS NULL AND policy_slot IS NULL) "
            "OR (policy_id <> '' AND policy_slot = 1)",
            name="formal_release_policy_single_slot",
        ),
    )
    op.create_index(
        "formal_release_request_hash_unique",
        "formal_release_claims",
        ["request_hash"],
        unique=True,
    )
    op.create_index(
        "formal_release_grant_nonce_unique",
        "formal_release_claims",
        ["grant_nonce"],
        unique=True,
    )
    op.create_index(
        "formal_release_gateway_request_id_unique",
        "formal_release_claims",
        ["gateway_request_id"],
        unique=True,
    )
    op.create_index(
        "formal_release_policy_slot_unique",
        "formal_release_claims",
        ["policy_id", "policy_slot"],
        unique=True,
    )


def _verify_integrity(conn) -> None:
    if conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
        raise RuntimeError("Migrated database failed integrity check")


class Store:
    def __init__(self, path: Path):
        assert_local_filesystem(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        url = "sqlite:///" + Path(path).resolve().as_posix()
        self.engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 20})
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
            context = MigrationContext.configure(conn)
            context._ensure_version_table()
            revision = context.get_current_revision()
            if revision is None:
                op = Operations(context)
                op.create_table("records", sa.Column("id", sa.String, primary_key=True), sa.Column("kind", sa.String, nullable=False), sa.Column("scope", sa.String, nullable=False), sa.Column("body", sa.Text, nullable=False))
                op.create_index("records_kind_scope", "records", ["kind", "scope"])
                op.create_index("records_scope_kind", "records", ["scope", "kind"])
                _create_formal_release_claims(op)
                _verify_integrity(conn)
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": CURRENT_REVISION})
            elif revision in {"0001_aggregates", "0002_v2_contracts"}:
                conn.commit()
                _backup_before_migration(self.path, CURRENT_REVISION)
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    op = Operations(MigrationContext.configure(conn))
                    if revision == "0001_aggregates":
                        op.create_index("records_scope_kind", "records", ["scope", "kind"])
                    _create_formal_release_claims(op)
                    _verify_integrity(conn)
                    conn.execute(text("UPDATE alembic_version SET version_num=:revision"), {"revision": CURRENT_REVISION})
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            elif revision != CURRENT_REVISION:
                raise RuntimeError("Unsupported database migration version")
            conn.commit()

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield Repository(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @contextmanager
    def read(self):
        with self.engine.connect() as conn:
            yield Repository(conn)


class Repository:
    def __init__(self, conn):
        self.conn = conn

    def get(self, ident: str, kind: str | None = None):
        row = self.conn.execute(text("SELECT kind, body FROM records WHERE id=:id"), {"id": ident}).first()
        if not row or (kind and row[0] != kind):
            raise KeyError(ident)
        return json.loads(row[1])

    def list(self, kind: str, scope: str | None = None):
        sql = "SELECT body FROM records WHERE kind=:kind"
        args = {"kind": kind}
        if scope is not None:
            sql += " AND scope=:scope"
            args["scope"] = scope
        sql += " ORDER BY rowid"
        return [json.loads(r[0]) for r in self.conn.execute(text(sql), args)]

    def put(self, kind: str, data: dict, scope: str = ""):
        self.conn.execute(text("INSERT INTO records(id,kind,scope,body) VALUES(:id,:kind,:scope,:body) ON CONFLICT(id) DO UPDATE SET body=excluded.body"), {"id": data["id"], "kind": kind, "scope": scope, "body": json.dumps(data, ensure_ascii=False)})
        return data

    def delete(self, ident: str):
        self.conn.execute(text("DELETE FROM records WHERE id=:id"), {"id": ident})
