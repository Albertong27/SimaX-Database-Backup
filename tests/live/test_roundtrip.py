"""Opt-in real native tools; run with scripts/live_tests.py, never production endpoints."""

import hashlib
import json
import os
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from simax.adapters import AdapterError, NativeAdapter
from simax.app import create_app


ENGINE = os.environ.get("SIMAX_LIVE_ENGINE")
pytestmark = pytest.mark.skipif(ENGINE not in ("postgresql", "mysql"), reason="Use scripts/live_tests.py for isolated live databases")


def connection(role):
    return {"name": f"live-{role}", "engine": ENGINE, "host": "127.0.0.1",
            "port": int(os.environ[f"SIMAX_LIVE_{role.upper()}_PORT"]),
            "database": "simax_fixture", "username": "postgres" if ENGINE == "postgresql" else "root",
            "password": os.environ["SIMAX_SECRET_LIVE"], "tls": "disable",
            "role": role, "environment": "DISPOSABLE"}


def post(client, url, body=None):
    response = client.post(url, json=body)
    assert response.is_success, response.text
    result = response.json()
    if url == "/api/sources":
        assert "password" not in result
        # Direct SQL verification uses the internal decrypted record, never API secrets.
        return client.app.state.service.store.get("sources", result["id"])
    return result


def finished(client, run):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        current = next(row for row in client.get("/api/state").json()["runs"] if row["id"] == run["id"])
        if current["status"] not in ("queued", "running"):
            return current
        time.sleep(0.1)
    pytest.fail(f"Worker did not finish {run['id']}")


def rows(adapter, source, table):
    if ENGINE == "postgresql":
        sql = f"SELECT row_to_json(t)::text FROM (SELECT * FROM {table} ORDER BY 1) t"
    else:
        columns = {
            "orders": "'id', id, 'customer_id', customer_id, 'label', label, 'amount', amount, 'doubled', doubled, 'payload', HEX(payload), 'metadata', metadata, 'optional', optional, 'state', state, 'created', created",
            "customers": "'id', id, 'name', name", "audit": "'order_id', order_id, 'action', action",
            "order_summary": "'id', id, 'label', label, 'total', total",
            "`résumé`": "'名前', `名前`"}
        sql = f"SELECT JSON_OBJECT({columns[table]}) FROM {table} ORDER BY 1"
    return [json.loads(line) for line in adapter.query(source, sql).splitlines()]


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    adapter = NativeAdapter()
    source, target = connection("source"), connection("target")
    # Verify fixture isolation before writing any SQL.
    assert source["port"] != target["port"]
    adapter.ensure_empty(source)
    adapter.ensure_empty(target)
    adapter.restore(source, Path(__file__).with_name(ENGINE + ".sql"))
    print("\nLIVE MATRIX " + json.dumps(adapter.inspect(source), ensure_ascii=True))
    app = create_app(tmp_path_factory.mktemp("catalog"))
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-SimaX-Request": "1"}) as client:
        src = post(client, "/api/sources", source)
        dst = post(client, "/api/sources", target)
        assert post(client, f"/api/sources/{src['id']}/preflight")["ok"]
        policy = post(client, "/api/policies", {"name": "Live native export", "source_id": src["id"]})
        backup = finished(client, post(client, f"/api/policies/{policy['id']}/run"))
        assert backup["status"] == "succeeded", backup
        artifact = client.get("/api/state").json()["artifacts"][0]
        yield client, app.state.service, adapter, src, dst, artifact


def test_real_backup_restore_data_objects_and_behavior(live):
    client, service, adapter, src, dst, artifact = live
    prefix = "app." if ENGINE == "postgresql" else ""
    tables = [prefix + name for name in ("orders", "customers", "audit", "order_summary")]
    tables += ['public."résumé"'] if ENGINE == "postgresql" else ['`résumé`']
    if ENGINE == "postgresql":
        tables += ["app.order_count"]
    baseline = {name: rows(adapter, src, name) for name in tables}
    first = next(row for row in baseline[prefix + "orders"] if row["id"] == 1)
    assert first["label"] == "café 日本 🌏 quote' slash\\ tab\t line\nend"
    assert first["optional"] is None
    assert first["metadata"] == {"unicode": "日本", "nested": [1, True, None]}
    assert first["payload"].lower().removeprefix("\\x") == "0001ff005c27"
    path = service.artifact_path(artifact)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    disk_manifest = json.loads(path.with_name("manifest.json").read_text())
    assert disk_manifest["bytes"] == path.stat().st_size
    assert not list(path.parent.glob("*.partial"))
    preview = post(client, "/api/restore/preview", {"artifact_id": artifact["id"], "target_id": dst["id"]})
    restored = finished(client, post(client, "/api/restore/confirm", {
        "token": preview["token"], "target_name": dst["name"], "acknowledge_code": True}))
    assert restored["status"] == "succeeded", restored
    assert {name: rows(adapter, dst, name) for name in tables} == baseline
    # Execute restored identities, generated columns, routines, triggers, and constraints.
    adapter.query(dst, f"INSERT INTO {prefix}orders(customer_id,label,amount) VALUES (1,'after restore',7.50)")
    adapter.query(dst, f"CALL {prefix}mark_paid(3)")
    assert adapter.query(dst, f"SELECT {prefix}double_amount(7.50)") == "15.00"
    assert adapter.query(dst, f"SELECT COUNT(*) FROM {prefix}orders WHERE id=3 AND doubled=15 AND state='paid'") == "1"
    assert adapter.query(dst, f"SELECT COUNT(*) FROM {prefix}audit WHERE order_id=3 AND action='INSERT'") == "1"
    for sql in (
        f"INSERT INTO {prefix}orders(customer_id,label,amount) VALUES (999,'bad FK',1)",
        f"INSERT INTO {prefix}orders(customer_id,label,amount) VALUES (1,'bad check',-1)",
        f"INSERT INTO {prefix}customers VALUES (2,'SimaX Jakarta')",
    ):
        with pytest.raises(AdapterError):
            adapter.query(dst, sql)
    if ENGINE == "postgresql":
        assert adapter.query(dst, "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='app' AND indexname='orders_label'") == "1"
    else:
        assert adapter.query(dst, "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND INDEX_NAME='orders_label'") == "1"
        assert adapter.query(dst, "SELECT STATUS FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE() AND EVENT_NAME='dormant_event'") == "DISABLED"
    assert {name: rows(adapter, src, name) for name in tables} == baseline
    blocked = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]})
    assert blocked.status_code == 400 and "empty" in blocked.text
    print("Verified rows, Unicode, binary/JSON/null values, views, indexes, identities, constraints, routines, triggers and unchanged source.")


def test_corruption_and_bad_credentials_fail_closed(live, monkeypatch):
    client, service, adapter, src, dst, artifact = live
    path = service.artifact_path(artifact)
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n-- corruption\n")
        response = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]})
        assert response.status_code == 400 and "integrity" in response.text
    finally:
        path.write_bytes(original)
    monkeypatch.setenv("SIMAX_SECRET_WRONG", "deliberately-wrong-test-password")
    bad = post(client, "/api/sources", {**connection("source"), "name": "bad-password", "password": "deliberately-wrong-test-password"})
    policy = post(client, "/api/policies", {"name": "Must fail", "source_id": bad["id"]})
    run = finished(client, post(client, f"/api/policies/{policy['id']}/run"))
    assert run["status"] == "failed"
    state = client.get("/api/state")
    assert len(state.json()["artifacts"]) == 1
    assert "deliberately-wrong-test-password" not in state.text


def test_mysql_nontransactional_tables_rejected(live):
    if ENGINE != "mysql":
        pytest.skip("MySQL consistency guard")
    _, _, adapter, src, _, _ = live
    adapter.query(src, "CREATE TABLE nontransactional(id integer) ENGINE=MyISAM")
    try:
        with pytest.raises(AdapterError, match="InnoDB"):
            adapter.inspect(src)
    finally:
        adapter.query(src, "DROP TABLE nontransactional")


def test_execution_rechecks_a_target_changed_after_preview(live):
    client, _, adapter, _, dst, artifact = live
    adapter.query(dst, "CREATE DATABASE simax_race")
    target = post(client, "/api/sources", {**connection("target"), "name": "race-target", "database": "simax_race"})
    preview = post(client, "/api/restore/preview", {"artifact_id": artifact["id"], "target_id": target["id"]})
    adapter.query(target, "CREATE TABLE sentinel(id integer PRIMARY KEY)")
    adapter.query(target, "INSERT INTO sentinel VALUES (99)")
    run = finished(client, post(client, "/api/restore/confirm", {
        "token": preview["token"], "target_name": target["name"], "acknowledge_code": True}))
    assert run["status"] == "failed" and "empty" in run["error"]
    assert adapter.query(target, "SELECT id FROM sentinel") == "99"
    assert len(adapter.inspect(target)["tables"]) == 1


def test_native_replay_stops_on_sql_error(live, tmp_path):
    _, _, adapter, _, dst, _ = live
    adapter.query(dst, "CREATE DATABASE simax_failed_replay")
    target = {**dst, "database": "simax_failed_replay"}
    failing = tmp_path / "invalid.sql"
    failing.write_text("CREATE TABLE before_error(id integer);\nINSERT INTO missing_table VALUES (1);\nCREATE TABLE after_error(id integer);\n", encoding="utf-8")
    with pytest.raises(AdapterError):
        adapter.restore(target, failing)
    tables = adapter.inspect(target)["tables"]
    assert not any(name.endswith("after_error") for name in tables)
    if ENGINE == "postgresql":
        # PostgreSQL promises atomic replay; MySQL DDL may remain after an error.
        assert tables == []
    else:
        assert tables == ["before_error"]


def test_native_change_observation_and_triggered_backup(live, tmp_path):
    from simax.models import Policy, Source
    from simax.observation import fingerprint
    from simax.service import Service

    _, _, adapter, original, _, _ = live
    service = Service(tmp_path / "events", adapter)
    source = service.save_source(Source(**{k: v for k, v in original.items() if k in Source.model_fields}).model_dump())
    table = "public.simax_change_fixture" if ENGINE == "postgresql" else "simax_change_fixture"
    other = "public.simax_unwatched_fixture" if ENGINE == "postgresql" else "simax_unwatched_fixture"
    adapter.query(source, f"CREATE TABLE {table}(id INTEGER PRIMARY KEY, amount DECIMAL(10,2), value VARCHAR(80))")
    adapter.query(source, f"CREATE TABLE {other}(id INTEGER PRIMARY KEY)")
    try:
        policy = service.save_policy(Policy(name="Watch one table", source_id=source["id"], trigger="table-change",
                                            change_tables=[table], acknowledge_scan=True, debounce_seconds=0, cooldown_seconds=60).model_dump())
        service.events.observe(policy)
        baseline = service.store.get("trigger_state", policy["id"])["fingerprint"]
        adapter.query(source, f"INSERT INTO {other} VALUES(1)")
        assert fingerprint(adapter, source, [table], service.directory) == baseline
        adapter.query(source, f"INSERT INTO {table} VALUES(1,12.50,'café 日本')")
        inserted = fingerprint(adapter, source, [table], service.directory)
        assert inserted != baseline
        adapter.query(source, f"UPDATE {table} SET amount=12.51 WHERE id=1")
        updated = fingerprint(adapter, source, [table], service.directory)
        assert updated != inserted  # Fractional values must not be rounded by HEX(number).
        service.events.observe(policy)
        service.events.dispatch()
        run = service.store.all("runs")[0]
        assert run["origin"] == "table-change"
        service.execute(run)
        assert service.store.get("runs", run["id"])["status"] == "succeeded"
        assert service.store.all("artifacts")[0]["bytes"] > 0
        adapter.query(source, f"DELETE FROM {table} WHERE id=1")
        assert fingerprint(adapter, source, [table], service.directory) == baseline
        adapter.query(source, f"ALTER TABLE {table} ADD COLUMN added INTEGER")
        assert fingerprint(adapter, source, [table], service.directory) != baseline
        database_before = fingerprint(adapter, source, [], service.directory)
        adapter.query(source, f"DROP TABLE {other}")
        assert fingerprint(adapter, source, [], service.directory) != database_before
        db_policy = service.save_policy(Policy(name="Watch database", source_id=source["id"], trigger="database-change",
                                               acknowledge_scan=True, debounce_seconds=0, cooldown_seconds=60).model_dump())
        service.events.observe(db_policy)
        adapter.query(source, f"INSERT INTO {table}(id,amount,value) VALUES(2,1.25,'database event')")
        service.events.observe(db_policy)
        service.events.dispatch()
        run = service.store.all("runs")[0]
        assert run["origin"] == "database-change"
        service.execute(run)
        assert service.store.get("runs", run["id"])["status"] == "succeeded"
        adapter.query(source, f"TRUNCATE TABLE {table}")
        assert fingerprint(adapter, source, [table], service.directory) != updated
        print("Verified table/database polling, out-of-scope changes, fractional updates, column/table changes and real event-triggered exports.")
    finally:
        adapter.query(source, f"DROP TABLE IF EXISTS {other}")
        adapter.query(source, f"DROP TABLE IF EXISTS {table}")
