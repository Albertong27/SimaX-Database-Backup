import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from simax.__main__ import migrate_credentials
from simax.db import Store
from simax.models import Policy
from simax.service import Service, acquire_runtime_lock
from simax.vault import Vault, VaultError
from test_app import FixtureAdapter, make_artifact, setup, source  # noqa: F401


def test_key_reused_and_ciphertext_authenticated(tmp_path):
    store = Store(tmp_path)
    key = store.vault.path.read_bytes()
    body = {"id": "secret", "username": "private-user", "password": " private-${literal}-密码 "}
    store.put("settings", body)
    with store.connect() as db:
        encrypted = db.execute("SELECT body FROM settings").fetchone()[0]
    assert "private" not in encrypted
    assert Store(tmp_path).get("settings", "secret") == body
    assert store.vault.path.read_bytes() == key
    damaged = encrypted[:45] + ("A" if encrypted[45] != "A" else "B") + encrypted[46:]
    with pytest.raises(VaultError, match="authentication failed"):
        store.decode(damaged)
    second = tmp_path / "other"
    second.mkdir()
    with pytest.raises(VaultError, match="authentication failed"):
        Vault(second).decode(encrypted)
    if os.name == "nt":
        assert key.startswith(b"DPAPI1\n")
    else:
        assert store.vault.path.stat().st_mode & 0o077 == 0


def test_missing_or_corrupt_key_never_replaced(tmp_path):
    store = Store(tmp_path)
    store.put("settings", {"id": "a", "password": "private"})
    key = store.vault.path.read_bytes()
    store.vault.path.unlink()
    with pytest.raises(VaultError, match="missing"):
        Store(tmp_path)
    assert not store.vault.path.exists()
    store.vault.path.write_bytes(b"corrupt")
    with pytest.raises(VaultError, match="Cannot unlock"):
        Store(tmp_path)
    assert store.vault.path.read_bytes() == b"corrupt"
    store.vault.path.write_bytes(key)
    if os.name != "nt":
        store.vault.path.chmod(0o600)
    assert Store(tmp_path).get("settings", "a")["password"] == "private"


def test_concurrent_key_initialization_publishes_one_complete_key(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as executor:
        vaults = list(executor.map(lambda _: Vault(tmp_path), range(16)))
    token = vaults[0].encode({"id": "concurrent", "password": "private"})
    assert all(v.decode(token)["password"] == "private" for v in vaults)
    assert not list(tmp_path.glob(".key-*"))


def legacy_catalog(tmp_path):
    # Build a real v2 file, including credential copies in historical runs.
    with sqlite3.connect(tmp_path / "simax.sqlite3") as db:
        db.executescript("CREATE TABLE sources(id TEXT PRIMARY KEY, name TEXT UNIQUE, body TEXT);"
                         "CREATE TABLE runs(id TEXT PRIMARY KEY, status TEXT, body TEXT); PRAGMA user_version=2;")
        original = {**source(), "id": "src_legacy", "username": "legacy-private-user", "revision": 1}
        original.pop("password")
        original["password_env"] = "SIMAX_SECRET_OLD"
        db.execute("INSERT INTO sources VALUES (?,?,?)", (original["id"], original["name"], json.dumps(original)))
        db.execute("INSERT INTO runs VALUES (?,?,?)", ("run_old", "succeeded", json.dumps({"id": "run_old", "source": original})))


def test_explicit_migration_encrypts_history_and_removes_imported_env(tmp_path, monkeypatch):
    legacy_catalog(tmp_path)
    env_file = tmp_path / ".env"
    password = " private-${LITERAL}-密码 "
    env_file.write_text(f"SIMAX_SECRET_OLD='{password}'\nSIMAX_SECRET_UNUSED=also-private\nOTHER_SETTING=keep\n", encoding="utf-8-sig")
    monkeypatch.setenv("SIMAX_SECRET_OLD", "wrong-process-value")
    assert migrate_credentials(tmp_path, env_file) == 2
    store = Store(tmp_path)
    for table, key in (("sources", "src_legacy"), ("runs", "run_old")):
        row = store.get(table, key)
        row = row["source"] if table == "runs" else row
        assert row["password"] == password
        assert "password_env" not in row
    assert "SIMAX_SECRET" not in env_file.read_text(encoding="utf-8-sig")
    assert "OTHER_SETTING=keep" in env_file.read_text(encoding="utf-8-sig")
    for path in tmp_path.glob("simax.sqlite3*"):
        data = path.read_bytes()
        assert b"legacy-private-user" not in data
        assert password.encode() not in data
    assert migrate_credentials(tmp_path, env_file) == 0
    assert store.get("settings", "imported-secrets")["values"]["SIMAX_SECRET_UNUSED"] == "also-private"


def test_incomplete_import_preserves_original_catalog_and_env(tmp_path):
    legacy_catalog(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("SIMAX_SECRET_OTHER=do-not-remove\n")
    with pytest.raises(VaultError, match="Legacy credentials"):
        migrate_credentials(tmp_path, env_file)
    with sqlite3.connect(tmp_path / "simax.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "password_env" in db.execute("SELECT body FROM sources").fetchone()[0]
    assert "do-not-remove" in env_file.read_text()


def test_import_refuses_active_runtime(tmp_path):
    Store(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("SIMAX_SECRET_OLD=keep\n")
    lock = acquire_runtime_lock(tmp_path)
    try:
        with pytest.raises(OSError):
            migrate_credentials(tmp_path, env_file)
        assert "keep" in env_file.read_text()
    finally:
        lock.close()


def test_api_redacts_credentials_and_preserves_edits_and_job_snapshots(setup):
    client, service, _ = setup
    src, policy, run, artifact = make_artifact(client, service)
    target = client.post("/api/sources", json=source("target", role="target", environment="DISPOSABLE")).json()
    preview = client.post("/api/restore/preview", json={"artifact_id": artifact["id"], "target_id": target["id"]})
    assert "super-secret" not in preview.text
    password = "  private-${literal}-密码  "
    updated = client.put(f"/api/sources/{src['id']}", json=source(password=password))
    assert updated.status_code == 200
    assert password not in updated.text and updated.json()["password_saved"]
    edit = source()
    del edit["password"]
    assert client.put(f"/api/sources/{src['id']}", json=edit).status_code == 200
    restarted = Service(service.directory, FixtureAdapter())
    assert restarted.store.get("sources", src["id"])["password"] == password
    assert restarted.store.get("runs", run["id"])["source"]["password"] == "super-secret"
    signing_key, broker_password = "signing-key-" * 4, "private-broker-password"
    body = Policy(name=policy["name"], source_id=src["id"], trigger="mqtt", event_secret=signing_key,
                  mqtt_username="private-broker-user", mqtt_password=broker_password).model_dump()
    response = client.put(f"/api/policies/{policy['id']}", json=body)
    assert response.status_code == 200
    body.pop("event_secret")
    body.pop("mqtt_password")
    assert client.put(f"/api/policies/{policy['id']}", json=body).status_code == 200
    saved = restarted.store.get("policies", policy["id"])
    assert saved["event_secret"] == signing_key and saved["mqtt_password"] == broker_password
    state = client.get("/api/state").text
    for secret in ("super-secret", password, signing_key, broker_password):
        assert secret not in state
    body["mqtt_username"] = ""
    assert client.put(f"/api/policies/{policy['id']}", json=body).status_code == 200
    assert restarted.store.get("policies", policy["id"])["mqtt_password"] == ""
    for path in service.directory.glob("simax.sqlite3*"):
        data = path.read_bytes()
        for private in (password, signing_key, broker_password, "private-broker-user", "super-secret"):
            assert private.encode() not in data
