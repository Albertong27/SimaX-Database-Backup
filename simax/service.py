import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .adapters import NativeAdapter, mysql_release
from .db import Store, identifier, now
from .models import Settings
from .schedules import latest_due
from .events import EventManager
from .operations import available, protection_report, retention_plan


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def acquire_runtime_lock(directory):
    lock = (directory / "runtime.lock").open("a+b")
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return lock


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
        self.events = EventManager(self)
        self.artifact_lock = threading.RLock()
        try:
            self.store.get("settings", "general")
        except LookupError:
            self.store.put("settings", {"id": "general", **Settings().model_dump()})

    def start(self):
        # A real OS lock prevents two workers from owning this catalog, including after crashes.
        self.lock = acquire_runtime_lock(self.directory)
        for run in self.store.all("runs"):
            if run["status"] == "running":
                run.update(status="interrupted", finished=now(),
                           error="Runtime stopped during execution. Inspect any restore target before retrying.")
                self.store.put("runs", run)
                self.store.audit("Run interrupted", run["id"], "Interrupted")
        self.thread = threading.Thread(target=self.loop, name="simax-worker", daemon=True)
        self.thread.start()
        self.events.start()

    def close(self):
        self.stop.set()
        self.events.close()
        if self.thread:
            self.thread.join(timeout=5)
        # Keep the lock if a native operation is still finishing; process exit releases it.
        if self.lock and not (self.thread and self.thread.is_alive()) and not (self.events.thread and self.events.thread.is_alive()):
            self.lock.close()

    def save_source(self, body, key=None):
        with self.artifact_lock:
            return self._save_source(body, key)

    def _save_source(self, body, key=None):
        previous = self.store.get("sources", key) if key else {}
        body = dict(body)
        if body.get("password") is None:
            body["password"] = previous.get("password")
        if body["password"] is None:
            raise ValueError("Enter a database password before saving this connection.")
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
            current = self.store.decode(db.execute("SELECT body FROM sources WHERE id=?", (key,)).fetchone()[0])
            if current["revision"] != source["revision"]:
                raise ValueError("Connection changed during preflight. Run the check again.")
            current["preflight"] = result
            self.store.put("sources", current, db)
            self.store.audit("Connection checked", source["name"], "Ready" if result["ok"] else "Needs attention", db)
        return result

    def save_policy(self, body, key=None):
        with self.artifact_lock:
            return self._save_policy(body, key)

    def _save_policy(self, body, key=None):
        source = self.store.get("sources", body["source_id"])
        if source["role"] != "source" or source["engine"] not in self.adapter.tools:
            raise ValueError("Choose a PostgreSQL or MySQL source connection.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM policies WHERE id=?", (key,)).fetchone() if key else None
            if key and row is None:
                raise LookupError("Policy not found")
            previous = self.store.decode(row[0]) if row else {}
            body = dict(body)
            for field in ("event_secret", "mqtt_password"):
                if body.get(field) is None:
                    body[field] = previous.get(field, "")
            if body["trigger"] in {"webhook", "mqtt"} and len(body["event_secret"].encode()) < 32:
                raise ValueError("Enter an event signing secret of at least 32 bytes.")
            if not body.get("mqtt_username"):
                body["mqtt_password"] = ""
            elif not body["mqtt_password"]:
                raise ValueError("Enter a broker password when using an MQTT username.")
            result = {**body, "id": key or identifier("pol"),
                      "revision": previous.get("revision", 0) + 1,
                      "created": previous.get("created", now()), "updated": now(),
                      "format": "single-sql", "scope": "whole-database"}
            self.store.put("policies", result, db)
            self.store.audit("Policy saved", result["name"] + f" r{result['revision']}", db=db)
        return result

    def enqueue(self, policy_id, origin="Manual", occurrence=None, expected_revision=None, scheduled_for=None, db=None, trigger_event=None):
        owns_transaction = db is None
        with (self.store.connect() if owns_transaction else nullcontext(db)) as db:
            if owns_transaction:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM policies WHERE id=?", (policy_id,)).fetchone()
            if not row:
                raise LookupError("Policy not found")
            policy = self.store.decode(row[0])
            if expected_revision is not None and policy["revision"] != expected_revision:
                return None
            source = self.store.decode(db.execute("SELECT body FROM sources WHERE id=?", (policy["source_id"],)).fetchone()[0])
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
                active = self.store.decode(row[0])
                if active.get("source", {}).get("id") == source["id"] and active["kind"] == "backup":
                    if occurrence:
                        self.store.audit("Schedule coalesced into active backup", active["id"], db=db)
                        return active
                    raise ValueError("A backup for this source is already queued or running.")
            run = {"id": identifier("run"), "kind": "backup", "status": "queued",
                   "stage": "Queued", "created": now(), "origin": origin,
                   "policy": policy, "source": source, "events": [], "error": None}
            if scheduled_for:
                run["scheduled_for"] = scheduled_for
            if trigger_event:
                run["trigger_event"] = trigger_event
            self.store.put("runs", run, db)
            self.store.audit("Backup queued", run["id"], db=db)
        return run

    def schedule(self, instant=None):
        instant = instant or datetime.now(timezone.utc)
        for policy in self.store.all("policies"):
            if not policy["enabled"] or policy["trigger"] not in {"daily", "weekly", "cron"}:
                continue
            due = latest_due(policy, instant)
            if due and due >= datetime.fromisoformat(policy["updated"]):
                # Preserve legacy daily identities when upgrading an existing catalog.
                identity = (str(due.astimezone(ZoneInfo(policy["timezone"])).date())
                            if policy["trigger"] in {"daily", "weekly"} else due.isoformat())
                self.enqueue(policy["id"], "Schedule", f"{policy['id']}:{identity}",
                             expected_revision=policy["revision"], scheduled_for=due.isoformat())

    def stage(self, run, stage):
        run["stage"] = stage
        run["events"].append({"time": now(), "stage": stage})
        self.store.put("runs", run)

    def execute(self, run):
        started = time.monotonic()
        queue_seconds = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(run["created"])).total_seconds())
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
        run["duration_seconds"] = round(time.monotonic() - started, 3)
        if run["kind"] == "restore":
            target_seconds = run.get("recovery_target_seconds", 900)
            elapsed = queue_seconds + run["duration_seconds"]
            run["recovery"] = {"queue_seconds": round(queue_seconds, 3),
                               "execution_seconds": run["duration_seconds"],
                               "total_seconds": round(elapsed, 3), "target_seconds": target_seconds,
                               "within_target": run["status"] == "succeeded" and elapsed <= target_seconds,
                               "scope": "Accepted job through technical restore and table inventory. Excludes incident detection, preview, provisioning, application checks and cutover. Production downtime target remains unverified."}
            if run["status"] == "succeeded":
                with self.artifact_lock:
                    artifact = self.store.get("artifacts", run["artifact_id"])
                    artifact["restore_test"]["recovery"] = run["recovery"]
                    self.store.put("artifacts", artifact)
        self.store.put("runs", run)
        self.store.audit("Backup finished" if run["kind"] == "backup" else "Restore finished", run["id"], run["status"])
        if run["kind"] == "backup" and run["status"] == "succeeded":
            try:
                self.prune_after_backup(run)
            except Exception:
                # A retention failure must not turn a finalized backup into a failed export.
                run["retention_error"] = "Retention cleanup failed. Existing recovery points were not all expired; inspect storage."
                self.store.put("runs", run)
                self.store.audit("Retention needs attention", run["id"], "Failed")

    def backup(self, run):
        self.stage(run, "Preflight")
        minimum = self.store.get("settings", "general").get("minimum_free_gib", 2) * 1024**3
        if shutil.disk_usage(self.backups).free < minimum:
            raise ValueError("Backup stopped: free space is below the configured safety reserve. Free space without deleting incident evidence.")
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
                    "policy_id": run["policy"]["id"], "lifecycle": "available",
                    "limitations": "Database-local logical SQL. PostgreSQL owners/grants and cluster objects are excluded. MySQL definers may require matching target accounts. Quiesce schema changes during export; inspect source routines before restoring."}
        with (folder / "manifest.json.partial").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        (folder / "manifest.json.partial").rename(folder / "manifest.json")
        manifest["relative_path"] = final.relative_to(self.backups).as_posix()
        self.store.put("artifacts", manifest)
        run["artifact_id"] = manifest["id"]
        self.stage(run, "Finalized and integrity checked")

    def artifact_path(self, artifact):
        if not available(artifact):
            raise ValueError("This recovery point has expired or is being removed by retention.")
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
        if target["engine"] == "mysql":
            original, restored = mysql_release(artifact["server_version"]), mysql_release(info["version"])
            if original[:2] != restored[:2] or restored < original:
                raise ValueError("MySQL restore requires the same release series (for example 8.0) and a target patch no older than the source.")
        self.adapter.ensure_empty(target)
        return info

    def preview_restore(self, artifact_id, target_id):
        with self.artifact_lock:
            return self._preview_restore(artifact_id, target_id)

    def _preview_restore(self, artifact_id, target_id):
        artifact = self.store.get("artifacts", artifact_id)
        target = self.store.get("sources", target_id)
        self.check_restore(artifact, target)
        confirmation = {"id": identifier("confirm"), "artifact_id": artifact_id,
                        "recovery_target_seconds": self.store.get("settings", "general").get("recovery_target_minutes", 15) * 60,
                        "target": target, "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
        self.store.put("confirmations", confirmation)
        self.store.audit("Restore preview checked", f"{artifact_id} → {target['name']}")
        return {"token": confirmation["id"], "expires": confirmation["expires"],
                "target": target["name"], "tables": artifact["tables"],
                "checks": ["Artifact SHA-256 and size match", "Engine major versions match",
                           "Target is empty and labeled disposable"],
                "warning": "SQL routines and triggers can execute code. No concurrent target writers are allowed. Validation compares table names only; data and application behavior still require operator verification."}

    def confirm_restore(self, token, target_name, acknowledge_code):
        with self.artifact_lock:
            return self._confirm_restore(token, target_name, acknowledge_code)

    def _confirm_restore(self, token, target_name, acknowledge_code):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM confirmations WHERE id=?", (token,)).fetchone()
            if not row:
                raise ValueError("Preview is missing or already used. Run the checks again.")
            confirmation = self.store.decode(row[0])
            if datetime.fromisoformat(confirmation["expires"]) < datetime.now(timezone.utc):
                raise ValueError("Preview expired. Run the checks again.")
            if not acknowledge_code or target_name != confirmation["target"]["name"]:
                raise ValueError("Type the exact target name and acknowledge the SQL execution notice.")
            if not available(self.store.get("artifacts", confirmation["artifact_id"])):
                raise ValueError("This recovery point is no longer available.")
            run = {"id": identifier("run"), "kind": "restore", "status": "queued", "stage": "Queued",
                   "created": now(), "origin": "Manual restore", "target": confirmation["target"],
                   "source": confirmation["target"], "artifact_id": confirmation["artifact_id"],
                   "recovery_target_seconds": confirmation.get("recovery_target_seconds", 900),
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
        with self.artifact_lock:
            artifact = self.store.get("artifacts", artifact["id"])
            artifact["restore_test"] = {"run_id": run["id"], "time": now(), "target": target["name"],
                                        "level": "Table inventory only; data and behavior not verified"}
            self.store.put("artifacts", artifact)
        self.stage(run, "SQL replay and table inventory checked")

    def retention_preview(self, policy_id):
        policy = self.store.get("policies", policy_id)
        source = self.store.get("sources", policy["source_id"])
        candidates = retention_plan(policy, source, self.store.all("artifacts"), self.store.all("runs"),
                                    self.store.all("confirmations"))
        return {"policy_id": policy_id, "eligible": [{"id": a["id"], "snapshot": a["snapshot"], "bytes": a["bytes"]} for a in candidates],
                "message": "Eligibility only. Cleanup runs after a new successful backup of the unchanged policy/source; pins, active restores and incident holds are preserved."}

    def pin_artifact(self, artifact_id, pinned):
        with self.artifact_lock:
            artifact = self.store.get("artifacts", artifact_id)
            if not available(artifact):
                raise ValueError("An expired or partially removed artifact cannot be pinned.")
            artifact["pinned"] = pinned
            with self.store.connect() as db:
                self.store.put("artifacts", artifact, db)
                self.store.audit("Artifact pinned" if pinned else "Artifact unpinned", artifact_id, db=db)
            return artifact

    def prune_after_backup(self, run):
        with self.artifact_lock:
            policy = self.store.get("policies", run["policy"]["id"])
            source = self.store.get("sources", policy["source_id"])
            if (run["status"] != "succeeded" or policy["revision"] != run["policy"]["revision"]
                    or source["revision"] != run["source"]["revision"] or not policy.get("retention_enabled")
                    or policy.get("retention_hold") or not policy["enabled"]):
                return
            # A missing/corrupt newest copy cannot authorize expiry of historical copies.
            self.artifact_path(self.store.get("artifacts", run["artifact_id"]))
            candidates = retention_plan(policy, source, self.store.all("artifacts"), self.store.all("runs"),
                                        self.store.all("confirmations"))
            for artifact in candidates:
                self.expire_artifact(artifact)

    def expire_artifact(self, artifact):
        """Delete only two owned files, with a durable tombstone before filesystem work."""
        root = self.backups.resolve()
        path = self.backups / artifact["relative_path"]
        folder = path.parent
        # Refuse aliases/junctions, unexpected layout and foreign files. Never recurse.
        if (path.name != "backup.sql" or folder.name != artifact["run_id"]
                or not path.resolve().is_relative_to(root) or folder.parent.parent.resolve() != root):
            raise ValueError("Retention path failed ownership checks.")
        for part in (self.backups, folder.parent, folder, path, folder / "manifest.json"):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise ValueError("Retention refuses linked paths.")
        if folder.exists() and any(p.name not in {"backup.sql", "manifest.json"} for p in folder.iterdir()):
            raise ValueError("Retention refuses a directory containing unexpected files.")
        artifact["lifecycle"] = "deleting"
        self.store.put("artifacts", artifact)
        try:
            path.unlink(missing_ok=True)
            (folder / "manifest.json").unlink(missing_ok=True)
            if folder.exists():
                folder.rmdir()
        except OSError:
            artifact["retention_error"] = "File cleanup incomplete; inspect storage. Retry follows the next successful backup."
            self.store.put("artifacts", artifact)
            raise
        artifact.update(lifecycle="expired", expired=now())
        artifact.pop("retention_error", None)
        with self.store.connect() as db:
            self.store.put("artifacts", artifact, db)
            self.store.audit("Artifact expired by retention", artifact["id"], db=db)

    def protection(self):
        artifacts, runs = self.store.all("artifacts"), self.store.all("runs")
        report = protection_report(self.store.all("policies"), self.store.all("sources"), artifacts, runs)
        report["free_bytes"] = shutil.disk_usage(self.backups).free
        report["minimum_free_bytes"] = self.store.get("settings", "general").get("minimum_free_gib", 2) * 1024**3
        report["storage_ok"] = report["free_bytes"] >= report["minimum_free_bytes"]
        lookup = {a["id"]: a for a in artifacts}
        for row in report["policies"]:
            artifact = lookup.get(row["latest_artifact_id"])
            if artifact:
                path = (self.backups / artifact["relative_path"]).resolve()
                if not path.is_relative_to(self.backups.resolve()) or not path.is_file() or path.stat().st_size != artifact["bytes"]:
                    row["status"] = "attention"
                    row["reasons"].append("Latest recovery file is missing or its size changed. Checksums are revalidated before restore.")
            attempts = sorted([r for r in runs if r.get("policy", {}).get("id") == row["policy_id"]
                               and r["status"] == "succeeded"], key=lambda r: r["created"], reverse=True)
            if attempts and attempts[0].get("retention_error"):
                row["reasons"].append("A retention attempt failed; inspect the run history.")
                row["status"] = "attention"
        report["ok"] = report["ok"] and report["storage_ok"] and all(r["status"] == "current" for r in report["policies"])
        return report

    def cancel(self, key):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM runs WHERE id=?", (key,)).fetchone()
            if not row:
                raise LookupError("Run not found")
            run = self.store.decode(row[0])
            if run["status"] != "queued":
                raise ValueError("Only queued runs can be cancelled in this preview.")
            run.update(status="cancelled", finished=now())
            self.store.put("runs", run, db)
            self.store.audit("Queued run cancelled", key, db=db)
        return run

    def tick(self):
        self.schedule()
        self.events.dispatch()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM runs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return
            run = self.store.decode(row[0])
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
