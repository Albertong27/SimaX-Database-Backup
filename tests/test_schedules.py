from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from simax.models import Policy, Schedule
from simax.schedules import latest_due, upcoming
from simax.service import Service
from test_app import FixtureAdapter, make_policy, setup  # noqa: F401


def at(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def schedule(**values):
    return Schedule(**values).model_dump()


@pytest.mark.parametrize("expression", [
    "* * * *", "0 0 0 * * *", "@daily", "60 * * * *", "0 24 * * *",
    "0 0 0 * *", "0 0 * 13 *", "0 0 * * 8", "*/0 * * * *",
    "0 0 * * 5-1", "0 0 31 2 *", "0 0 * * MON", "0 0 L * *",
    "H * * * *", "0 0 * * 1#2", "0,,1 * * * *",
])
def test_invalid_or_unsupported_cron(expression):
    with pytest.raises(ValueError):
        schedule(trigger="cron", cron=expression)


def test_lists_ranges_steps_and_sunday_alias():
    config = schedule(trigger="cron", cron="5,35 8-10/2 * * 7", timezone="UTC")
    assert [v["utc"] for v in upcoming(config, at("2026-10-18T08:05:00Z"), 4)] == [
        "2026-10-18T08:35:00+00:00", "2026-10-18T10:05:00+00:00",
        "2026-10-18T10:35:00+00:00", "2026-10-25T08:05:00+00:00",
    ]


def test_both_restricted_day_fields_use_or():
    config = schedule(trigger="cron", cron="0 9 31 2 1", timezone="UTC")
    assert [v["utc"][:10] for v in upcoming(config, at("2026-02-01T00:00:00Z"), 4)] == [
        "2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23",
    ]


def test_leap_day_preview_is_bounded_and_crosses_nonleap_century():
    config = schedule(trigger="cron", cron="0 9 29 2 *", timezone="UTC")
    result = upcoming(config, at("2096-03-01T00:00:00Z"))
    assert len(result) == 1
    assert result[0]["utc"] == "2104-02-29T09:00:00+00:00"


def test_weekly_preview_uses_monday_zero_and_policy_timezone():
    config = schedule(trigger="weekly", weekdays=[0, 4], time="03:00", timezone="Asia/Jakarta")
    assert [v["utc"] for v in upcoming(config, at("2026-10-18T21:00:00Z"), 2)] == [
        "2026-10-22T20:00:00+00:00", "2026-10-25T20:00:00+00:00",
    ]
    assert latest_due(config, at("2026-10-20T00:00:00Z")) is None


@pytest.mark.parametrize("trigger,extra", [("daily", {}), ("weekly", {"weekdays": [6]}), ("cron", {"cron": "30 2 * * *"})])
def test_spring_gap_preview_and_execution_agree(trigger, extra):
    config = schedule(trigger=trigger, time="02:30", timezone="America/New_York", **extra)
    assert latest_due(config, at("2026-03-08T12:00:00Z")) is None
    result = upcoming(config, at("2026-03-08T00:00:00-05:00"), 1)[0]
    assert result["local"] == ("2026-03-15" if trigger == "weekly" else "2026-03-09") + "T02:30:00-04:00"


def test_fall_back_uses_first_fold_even_when_current_wall_time_is_earlier():
    config = schedule(trigger="cron", cron="30 1 * * *", timezone="America/New_York")
    instant = at("2026-11-01T01:15:00-05:00")
    assert latest_due(config, instant) == at("2026-11-01T01:30:00-04:00")
    assert upcoming(config, instant, 1)[0]["local"] == "2026-11-02T01:30:00-05:00"


def test_preview_is_read_only_and_invalid_input_cannot_be_saved(setup):
    client, service, _ = setup
    src, _ = make_policy(client)
    before = {key: service.store.all(key) for key in ["policies", "runs", "audit"]}
    response = client.post("/api/schedules/preview", json={"trigger": "cron", "cron": "*/15 * * * *"})
    assert response.status_code == 200
    assert len(response.json()["occurrences"]) == 5
    assert all(at(b["utc"]) > at(a["utc"]) for a, b in zip(response.json()["occurrences"], response.json()["occurrences"][1:]))
    assert before == {key: service.store.all(key) for key in before}
    for changes in [{"trigger": "weekly", "weekdays": []}, {"weekdays": [7]},
                    {"weekdays": [0, 0]}, {"trigger": "cron", "cron": "0 0 31 2 *"}]:
        assert client.post("/api/schedules/preview", json=changes).status_code == 422
        assert client.post("/api/policies", json={"name": "invalid", "source_id": src["id"], **changes}).status_code == 422
    assert client.post("/api/schedules/preview", json={"trigger": "manual"}).json()["occurrences"] == []


def saved_schedule(client, service, **changes):
    _, policy = make_policy(client)
    policy.update(trigger="cron", cron="*/15 * * * *", timezone="UTC",
                  updated="2026-01-01T00:00:00+00:00", **changes)
    service.store.put("policies", policy)
    return policy


def test_latest_only_catchup_restart_dedup_and_next_occurrence(setup):
    client, service, _ = setup
    policy = saved_schedule(client, service)
    instant = at("2026-10-19T10:47:00Z")
    service.schedule(instant)
    run = service.store.all("runs")[0]
    assert run["scheduled_for"] == "2026-10-19T10:45:00+00:00"
    service.execute(run)
    assert service.store.all("runs")[0]["status"] == "succeeded"
    restarted = Service(service.directory, FixtureAdapter())
    restarted.schedule(instant)
    assert len(service.store.all("runs")) == 1
    restarted.schedule(at("2026-10-19T11:01:00Z"))
    assert len(service.store.all("runs")) == 2
    assert service.store.all("runs")[0]["policy"]["id"] == policy["id"]


def test_coalesced_occurrence_does_not_reappear_after_active_job_finishes(setup):
    client, service, _ = setup
    policy = saved_schedule(client, service)
    active = service.enqueue(policy["id"])
    instant = at("2026-10-19T10:47:00Z")
    service.schedule(instant)
    assert len(service.store.all("runs")) == 1
    assert any(a["action"] == "Schedule coalesced into active backup" for a in service.store.all("audit"))
    service.execute(active)
    service.schedule(instant)
    assert len(service.store.all("runs")) == 1


def test_weekly_skips_previous_days_and_before_edit_occurrences(setup):
    client, service, _ = setup
    policy = saved_schedule(client, service)
    policy.update(trigger="weekly", weekdays=[0], time="09:00")
    service.store.put("policies", policy)
    service.schedule(at("2026-10-20T10:00:00Z"))  # Tuesday cannot catch up Monday.
    assert not service.store.all("runs")
    policy["updated"] = "2026-10-19T09:01:00+00:00"
    service.store.put("policies", policy)
    service.schedule(at("2026-10-19T10:00:00Z"))
    assert not service.store.all("runs")
    service.schedule(at("2026-10-26T09:00:00Z"))
    assert len(service.store.all("runs")) == 1


def test_stale_schedule_revision_cannot_enqueue_or_consume_occurrence(setup, monkeypatch):
    client, service, _ = setup
    policy = saved_schedule(client, service)
    enqueue = service.enqueue

    def edit_before_enqueue(*args, **kwargs):
        policy.update(enabled=False, revision=policy["revision"] + 1)
        service.store.put("policies", policy)
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(service, "enqueue", edit_before_enqueue)
    service.schedule(at("2026-10-19T10:00:00Z"))
    assert not service.store.all("runs")
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 0


def test_legacy_daily_occurrence_still_prevents_duplicate_after_upgrade(setup):
    client, service, _ = setup
    policy = saved_schedule(client, service)
    policy.update(trigger="daily", time="09:00")
    policy.pop("weekdays", None)
    policy.pop("cron", None)
    service.store.put("policies", policy)
    with service.store.connect() as db:
        db.execute("INSERT INTO occurrences VALUES (?, ?)", (f"{policy['id']}:2026-10-19", "2026-10-19T09:00:00+00:00"))
    service.schedule(at("2026-10-19T10:00:00Z"))
    assert not service.store.all("runs")


def test_concurrent_edits_get_distinct_revisions(setup):
    client, service, _ = setup
    src, policy = make_policy(client)
    body = Policy(name=policy["name"], source_id=src["id"]).model_dump()
    with ThreadPoolExecutor(max_workers=4) as pool:
        revisions = list(pool.map(lambda _: service.save_policy(body, policy["id"])["revision"], range(8)))
    assert sorted(revisions) == list(range(2, 10))
    assert service.store.get("policies", policy["id"])["revision"] == 9
