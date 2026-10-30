"""Opt-in synthetic throughput drill; never a production downtime certification."""

import hashlib
import json
import os
import platform
from pathlib import Path
import time

import pytest

from simax.adapters import NativeAdapter
from simax.models import Policy, Source
from simax.service import Service


MIB = int(os.environ.get("SIMAX_LIVE_BENCHMARK_MIB", "0"))
pytestmark = pytest.mark.skipif(os.environ.get("SIMAX_LIVE_ENGINE") != "mysql" or not MIB,
                                reason="Opt in with scripts/live_tests.py --engine mysql --benchmark-mib 128")


def test_timed_mysql_recovery_with_verified_payload(tmp_path):
    adapter = NativeAdapter()
    connections = []
    for role in ("source", "target"):
        connection = Source(name=f"benchmark-{role}", engine="mysql", host="127.0.0.1",
                            port=int(os.environ[f"SIMAX_LIVE_{role.upper()}_PORT"]), database="simax_fixture",
                            username="root", password=os.environ["SIMAX_SECRET_LIVE"], tls="disable",
                            role=role, environment="DISPOSABLE").model_dump()
        connections.append(connection)
    assert connections[0]["port"] != connections[1]["port"]
    for connection in connections:
        adapter.query(connection, "CREATE DATABASE simax_benchmark")
        connection["database"] = "simax_benchmark"
    src, dst = connections
    adapter.query(src, "CREATE TABLE payload(id INT PRIMARY KEY, body LONGBLOB NOT NULL) ENGINE=InnoDB")
    adapter.query(src, "INSERT INTO payload VALUES(0, REPEAT('0123456789abcdef',4096))")
    count = 1
    while count < MIB * 16:
        # Bound fixture transactions to 8 MiB; production metadata queries keep
        # their short timeout. Population is not counted as restore performance.
        batch = min(count, 128, MIB * 16 - count)
        args, env = adapter.command(src)
        sql = f"INSERT INTO payload SELECT id+{count}, body FROM payload WHERE id < {batch};\n"
        adapter.invoke(args + ["--database=" + src["database"]], env, input_data=sql.encode(), timeout=180)
        count += batch
    service = Service(tmp_path / "encrypted-catalog", adapter)
    source, target = [service.save_source(c) for c in connections]
    policy = service.save_policy(Policy(name="Timed synthetic recovery", source_id=source["id"]).model_dump())
    backup = service.enqueue(policy["id"])
    service.execute(backup)
    assert backup["status"] == "succeeded", "Synthetic export failed; inspect safe run metadata"
    artifact = service.store.get("artifacts", backup["artifact_id"])
    preview = service.preview_restore(artifact["id"], target["id"])
    restored = service.confirm_restore(preview["token"], target["name"], True)
    service.execute(restored)
    assert restored["status"] == "succeeded", "Synthetic replay failed; inspect safe run metadata"
    verify_start = time.monotonic()
    payload_hash = hashlib.sha256(("0123456789abcdef" * 4096).encode()).hexdigest()
    sql = ("SELECT JSON_ARRAY(COUNT(*), SUM(OCTET_LENGTH(body)), SUM(id), "
           f"SUM(SHA2(body,256) <> '{payload_hash}')) FROM payload")
    expected = [count, count * 65536, count * (count - 1) // 2, 0]
    assert json.loads(adapter.query(dst, sql)) == expected
    assert json.loads(adapter.query(src, sql)) == expected
    validation_seconds = time.monotonic() - verify_start
    report = {"workload": "Synthetic fixed BLOB rows; not the production database or representative peak traffic",
              "platform": platform.platform(), "server_version": artifact["server_version"],
              "tool_version": artifact["tool_version"], "payload_mib": count / 16,
              "backup_bytes": artifact["bytes"], "backup_seconds": backup["duration_seconds"],
              "recovery": restored["recovery"], "payload_validation_seconds": round(validation_seconds, 3),
              "drill_plus_payload_check_seconds": round(restored["recovery"]["total_seconds"] + validation_seconds, 3),
              "production_rto_verified": False,
              "verification": "Exact row count, total payload bytes, identity sum, and SHA-256 of every BLOB; unchanged source verified"}
    destination = Path(os.environ["SIMAX_LIVE_REPORT_DIR"]) / "mysql-recovery-benchmark.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("\nTIMED RECOVERY " + json.dumps(report))
