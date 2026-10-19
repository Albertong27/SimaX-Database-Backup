import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .adapters import NativeAdapter
from .db import Store, identifier, now
from .models import Settings


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Service:
    def __init__(self, directory, adapter=None):
        self.directory = Path(directory).resolve()
        self.store = Store(self.directory)
        self.backups = self.directory / "backups"
        self.backups.mkdir(exist_ok=True)
        self.adapter = adapter or NativeAdapter()
        self.stop = threading.Event()
        self.thread = None
        self.runtime_error = None
        self.lock = None
        try:
            self.store.get("settings", "general")
        except LookupError:
            self.store.put("settings", {"id": "general", **Settings().model_dump()})

    def start(self):
        # A real OS lock prevents two workers from owning this catalog, including after crashes.
        self.lock = (self.directory / "runtime.lock").open("a+b")
        self.lock.seek(0)
        if os.name == "nt":
            import msvcrt
            if self.lock.read(1) == b"":
                self.lock.write(b"0")
                self.lock.flush()
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for run in self.store.all("runs"):
            if run["status"] == "running":
                run.update(status="interrupted", finished=now(),
                           error="Runtime stopped during execution. Inspect any restore target before retrying.")
                self.store.put("runs", run)
                self.store.audit("Run interrupted", run["id"], "Interrupted")
        self.thread = threading.Thread(target=self.loop, name="simax-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        # Keep the lock if a native operation is still finishing; process exit releases it.
        if self.lock and not (self.thread and self.thread.is_alive()):
            self.lock.close()

    def save_source(self, body, key=None):
        previous = self.store.get("sources", key) if key else {}
        if key and any(p["source_id"] == key for p in self.store.all("policies")):
            if body["role"] != "source" or body["engine"] not in self.adapter.tools:
                raise ValueError("This connection is used by a backup policy. Keep it a supported backup source.")
        result = {**body, "id": key or identifier("src"),
                  "revision": previous.get("revision", 0) + 1,
                  "created": previous.get("created", now()), "preflight": None}
        with self.store.connect() as db:
            self.store.put("sources", result, db)
            self.store.audit("Connection saved", result["name"], db=db)
        return result

    def preflight(self, key):
        source = self.store.get("sources", key)
        try:
            details = self.adapter.inspect(source)
            result = {"ok": True, "checked": now(), **details,
                      "message": "Connection and tools checked. Export privileges are validated when a backup runs."}
        except ValueError as error:
            result = {"ok": False, "checked": now(), "message": str(error)}
        # Do not clobber a connection edited while its network check was in flight.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute("SELECT body FROM sources WHERE id=?", (key,)).fetchone()[0])
            if current["revision"] != source["revision"]:
                raise ValueError("Connection changed during preflight. Run the check again.")
            current["preflight"] = result
            self.store.put("sources", current, db)
            self.store.audit("Connection checked", source["name"], "Ready" if result["ok"] else "Needs attention", db)
        return result

    def save_policy(self, body, key=None):
        source = self.store.get("sources", body["source_id"])
        if source["role"] != "source" or source["engine"] not in self.adapter.tools:
            raise ValueError("Choose a PostgreSQL or MySQL source connection.")
        previous = self.store.get("policies", key) if key else {}
        result = {**body, "id": key or identifier("pol"),
                  "revision": previous.get("revision", 0) + 1,
                  "created": previous.get("created", now()), "updated": now(),
                  "format": "single-sql", "scope": "whole-database"}
        with self.store.connect() as db:
            self.store.put("policies", result, db)
            self.store.audit("Policy saved", result["name"] + f" r{result['revision']}", db=db)
        return result

    def enqueue(self, policy_id, origin="Manual", occurrence=None):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM policies WHERE id=?", (policy_id,)).fetchone()
            if not row:
                raise LookupError("Policy not found")
            policy = json.loads(row[0])
            source = json.loads(db.execute("SELECT body FROM sources WHERE id=?", (policy["source_id"],)).fetchone()[0])
            if not policy["enabled"]:
                raise ValueError("Enable this policy before starting a backup.")
            if source["role"] != "source" or source["engine"] not in self.adapter.tools:
                raise ValueError("This source cannot execute backups.")
            if occurrence:
                try:
                    db.execute("INSERT INTO occurrences VALUES (?,?)", (occurrence, now()))
                except sqlite3.IntegrityError:
                    return None
            for row in db.execute("SELECT body FROM runs WHERE status IN ('queued','running')"):
                active = json.loads(row[0])
                if active.get("source", {}).get("id") == source["id"] and active["kind"] == "backup":
                    if occurrence:
                        self.store.audit("Schedule coalesced into active backup", active["id"], db=db)
                        return active
                    raise ValueError("A backup for this source is already queued or running.")
            run = {"id": identifier("run"), "kind": "backup", "status": "queued",
                   "stage": "Queued", "created": now(), "origin": origin,
                   "policy": policy, "source": source, "events": [], "error": None}
            self.store.put("runs", run, db)
            self.store.audit("Backup queued", run["id"], db=db)
        return run

    def schedule(self, instant=None):
        instant = instant or datetime.now(timezone.utc)
        for policy in self.store.all("policies"):
            if not policy["enabled"] or policy["trigger"] != "daily":
                continue
            zone = ZoneInfo(policy["timezone"])
            local = instant.astimezone(zone)
            hour, minute = map(int, policy["time"].split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
            # Nonexistent DST wall times are skipped; a repeated time runs once, at fold 0.
            roundtrip = due.astimezone(timezone.utc).astimezone(zone)
            if roundtrip.replace(tzinfo=None) != due.replace(tzinfo=None):
                continue
            if due.astimezone(timezone.utc) <= instant and due >= datetime.fromisoformat(policy["updated"]):
                self.enqueue(policy["id"], "Schedule", f"{policy['id']}:{local.date()}")

    def stage(self, run, stage):
        run["stage"] = stage
        run["events"].append({"time": now(), "stage": stage})
        self.store.put("runs", run)

    def execute(self, run):
        run.update(status="running", started=now())
        self.store.put("runs", run)
        try:
            if run["kind"] == "backup":
                self.backup(run)
            else:
                self.restore(run)
            run.update(status="succeeded", finished=now())
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else "Operation failed. Check runtime file permissions, available storage and native tools. Inspect the target before retrying a restore."
            run.update(status="failed", error=message, finished=now())
        self.store.put("runs", run)
        self.store.audit("Backup finished" if run["kind"] == "backup" else "Restore finished", run["id"], run["status"])

    def backup(self, run):
        self.stage(run, "Preflight")
        info = self.adapter.inspect(run["source"])
        folder = self.backups / run["policy"]["destination"] / run["id"]
        folder.mkdir(parents=True, exist_ok=False)
        temporary = folder / "backup.sql.partial"
        final = folder / "backup.sql"
        self.stage(run, "Export")
        snapshot = now()  # Conservative lower bound; native snapshot occurs after invocation.
        self.adapter.export(run["source"], temporary)
        self.stage(run, "Verify local copy")
        checksum = digest(temporary)
        temporary.rename(final)
        manifest = {"format_version": 1, "id": identifier("art"), "run_id": run["id"],
                    "source_id": run["source"]["id"], "source_name": run["source"]["name"],
                    "engine": run["source"]["engine"], "server_version": info["version"],
                    "server_major": info["major"], "tool_version": info["tool_version"],
                    "snapshot": snapshot, "snapshot_precision": "export-start lower bound",
                    "created": now(), "format": "single-sql", "scope": "whole-database",
                    "tables": info["tables"], "bytes": final.stat().st_size,
                    "sha256": checksum, "file": "backup.sql", "integrity": "verified",
                    "restore_test": None, "pinned": False,
                    "policy_name": run["policy"]["name"], "policy_revision": run["policy"]["revision"],
                    "limitations": "Database-local logical SQL. PostgreSQL owners/grants and cluster objects are excluded. MySQL definers may require matching target accounts. Quiesce schema changes during export; inspect source routines before restoring."}
        with (folder / "manifest.json.partial").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        (folder / "manifest.json.partial").rename(folder / "manifest.json")
        manifest["relative_path"] = str(final.relative_to(self.backups))
        self.store.put("artifacts", manifest)
        run["artifact_id"] = manifest["id"]
        self.stage(run, "Finalized and integrity checked")

    def artifact_path(self, artifact):
        path = (self.backups / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.backups.resolve()) or not path.is_file():
            raise ValueError("Artifact is missing or outside the managed backup directory.")
        if path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
            raise ValueError("Artifact integrity check failed. Restore is blocked.")
        return path

    def check_restore(self, artifact, target):
        self.artifact_path(artifact)
        if target["role"] != "target" or target["environment"] != "DISPOSABLE":
            raise ValueError("This preview restores only to connections labeled DISPOSABLE and used as restore targets.")
        if target["engine"] != artifact["engine"]:
            raise ValueError("Cross-engine restore is not supported.")
        # Compare against the immutable source identity recorded by the original run.
        source = self.store.get("runs", artifact["run_id"])["source"]
        if all(source[k] == target[k] for k in ("host", "port", "database")):
            raise ValueError("Use a separate, disposable target database; the source cannot be overwritten.")
        info = self.adapter.inspect(target)
        if info["major"] != artifact["server_major"]:
            raise ValueError("This preview requires the same engine major version on the target.")
        self.adapter.ensure_empty(target)
        return info

    def preview_restore(self, artifact_id, target_id):
        artifact = self.store.get("artifacts", artifact_id)
        target = self.store.get("sources", target_id)
        self.check_restore(artifact, target)
        confirmation = {"id": identifier("confirm"), "artifact_id": artifact_id,
                        "target": target, "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
        self.store.put("confirmations", confirmation)
        self.store.audit("Restore preview checked", f"{artifact_id} → {target['name']}")
        return {"token": confirmation["id"], "expires": confirmation["expires"],
                "target": target["name"], "tables": artifact["tables"],
                "checks": ["Artifact SHA-256 and size match", "Engine major versions match",
                           "Target is empty and labeled disposable"],
                "warning": "SQL routines and triggers can execute code. No concurrent target writers are allowed. Validation compares table names only; data and application behavior still require operator verification."}

    def confirm_restore(self, token, target_name, acknowledge_code):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM confirmations WHERE id=?", (token,)).fetchone()
            if not row:
                raise ValueError("Preview is missing or already used. Run the checks again.")
            confirmation = json.loads(row[0])
            if datetime.fromisoformat(confirmation["expires"]) < datetime.now(timezone.utc):
                raise ValueError("Preview expired. Run the checks again.")
            if not acknowledge_code or target_name != confirmation["target"]["name"]:
                raise ValueError("Type the exact target name and acknowledge the SQL execution notice.")
            run = {"id": identifier("run"), "kind": "restore", "status": "queued", "stage": "Queued",
                   "created": now(), "origin": "Manual restore", "target": confirmation["target"],
                   "source": confirmation["target"], "artifact_id": confirmation["artifact_id"],
                   "events": [], "error": None}
            self.store.put("runs", run, db)
            db.execute("DELETE FROM confirmations WHERE id=?", (token,))
            self.store.audit("Restore authorized", run["id"], db=db)
        return run

    def restore(self, run):
        artifact = self.store.get("artifacts", run["artifact_id"])
        target = self.store.get("sources", run["target"]["id"])
        if target["revision"] != run["target"]["revision"]:
            raise ValueError("Target connection changed after preview. Create a new restore preview.")
        self.stage(run, "Revalidate artifact and target")
        self.check_restore(artifact, target)
        self.stage(run, "Replay SQL")
        self.adapter.restore(target, self.artifact_path(artifact))
        self.stage(run, "Compare table inventory")
        result = self.adapter.inspect(target)
        if sorted(result["tables"]) != sorted(artifact["tables"]):
            raise ValueError("SQL replay finished but table inventory differs. Inspect the target; full recovery is not verified.")
        artifact["restore_test"] = {"run_id": run["id"], "time": now(), "target": target["name"],
                                    "level": "Table inventory only; data and behavior not verified"}
        self.store.put("artifacts", artifact)
        self.stage(run, "SQL replay and table inventory checked")

    def cancel(self, key):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM runs WHERE id=?", (key,)).fetchone()
            if not row:
                raise LookupError("Run not found")
            run = json.loads(row[0])
            if run["status"] != "queued":
                raise ValueError("Only queued runs can be cancelled in this preview.")
            run.update(status="cancelled", finished=now())
            self.store.put("runs", run, db)
            self.store.audit("Queued run cancelled", key, db=db)
        return run

    def tick(self):
        self.schedule()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM runs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return
            run = json.loads(row[0])
            run["status"] = "running"
            self.store.put("runs", run, db)
        self.execute(run)

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
                self.runtime_error = None
            except Exception:
                self.runtime_error = "Scheduler paused by an internal error. Check configuration and available disk space."
            self.stop.wait(2)
