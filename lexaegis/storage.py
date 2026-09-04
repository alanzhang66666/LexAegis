"""Small JSON aggregate store, with SQLAlchemy and versioned SQL migrations.

Write transactions serialize business transitions; no network calls inside them.
"""
import json
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 20})
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
            context = MigrationContext.configure(conn)
            context._ensure_version_table()
            if context.get_current_revision() is None:
                op = Operations(context)
                op.create_table("records", sa.Column("id", sa.String, primary_key=True), sa.Column("kind", sa.String, nullable=False), sa.Column("scope", sa.String, nullable=False), sa.Column("body", sa.Text, nullable=False))
                op.create_index("records_kind_scope", "records", ["kind", "scope"])
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001_aggregates')"))
            elif context.get_current_revision() != "0001_aggregates":
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
