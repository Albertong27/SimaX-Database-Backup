import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identifier(prefix):
    return f"{prefix}_{uuid4().hex[:16]}"


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "simax.sqlite3"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("This catalog belongs to a newer schema version. Use a compatible SimaX release.")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policies (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    source_id TEXT NOT NULL REFERENCES sources(id), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS occurrences (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS confirmations (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def table(table):
        if table not in {"sources", "policies", "runs", "artifacts", "audit", "settings", "confirmations"}:
            raise ValueError("Unknown collection")
        return table

    def all(self, table):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                f"SELECT body FROM {self.table(table)} ORDER BY rowid DESC"
            )]

    def get(self, table, key):
        with self.connect() as db:
            row = db.execute(f"SELECT body FROM {self.table(table)} WHERE id=?", (key,)).fetchone()
        if not row:
            raise LookupError("Record not found")
        return json.loads(row[0])

    def put(self, table, body, db=None):
        table = self.table(table)
        fields = {"id": body["id"], "body": json.dumps(body)}
        if table in {"sources", "policies"}:
            fields["name"] = body["name"]
        if table == "policies":
            fields["source_id"] = body["source_id"]
        if table == "runs":
            fields["status"] = body["status"]
        columns = ",".join(fields)
        updates = ",".join(f"{key}=excluded.{key}" for key in fields if key != "id")
        query = (f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in fields)}) "
                 f"ON CONFLICT(id) DO UPDATE SET {updates}")
        if db is not None:
            db.execute(query, tuple(fields.values()))
        else:
            with self.connect() as connection:
                connection.execute(query, tuple(fields.values()))
        return body

    def audit(self, action, scope, result="Done", db=None):
        return self.put("audit", {"id": identifier("audit"), "time": now(),
                        "actor": "Local operator", "action": action,
                        "scope": scope, "result": result}, db=db)
