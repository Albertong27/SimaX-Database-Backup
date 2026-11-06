from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from simax.models import Policy
from simax.operations import protection_report
from simax.schedules import upcoming
from test_app import make_policy, setup, source, target  # noqa: F401


def export(service, policy):
    run = service.enqueue(policy["id"])
    service.execute(run)
    return service.store.get("runs", run["id"])


def history(client, service):
    src, policy = make_policy(client)
    artifacts = []
    for days in (5, 4, 3, 2):
        run = export(service, policy)
        artifact = service.store.get("artifacts", run["artifact_id"])
        artifact.update(created=(datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
                        snapshot=(datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
        service.store.put("artifacts", artifact)
        artifacts.append(artifact)
    body = Policy(**{k: v for k, v in policy.items() if k in Policy.model_fields}).model_dump()
    body.update(retention_enabled=True, retention_days=1, retention_keep_last=2, freshness_minutes=150)
    policy = service.save_policy(body, policy["id"])
    return src, policy, artifacts


def test_two_hour_schedule_preserves_every_peak_hour_interval():
    plan = Policy(name="two-hour", source_id="src", trigger="cron", cron="0 */2 * * *", timezone="Asia/Jakarta")
    times = upcoming(plan.model_dump(), datetime(2026, 10, 30, 1, 1, tzinfo=timezone.utc), count=8)
    assert [t["local"][11:16] for t in times] == ["10:00", "12:00", "14:00", "16:00", "18:00", "20:00", "22:00", "00:00"]
    assert all(datetime.fromisoformat(b["utc"]) - datetime.fromisoformat(a["utc"]) == timedelta(hours=2)
               for a, b in zip(times, times[1:]))


def test_retention_expires_history_only_after_success_and_keeps_floor(setup):
    client, service, adapter = setup
    _, policy, artifacts = history(client, service)
    preview = client.get(f"/api/policies/{policy['id']}/retention-preview")
    assert preview.status_code == 200 and len(preview.json()["eligible"]) == 2
    adapter.fail_export = True
    failed = export(service, policy)
    assert failed["status"] == "failed"
    assert all(service.artifact_path(a).is_file() for a in artifacts)
    adapter.fail_export = False
    succeeded = export(service, policy)
    assert succeeded["status"] == "succeeded"
    stored = service.store.all("artifacts")
    assert sum(a.get("lifecycle") == "expired" for a in stored) == 3
    assert sum(a.get("lifecycle") == "available" for a in stored) == 2
    assert all(not (service.backups / a["relative_path"]).exists() for a in stored if a["lifecycle"] == "expired")
    response = client.post("/api/restore/preview", json={"artifact_id": artifacts[0]["id"], "target_id": target(client)["id"]})
    assert response.status_code == 400


def test_pins_preview_reservations_and_queued_restores_protect_history(setup):
    client, service, _ = setup
    _, policy, artifacts = history(client, service)
    assert client.put(f"/api/artifacts/{artifacts[0]['id']}/pin", json={"pinned": True}).status_code == 200
    dst = target(client)
    previews = [client.post("/api/restore/preview", json={"artifact_id": a["id"], "target_id": dst["id"]}).json()
                for a in artifacts[1:3]]
    assert client.post("/api/restore/confirm", json={"token": previews[1]["token"], "target_name": dst["name"], "acknowledge_code": True}).status_code == 202
    export(service, policy)
    assert all(service.artifact_path(service.store.get("artifacts", a["id"])).is_file() for a in artifacts)


def test_incident_hold_and_concurrent_policy_edit_stop_expiry(setup, monkeypatch):
    client, service, adapter = setup
    _, policy, artifacts = history(client, service)
    original = adapter.export
    def during_export(src, path):
        original(src, path)
        updated = {k: v for k, v in policy.items() if k in Policy.model_fields}
        updated["retention_hold"] = True
        service.save_policy(updated, policy["id"])
    monkeypatch.setattr(adapter, "export", during_export)
    export(service, policy)
    assert service.retention_preview(policy["id"])["eligible"] == []
    assert all(service.artifact_path(a).is_file() for a in artifacts)


def test_interrupted_file_cleanup_resumes_without_false_restore_evidence(setup, monkeypatch):
    client, service, _ = setup
    _, policy, artifacts = history(client, service)
    original = Path.unlink
    failing = service.backups / artifacts[0]["relative_path"]
    def fail_manifest(path, *args, **kwargs):
        if path == failing.with_name("manifest.json"):
            raise PermissionError("controlled fixture failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_manifest)
    run = export(service, policy)
    assert run["status"] == "succeeded" and run["retention_error"]
    deleting = service.store.get("artifacts", artifacts[0]["id"])
    assert deleting["lifecycle"] == "deleting"
    with pytest.raises(ValueError, match="expired"):
        service.artifact_path(deleting)
    monkeypatch.setattr(Path, "unlink", original)
    export(service, policy)
    assert service.store.get("artifacts", artifacts[0]["id"])["lifecycle"] == "expired"


def test_retention_refuses_escape_or_foreign_files(setup, tmp_path):
    client, service, _ = setup
    _, policy, artifacts = history(client, service)
    owned = service.backups / artifacts[0]["relative_path"]
    foreign = owned.parent / "incident-evidence.txt"
    foreign.write_text("keep")
    result = export(service, policy)
    assert result["retention_error"] and foreign.read_text() == "keep" and owned.exists()
    artifact = service.store.get("artifacts", artifacts[0]["id"])
    artifact["relative_path"] = "../../outside/backup.sql"
    with pytest.raises(ValueError, match="ownership"):
        service.expire_artifact(artifact)


def test_protection_exposes_stale_failed_and_missing_recovery_points(setup):
    client, service, adapter = setup
    _, policy, artifacts = history(client, service)
    assert not service.protection()["ok"]
    assert any("freshness" in reason for reason in service.protection()["policies"][0]["reasons"])
    latest = export(service, policy)
    assert service.protection()["ok"]
    artifact = service.store.get("artifacts", latest["artifact_id"])
    service.artifact_path(artifact).write_text("corrupt")
    report = service.protection()
    assert not report["ok"] and "size changed" in " ".join(report["policies"][0]["reasons"])
    adapter.fail_export = True
    export(service, policy)
    assert "failed" in " ".join(service.protection()["policies"][0]["reasons"])
    response = client.get("/api/health/protection")
    assert response.status_code == 503 and "super-secret" not in response.text


def test_low_disk_blocks_export_without_expiring_history(setup, monkeypatch):
    client, service, _ = setup
    _, policy, artifacts = history(client, service)
    monkeypatch.setattr("simax.service.shutil.disk_usage", lambda _: SimpleNamespace(free=1024))
    run = export(service, policy)
    assert run["status"] == "failed" and "free space" in run["error"]
    assert not service.protection()["storage_ok"]
    assert all(service.artifact_path(a).exists() for a in artifacts)


@pytest.mark.parametrize("queue_minutes,within", [(0, True), (20, False)])
def test_recovery_duration_includes_queue_and_never_claims_production_rto(setup, queue_minutes, within):
    client, service, _ = setup
    _, policy = make_policy(client)
    backup = export(service, policy)
    dst = target(client)
    preview = client.post("/api/restore/preview", json={"artifact_id": backup["artifact_id"], "target_id": dst["id"]}).json()
    accepted = client.post("/api/restore/confirm", json={"token": preview["token"], "target_name": dst["name"], "acknowledge_code": True}).json()
    run = service.store.get("runs", accepted["id"])
    run["created"] = (datetime.now(timezone.utc) - timedelta(minutes=queue_minutes)).isoformat()
    service.execute(run)
    report = client.get(f"/api/runs/{run['id']}/recovery-report").json()
    assert report["within_target"] is within and report["target_seconds"] == 900
    assert report["execution_seconds"] >= 0 and report["total_seconds"] >= queue_minutes * 60
    assert report["production_rto_verified"] is False
    assert "super-secret" not in str(report)
