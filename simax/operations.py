"""Retention decisions and recovery visibility. No database commands or deletion here."""

from datetime import datetime, timedelta, timezone


def available(artifact):
    return artifact.get("lifecycle", "available") == "available"


def identity(source):
    return tuple(source.get(key) for key in ("engine", "host", "port", "database"))


def policy_artifacts(policy, source, artifacts, runs):
    runs = {run["id"]: run for run in runs}
    result = []
    for artifact in artifacts:
        run = runs.get(artifact["run_id"], {})
        if (run.get("policy", {}).get("id") == policy["id"]
                and identity(run.get("source", {})) == identity(source)
                and artifact["source_id"] == source["id"]):
            result.append(artifact)
    return sorted(result, key=lambda artifact: (artifact["snapshot"], artifact["id"]), reverse=True)


def retention_plan(policy, source, artifacts, runs, confirmations, instant=None):
    instant = instant or datetime.now(timezone.utc)
    if not policy.get("retention_enabled") or policy.get("retention_hold") or not policy["enabled"]:
        return []
    history = [a for a in policy_artifacts(policy, source, artifacts, runs)
               if a.get("lifecycle") != "expired"]
    # Keep the newest usable copies even if an older deletion was interrupted.
    keep = {a["id"] for a in [a for a in history if available(a)][:policy.get("retention_keep_last", 12)]}
    keep |= {r.get("artifact_id") for r in runs if r["status"] in {"queued", "running"}}
    keep |= {c["artifact_id"] for c in confirmations if datetime.fromisoformat(c["expires"]) > instant}
    cutoff = instant - timedelta(days=policy.get("retention_days", 30))
    return [a for a in history if a["id"] not in keep and not a.get("pinned")
            and datetime.fromisoformat(a["created"]) < cutoff
            and datetime.fromisoformat(a["snapshot"]) < cutoff]


def protection_report(policies, sources, artifacts, runs, instant=None):
    instant = instant or datetime.now(timezone.utc)
    sources = {s["id"]: s for s in sources}
    rows = []
    for policy in policies:
        source = sources.get(policy["source_id"], {})
        history = policy_artifacts(policy, source, artifacts, runs)
        usable = [a for a in history if available(a)]
        latest = usable[0] if usable else None
        age = max(0, (instant - datetime.fromisoformat(latest["snapshot"])).total_seconds()) if latest else None
        related = sorted([r for r in runs if r.get("policy", {}).get("id") == policy["id"]],
                         key=lambda r: r["created"], reverse=True)
        latest_run = related[0] if related else None
        completed = next((r for r in related if r["status"] not in {"queued", "running", "cancelled"}), None)
        reasons = []
        if not latest:
            reasons.append("No available recovery point for the current source.")
        elif age > policy.get("freshness_minutes", 1440) * 60:
            reasons.append("Latest recovery point exceeds the policy freshness limit.")
        if completed and completed["status"] in {"failed", "interrupted"}:
            reasons.append("Latest completed backup failed or was interrupted.")
        if latest_run and latest_run["status"] in {"queued", "running"}:
            if (instant - datetime.fromisoformat(latest_run["created"])).total_seconds() > policy.get("freshness_minutes", 1440) * 60:
                reasons.append("Backup has remained queued or running beyond the freshness limit.")
        if any(a.get("retention_error") or a.get("lifecycle") == "deleting" for a in history):
            reasons.append("Retention cleanup is incomplete; inspect storage and retained history.")
        rows.append({"policy_id": policy["id"], "name": policy["name"], "enabled": policy["enabled"],
                     "status": "attention" if reasons else "current", "reasons": reasons,
                     "snapshot_age_seconds": age, "freshness_minutes": policy.get("freshness_minutes", 1440),
                     "latest_artifact_id": latest["id"] if latest else None,
                     "retention_hold": policy.get("retention_hold", False)})
    return {"checked": instant.isoformat(), "policies": rows,
            "ok": bool(rows) and all(row["enabled"] and row["status"] == "current" for row in rows)}
