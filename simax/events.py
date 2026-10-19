"""Durable event intake, bounded coalescing, and best-effort change observation."""

import hashlib
import hmac
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .db import now
from .observation import fingerprint


EVENT_TRIGGERS = {"table-change", "database-change", "webhook", "mqtt"}
CHANGE_TRIGGERS = {"table-change", "database-change"}


class EventRejected(ValueError):
    pass


class IntakeUnavailable(Exception):
    pass


def verify_signature(policy, timestamp, signature, payload, instant=None):
    secret = os.environ.get(policy["event_secret_env"], "")
    if len(secret.encode()) < 32:
        raise EventRejected("Set the policy's event secret to at least 32 bytes and restart SimaX.")
    if abs((instant if instant is not None else time.time()) - timestamp) > 300:
        raise EventRejected("Event timestamp is outside the five-minute acceptance window.")
    message = policy["id"].encode() + b"\n" + str(timestamp).encode() + b"\n" + payload
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise EventRejected("Event authentication failed.")


class EventManager:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.thread = None
        self.mqtt = None

    def state(self, policy, db):
        row = db.execute("SELECT body FROM trigger_state WHERE id=?", (policy["id"],)).fetchone()
        state = json.loads(row[0]) if row else {}
        if state.get("revision") != policy["revision"]:
            state = {"id": policy["id"], "revision": policy["revision"], "status": "waiting",
                     "message": "Waiting for the first observation or authenticated event.", "pending": None}
        return state

    def current(self, policy, db):
        row = db.execute("SELECT body FROM policies WHERE id=?", (policy["id"],)).fetchone()
        current = json.loads(row[0]) if row else {}
        return current.get("enabled") and current.get("revision") == policy["revision"]

    def health(self, policy, status, message):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.current(policy, db):
                return
            state = self.state(policy, db)
            if (state.get("status"), state.get("message")) != (status, message):
                self.store.audit("Trigger status changed", policy["id"], status, db)
            state.update(status=status, message=message, checked=now())
            self.store.put("trigger_state", state, db)

    def _pending(self, policy, state, instant, event_id):
        pending = state.get("pending")
        if not pending:
            pending = {"first": instant, "count": 0}
        pending.update(last=instant, count=min(pending["count"] + 1, 1000000), event_id=event_id)
        state.update(pending=pending, last_received=instant)

    def receive(self, policy, event_id, origin, instant=None):
        instant = instant if instant is not None else time.time()
        if policy["trigger"] != origin or origin not in {"webhook", "mqtt"}:
            raise EventRejected("This policy does not accept that event type.")
        receipt = hashlib.sha256(f"{policy['id']}:{event_id}".encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.current(policy, db):
                raise EventRejected("Policy is paused or changed. Use its current configuration.")
            db.execute("DELETE FROM trigger_receipts WHERE received < ?", (instant - 7 * 86400,))
            if db.execute("SELECT 1 FROM trigger_receipts WHERE id=?", (receipt,)).fetchone():
                return {"status": "duplicate"}
            # Bound catalog growth during authenticated event floods; retry later with the same ID.
            if db.execute("SELECT COUNT(*) FROM trigger_receipts").fetchone()[0] >= 100000:
                raise IntakeUnavailable("Event receipt capacity reached. Retry after old receipts expire.")
            db.execute("INSERT INTO trigger_receipts VALUES (?,?)", (receipt, instant))
            state = self.state(policy, db)
            first_pending = not state.get("pending")
            self._pending(policy, state, instant, event_id)
            state.update(status="ready", message="Authenticated event persisted; backup is pending or coalesced.", checked=now())
            self.store.put("trigger_state", state, db)
            if first_pending:
                self.store.audit("Trigger event accepted", policy["id"], origin, db)
        return {"status": "accepted", "policy_id": policy["id"]}

    def dispatch(self, instant=None):
        instant = instant if instant is not None else time.time()
        for policy in self.store.all("policies"):
            if not policy["enabled"] or policy["trigger"] not in EVENT_TRIGGERS:
                continue
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if not self.current(policy, db):
                    continue
                state = self.state(policy, db)
                pending = state.get("pending")
                if policy["trigger"] in CHANGE_TRIGGERS and pending:
                    source = json.loads(db.execute("SELECT body FROM sources WHERE id=?", (policy["source_id"],)).fetchone()[0])
                    if source["revision"] != state.get("source_revision"):
                        state.update(pending=None, status="waiting", message="Source changed; a new observation baseline is required.", last_poll=0)
                        self.store.put("trigger_state", state, db)
                        continue
                if not pending or instant < max(pending["first"] + policy["debounce_seconds"], state.get("last_dispatch", 0) + policy["cooldown_seconds"]):
                    continue
                active = [json.loads(row[0]) for row in db.execute("SELECT body FROM runs WHERE status IN ('queued','running')")]
                if any(r["kind"] == "backup" and r["source"]["id"] == policy["source_id"] for r in active):
                    continue  # Keep a follow-up; the active snapshot may predate this event.
                run = self.service.enqueue(policy["id"], policy["trigger"], expected_revision=policy["revision"],
                                           db=db, trigger_event=pending)
                if run:
                    state.update(pending=None, last_dispatch=instant, last_run=run["id"],
                                 message="Event request queued as a backup. See its run for completion evidence.")
                    self.store.put("trigger_state", state, db)

    def observe(self, policy, instant=None):
        explicit_instant = instant
        source = self.store.get("sources", policy["source_id"])
        try:
            selected = policy["change_tables"] if policy["trigger"] == "table-change" else []
            value = fingerprint(self.service.adapter, source, selected, self.service.directory, self.service.stop.is_set)
            instant = explicit_instant if explicit_instant is not None else time.time()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if not self.current(policy, db):
                    return
                current_source = json.loads(db.execute("SELECT body FROM sources WHERE id=?", (source["id"],)).fetchone()[0])
                if current_source["revision"] != source["revision"]:
                    return
                state = self.state(policy, db)
                baseline = state.get("fingerprint") if state.get("source_revision") == source["revision"] else None
                if baseline is None:
                    state["pending"] = None
                if baseline is not None and baseline != value:
                    first_pending = not state.get("pending")
                    self._pending(policy, state, instant, "change:" + value)
                    if first_pending:
                        self.store.audit("Observed table state changed", policy["id"], db=db)
                    state["last_change"] = instant
                state.update(fingerprint=value, source_revision=source["revision"], last_poll=instant,
                             status="observing", checked=now(),
                             message="Read-only polling active; transient changes between polls are not captured." if baseline else "Baseline recorded; the next observed change can request a backup. Polling is not continuous coverage.")
                self.store.put("trigger_state", state, db)
        except Exception:
            instant = explicit_instant if explicit_instant is not None else time.time()
            self.health(policy, "degraded", "Change scan failed. Check table selection, SELECT privileges, native tools and scan cost. Observation coverage has a gap.")
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if self.current(policy, db):
                    state = self.state(policy, db)
                    state["last_poll"] = instant
                    self.store.put("trigger_state", state, db)

    def start(self):
        from .mqtt import MqttManager
        self.mqtt = MqttManager(self)
        for policy in self.store.all("policies"):
            if policy["enabled"] and policy["trigger"] in EVENT_TRIGGERS:
                self.health(policy, "waiting", "Runtime restarted; observation continuity is not guaranteed. Persisted pending events are retained.")
        self.thread = threading.Thread(target=self.loop, name="simax-events", daemon=True)
        self.thread.start()

    def loop(self):
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="simax-change")
        polls = {}
        try:
            while not self.service.stop.is_set():
                try:
                    policies = self.store.all("policies")
                    self.mqtt.reconcile(policies)
                    polls = {key: future for key, future in polls.items() if not future.done()}
                    for policy in policies:
                        if self.service.stop.is_set():
                            break
                        if policy["enabled"] and policy["trigger"] in CHANGE_TRIGGERS:
                            with self.store.connect() as db:
                                state = self.state(policy, db)
                            if len(polls) < 2 and policy["id"] not in polls and time.time() >= state.get("last_poll", 0) + policy["poll_seconds"]:
                                polls[policy["id"]] = pool.submit(self.observe, policy)
                        elif policy["enabled"] and policy["trigger"] == "webhook":
                            if len(os.environ.get(policy["event_secret_env"], "").encode()) < 32:
                                self.health(policy, "degraded", "Set an event secret of at least 32 bytes and restart SimaX.")
                            else:
                                with self.store.connect() as db:
                                    state = self.state(policy, db)
                                if state["status"] != "ready":
                                    self.health(policy, "ready", "Signing key configured; waiting for authenticated webhook events.")
                except Exception:
                    # A bad observer must not stop backup execution or other intake paths.
                    for policy in self.store.all("policies"):
                        if policy["enabled"] and policy["trigger"] in EVENT_TRIGGERS:
                            self.health(policy, "degraded", "Event observer unavailable. Check configuration and available storage.")
                self.service.stop.wait(2)
        finally:
            self.mqtt.close()
            pool.shutdown(wait=True, cancel_futures=True)

    def close(self):
        if self.thread:
            self.thread.join(timeout=5)
