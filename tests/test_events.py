import hashlib
import hmac
import json
import time

import pytest

from simax.events import EventRejected
from simax.models import Policy
from simax.service import Service
from test_app import FixtureAdapter, make_policy, setup  # noqa: F401


SECRET = "isolated-test-key-" * 3


def event_policy(client, service, trigger="webhook", **changes):
    src, original = make_policy(client)
    body = Policy(name=original["name"], source_id=src["id"], trigger=trigger,
                  acknowledge_scan=True, change_tables=["public.orders"],
                  debounce_seconds=10, cooldown_seconds=60, event_secret=SECRET, **changes).model_dump()
    return service.save_policy(body, original["id"])


def signed(policy, payload, timestamp=None, secret=SECRET):
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(secret.encode(), policy["id"].encode() + b"\n" + str(timestamp).encode() + b"\n" + payload, hashlib.sha256).hexdigest()
    return {"X-SimaX-Timestamp": str(timestamp), "X-SimaX-Signature": signature}


def webhook(client, policy, event_id="fixture-1", **kwargs):
    body = json.dumps({"event_id": event_id}).encode()
    return client.post(f"/api/triggers/webhook/{policy['id']}", content=body, headers=signed(policy, body, **kwargs))


def test_webhook_auth_schema_replay_and_scope(setup, monkeypatch):
    client, service, _ = setup
    monkeypatch.setenv("SIMAX_SECRET_EVENTS", SECRET)
    policy = event_policy(client, service)
    assert webhook(client, policy, secret="wrong").status_code == 401
    assert webhook(client, policy, timestamp=int(time.time()) - 301).status_code == 401
    assert webhook(client, policy, timestamp=int(time.time()) + 301).status_code == 401
    body = b'{"event_id":"bad","sql":"DROP TABLE orders"}'
    assert client.post(f"/api/triggers/webhook/{policy['id']}", content=body, headers=signed(policy, body)).status_code == 422
    assert client.post(f"/api/triggers/webhook/{policy['id']}", content=b'x' * 4097).status_code == 413
    assert webhook(client, policy).status_code == 202
    assert webhook(client, policy).status_code == 409
    assert not service.store.all("runs")  # Accepted is pending, not completed.
    other = service.save_policy(Policy(name="other", source_id=policy["source_id"], trigger="webhook", event_secret=SECRET).model_dump())
    body = b'{"event_id":"another"}'
    assert client.post(f"/api/triggers/webhook/{other['id']}", content=body, headers=signed(policy, body)).status_code == 401
    assert SECRET not in client.get("/api/state").text


def test_durable_coalescing_cooldown_and_follow_up_after_active_snapshot(setup):
    client, service, _ = setup
    policy = event_policy(client, service)
    base = time.time()
    for i in range(50):
        service.events.receive(policy, f"burst-{i}", "webhook", base + i / 100)
    restarted = Service(service.directory, FixtureAdapter())
    restarted.events.dispatch(base + 9)
    assert not service.store.all("runs")
    restarted.events.dispatch(base + 10)
    run = service.store.all("runs")[0]
    assert run["trigger_event"]["count"] == 50
    assert run["origin"] == "webhook"
    service.events.receive(policy, "during-backup", "webhook", base + 11)
    restarted.events.dispatch(base + 100)
    assert len(service.store.all("runs")) == 1
    service.execute(run)
    restarted.events.dispatch(base + 30)
    assert len(service.store.all("runs")) == 1
    restarted.events.dispatch(base + 70)
    assert len(service.store.all("runs")) == 2
    assert restarted.events.receive(policy, "during-backup", "webhook", base + 71)["status"] == "duplicate"


def test_edit_pause_stale_delivery_and_receipt_retention(setup):
    client, service, _ = setup
    policy = event_policy(client, service)
    service.events.receive(policy, "before-edit", "webhook", 1000)
    body = {k: v for k, v in policy.items() if k in Policy.model_fields}
    body["enabled"] = False
    paused = service.save_policy(body, policy["id"])
    with pytest.raises(EventRejected):
        service.events.receive(policy, "stale", "webhook", 1001)
    with pytest.raises(EventRejected):
        service.events.receive(paused, "paused", "webhook", 1001)
    body["enabled"] = True
    enabled = service.save_policy(body, policy["id"])
    service.events.dispatch(1100)
    assert not service.store.all("runs")
    assert service.events.receive(enabled, "before-edit", "webhook", 1200)["status"] == "duplicate"
    assert service.events.receive(enabled, "before-edit", "webhook", 1000 + 7 * 86400 + 1)["status"] == "accepted"


def test_change_baseline_outage_restart_and_source_edit(setup, monkeypatch):
    client, service, _ = setup
    policy = event_policy(client, service, "table-change")
    value = ["first"]
    monkeypatch.setattr("simax.events.fingerprint", lambda *args: value[0])
    service.events.observe(policy, 1000)
    assert service.store.get("trigger_state", policy["id"])["pending"] is None
    service.events.observe(policy, 1100)
    assert not service.store.all("runs")
    restarted = Service(service.directory, FixtureAdapter())
    value[0] = "changed"
    restarted.events.observe(policy, 1200)
    state = service.store.get("trigger_state", policy["id"])
    assert state["pending"]["count"] == 1
    source = service.store.get("sources", policy["source_id"])
    source["revision"] += 1
    service.store.put("sources", source)
    restarted.events.dispatch(1300)
    assert not service.store.all("runs")
    restarted.events.observe(policy, 1400)
    assert service.store.get("trigger_state", policy["id"])["pending"] is None
    def failure(*args):
        raise RuntimeError("private query or credential")
    monkeypatch.setattr("simax.events.fingerprint", failure)
    restarted.events.observe(policy, 1500)
    state = service.store.get("trigger_state", policy["id"])
    assert state["status"] == "degraded"
    assert "private query" not in json.dumps(state)
    assert state["fingerprint"] == "changed"


def test_observation_edit_race_does_not_update_new_revision(setup, monkeypatch):
    client, service, _ = setup
    policy = event_policy(client, service, "database-change")
    def edited(*args):
        body = {k: v for k, v in policy.items() if k in Policy.model_fields}
        body["enabled"] = False
        service.save_policy(body, policy["id"])
        return "old-snapshot"
    monkeypatch.setattr("simax.events.fingerprint", edited)
    service.events.observe(policy)
    assert service.store.all("trigger_state") == []


@pytest.mark.parametrize("changes", [
    {"trigger": "table-change"}, {"trigger": "database-change"},
    {"trigger": "table-change", "acknowledge_scan": True, "change_tables": []},
    {"trigger": "mqtt", "mqtt_topic": "backup/#"},
    {"trigger": "mqtt", "mqtt_password": "bad\x00password"},
    {"cooldown_seconds": 0}, {"poll_seconds": 1}, {"event_secret_env": "PATH"},
])
def test_event_configuration_boundaries(changes):
    with pytest.raises(ValueError):
        Policy(name="bad", source_id="source", **changes)


def test_catalog_v1_upgrade_preserves_existing_records(tmp_path):
    from simax.db import Store
    store = Store(tmp_path)
    store.put("settings", {"id": "existing", "value": "preserved"})
    with store.connect() as db:
        db.execute("DROP TABLE trigger_state")
        db.execute("DROP TABLE trigger_receipts")
        db.execute("UPDATE settings SET body=? WHERE id=?", (json.dumps({"id": "existing", "value": "preserved"}), "existing"))
        db.execute("PRAGMA user_version=1")
    upgraded = Store(tmp_path)
    assert upgraded.get("settings", "existing")["value"] == "preserved"
    with upgraded.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM trigger_receipts").fetchone()[0] == 0


def test_failed_intake_rolls_back_receipt_and_can_be_retried(setup, monkeypatch):
    client, service, _ = setup
    policy = event_policy(client, service)
    put = service.store.put
    def fail_state(table, *args, **kwargs):
        if table == "trigger_state":
            raise RuntimeError("isolated storage failure")
        return put(table, *args, **kwargs)
    monkeypatch.setattr(service.store, "put", fail_state)
    with pytest.raises(RuntimeError):
        service.events.receive(policy, "retryable", "webhook")
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM trigger_receipts").fetchone()[0] == 0
    monkeypatch.setattr(service.store, "put", put)
    assert service.events.receive(policy, "retryable", "webhook")["status"] == "accepted"
