import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from simax.adapters import AdapterError, NativeAdapter
from simax.app import create_app
from simax.service import Service


class FixtureAdapter:
    """Controlled native-tool boundary. These tests do not claim live-engine support."""
    tools = NativeAdapter.tools

    def __init__(self):
        self.fail_export = False
        self.restored = []
        self.nonempty = set()
        self.tables = ["public.orders"]

    def availability(self):
        return {"postgresql": {"psql": True, "pg_dump": True},
                "mysql": {"mysql": True, "mysqldump": True}}

    def inspect(self, source):
        return {"version": "PostgreSQL 17.2", "major": 17,
                "tables": self.tables.copy(), "tool_version": "pg_dump 17.2"}

    def ensure_empty(self, source):
        if source["id"] in self.nonempty:
            raise AdapterError("Target must be empty.")

    def export(self, source, path):
        path.write_text("CREATE TABLE orders(id integer);\nINSERT INTO orders VALUES (42);\n")
        if self.fail_export:
            raise AdapterError("Controlled export failure")

    def restore(self, source, path):
        self.restored.append((source["id"], path.read_text()))
        self.nonempty.add(source["id"])


def source(name="orders-dev", **changes):
    return {"name": name, "engine": "postgresql", "host": "localhost", "port": 5432,
            "database": "orders", "username": "backup", "password_env": "SIMAX_SECRET_TEST",
            "environment": "DEV", "role": "source", "tls": "disable", **changes}


@pytest.fixture
def setup(tmp_path):
    adapter = FixtureAdapter()
    app = create_app(tmp_path, adapter, worker=False)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-SimaX-Request": "1"}) as client:
        yield client, app.state.service, adapter


def make_policy(client):
    response = client.post("/api/sources", json=source())
    assert response.status_code == 201
    src = response.json()
    response = client.post("/api/policies", json={"name": "nightly", "source_id": src["id"]})
    assert response.status_code == 201
    return src, response.json()


def make_artifact(client, service):
    src, policy = make_policy(client)
    run = client.post(f"/api/policies/{policy['id']}/run").json()
    service.tick()
    artifact = service.store.all("artifacts")[0]
    return src, policy, run, artifact


def test_empty_catalog_is_real_and_persistent(setup):
    client, service, _ = setup
    assert client.get("/api/state").json()["sources"] == []
    src, _ = make_policy(client)
    other = Service(service.directory, FixtureAdapter())
    assert other.store.get("sources", src["id"])["name"] == "orders-dev"
    assert "password" not in other.store.get("sources", src["id"])
    assert other.store.all("audit")


def test_source_duplicate_and_no_password_leak(setup):
    client, _, _ = setup
    assert client.post("/api/sources", json=source()).status_code == 201
    assert client.post("/api/sources", json=source()).status_code == 409
    response = client.post("/api/sources", json={**source("extra"), "password": "secret-value"})
    assert response.status_code == 422
    assert "secret-value" not in response.text


@pytest.mark.parametrize("changes", [
    {"database": "postgresql://other/server"}, {"database": "x; DROP TABLE x"},
    {"host": "--help"}, {"password_env": "PATH"},
    {"host": "remote.example", "tls": "disable"}, {"port": 0}
])
def test_connection_input_boundaries(setup, changes):
    client, _, _ = setup
    assert client.post("/api/sources", json=source(**changes)).status_code == 422


def test_origin_host_and_mutation_boundaries(setup):
    client, _, _ = setup
    assert client.post("/api/sources", json=source(), headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/sources", json=source(), headers={"X-SimaX-Request": ""}).status_code == 403
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 400
    response = client.get("/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_backup_finalization_and_policy_snapshot(setup):
    client, service, _ = setup
    src, policy = make_policy(client)
    run = client.post(f"/api/policies/{policy['id']}/run").json()
    assert client.post(f"/api/policies/{policy['id']}/run").status_code == 400
    edited = {"name": "new-name", "source_id": src["id"], "destination": "second"}
    assert client.put(f"/api/policies/{policy['id']}", json=edited).status_code == 200
    service.tick()
    result = service.store.get("runs", run["id"])
    assert result["status"] == "succeeded"
    assert result["policy"]["revision"] == 1
    assert result["policy"]["name"] == "nightly"
    artifact = service.store.all("artifacts")[0]
    path = service.artifact_path(artifact)
    assert path.parent.parent.name == "local"
    assert artifact["restore_test"] is None
    assert path.with_name("manifest.json").exists()
    manifest = json.loads(path.with_name("manifest.json").read_text())
    assert "password_env" not in json.dumps(manifest)
    assert not path.with_name("backup.sql.partial").exists()


def test_partial_export_never_becomes_artifact(setup):
    client, service, adapter = setup
    _, policy = make_policy(client)
    adapter.fail_export = True
    run = client.post(f"/api/policies/{policy['id']}/run").json()
    service.tick()
    assert service.store.get("runs", run["id"])["status"] == "failed"
    assert service.store.all("artifacts") == []
    assert list(service.backups.rglob("*.partial"))


def test_unsupported_policy_cannot_be_accepted(setup):
    client, _, _ = setup
    src = client.post("/api/sources", json=source(engine="oracle")).json()
    assert client.post("/api/policies", json={"name": "oracle", "source_id": src["id"]}).status_code == 400
    src = client.post("/api/sources", json=source("second")).json()
    assert client.post("/api/policies", json={"name": "bad", "source_id": src["id"], "trigger": "webhook"}).status_code == 422
    assert client.post("/api/policies", json={"name": "bad", "source_id": src["id"], "destination": "../outside"}).status_code == 422
    assert client.post("/api/policies", json={"name": "bad", "source_id": src["id"], "timezone": "invalid"}).status_code == 422


def test_schedule_once_per_day_and_no_old_day_catchup(setup):
    client, service, _ = setup
    src, policy = make_policy(client)
    policy.update(trigger="daily", time="03:00", timezone="Asia/Jakarta", updated="2026-10-17T00:00:00+00:00")
    service.store.put("policies", policy)
    instant = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    service.schedule(instant)
    service.schedule(instant)
    assert len(service.store.all("runs")) == 1
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 1
    assert service.store.all("runs")[0]["origin"] == "Schedule"


def test_dst_nonexistent_time_is_skipped(setup):
    client, service, _ = setup
    _, policy = make_policy(client)
    policy.update(trigger="daily", time="02:30", timezone="America/New_York", updated="2026-01-01T00:00:00+00:00")
    service.store.put("policies", policy)
    service.schedule(datetime(2026, 3, 8, 12, tzinfo=timezone.utc))
    assert service.store.all("runs") == []


def test_cancel_and_paused_policy(setup):
    client, service, _ = setup
    _, policy = make_policy(client)
    run = client.post(f"/api/policies/{policy['id']}/run").json()
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    service.tick()
    assert service.store.all("artifacts") == []
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 400
    policy["enabled"] = False
    service.store.put("policies", policy)
    assert client.post(f"/api/policies/{policy['id']}/run").status_code == 400


def target(client, **changes):
    return client.post("/api/sources", json=source("restore-test", database="restored", role="target", environment="DISPOSABLE", **changes)).json()


def test_restore_requires_preview_exact_authorization_and_single_use(setup):
    client, service, adapter = setup
    _, _, _, artifact = make_artifact(client, service)
    dst = target(client)
    preview = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]}).json()
    payload = {"token": preview["token"], "target_name": "wrong", "acknowledge_code": True}
    assert client.post("/api/restore/confirm", json=payload).status_code == 400
    payload["target_name"] = dst["name"]
    response = client.post("/api/restore/confirm", json=payload)
    assert response.status_code == 202
    assert client.post("/api/restore/confirm", json=payload).status_code == 400
    service.tick()
    assert adapter.restored
    assert service.store.get("runs", response.json()["id"])["status"] == "succeeded"
    evidence = service.store.get("artifacts", artifact["id"])["restore_test"]
    assert "data and behavior not verified" in evidence["level"]


def test_corruption_blocks_restore_before_any_execution(setup):
    client, service, adapter = setup
    _, _, _, artifact = make_artifact(client, service)
    dst = target(client)
    service.artifact_path(artifact).write_text("damaged")
    response = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]})
    assert response.status_code == 400
    assert "integrity" in response.text
    assert not adapter.restored


def test_target_rechecked_after_preview(setup):
    client, service, adapter = setup
    _, _, _, artifact = make_artifact(client, service)
    dst = target(client)
    preview = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]}).json()
    response = client.post("/api/restore/confirm", json={"token": preview["token"], "target_name": dst["name"], "acknowledge_code": True})
    adapter.nonempty.add(dst["id"])
    service.tick()
    assert not adapter.restored
    assert service.store.get("runs", response.json()["id"])["status"] == "failed"


def test_production_and_same_database_restore_blocked(setup):
    client, service, _ = setup
    src, _, _, artifact = make_artifact(client, service)
    assert client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": src["id"]}).status_code == 400
    dst = target(client)
    dst["database"] = src["database"]
    service.store.put("sources", dst)
    response = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]})
    assert response.status_code == 400


def test_missing_tools_are_actionable_not_success(setup, monkeypatch):
    client, service, _ = setup
    service.adapter = NativeAdapter()
    monkeypatch.setattr("simax.adapters.shutil.which", lambda _: None)
    src, _ = make_policy(client)
    response = client.post(f"/api/sources/{src['id']}/preflight")
    assert not response.json()["ok"]
    assert "Install psql" in response.json()["message"]


def test_native_arguments_do_not_contain_password(monkeypatch):
    monkeypatch.setattr("simax.adapters.shutil.which", lambda tool: f"/tools/{tool}")
    monkeypatch.setenv("SIMAX_SECRET_TEST", "super-secret")
    monkeypatch.setenv("PGSERVICE", "unwanted")
    args, environment = NativeAdapter().command(source(), export=True)
    assert "super-secret" not in " ".join(args)
    assert environment["PGPASSWORD"] == "super-secret"
    assert "PGSERVICE" not in environment
    assert "SIMAX_SECRET_TEST" not in environment
    assert "--dbname" in args


def test_artifact_path_escape_blocked(setup):
    client, service, _ = setup
    _, _, _, artifact = make_artifact(client, service)
    artifact["relative_path"] = "../simax.sqlite3"
    with pytest.raises(ValueError, match="outside"):
        service.artifact_path(artifact)


def test_runtime_recovers_interrupted_work_and_excludes_second_owner(tmp_path):
    first = Service(tmp_path, FixtureAdapter())
    run = {"id": "run_crashed", "status": "running", "kind": "restore", "events": []}
    first.store.put("runs", run)
    first.start()
    try:
        assert first.store.get("runs", "run_crashed")["status"] == "interrupted"
        second = Service(tmp_path, FixtureAdapter())
        with pytest.raises(OSError):
            second.start()
        if second.lock:
            second.lock.close()
    finally:
        first.close()


def test_settings_validation_and_audit_export(setup):
    client, _, _ = setup
    assert client.put("/api/settings", json={"timezone": "missing"}).status_code == 422
    assert client.put("/api/settings", json={"timezone": "UTC", "recovery_limit_hours": 12}).status_code == 200
    response = client.get("/api/audit/export")
    assert "attachment" in response.headers["content-disposition"]
    assert response.json()[0]["action"] == "Display and freshness settings updated"


def test_bound_source_cannot_break_existing_policy(setup):
    client, _, _ = setup
    src, _ = make_policy(client)
    assert client.put(f"/api/sources/{src['id']}", json=source(engine="oracle")).status_code == 400
    assert client.put(f"/api/sources/{src['id']}", json=source(role="target")).status_code == 400


def test_expired_preview_never_enqueues_restore(setup):
    client, service, _ = setup
    _, _, _, artifact = make_artifact(client, service)
    dst = target(client)
    preview = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": dst["id"]}).json()
    saved = service.store.get("confirmations", preview["token"])
    saved["expires"] = "2000-01-01T00:00:00+00:00"
    service.store.put("confirmations", saved)
    assert client.post("/api/restore/confirm", json={"token": preview["token"], "target_name": dst["name"], "acknowledge_code": True}).status_code == 400
    assert not any(r["kind"] == "restore" for r in service.store.all("runs"))


def test_newer_catalog_version_is_not_downgraded(tmp_path):
    service = Service(tmp_path, FixtureAdapter())
    with service.store.connect() as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="newer schema"):
        Service(tmp_path, FixtureAdapter())
    with service.store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 999
