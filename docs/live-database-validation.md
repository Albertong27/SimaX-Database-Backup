# Native database validation

Validated locally on 2026-10-19, Windows x64, Python 3.12.4. All data is synthetic. Docker is not used by the test harness or the native CI job.

## Tested matrix

| Engine | Server | Export / replay clients | Native live result |
| --- | --- | --- | --- |
| PostgreSQL | 17.11, Windows x64 EDB binaries | pg_dump / psql 17.11 | 5 passed; 1 MySQL-only case skipped |
| MySQL Community | 8.4.11, Windows x64 | mysqldump / mysql 8.4.11 | 6 passed |

Each engine uses two separate server processes with different loopback ports and data directories. Both databases are named `simax_fixture`. No existing server, Windows service, normal SimaX catalog, or user database is used. The app uses its real SQLite store, HTTP API, background worker, and native adapter throughout the round trip.

The default regression suite has 81 passing tests. Live cases are skipped by default. GitHub Actions is configured to repeat both engines on `windows-2025` with Python 3.12 and the same pinned binaries; this milestone has not been pushed or validated by hosted CI.

## Reproduce on Windows

From the repository root, with Python 3.12+:

```powershell
python -m pip install -r requirements-dev.txt
python scripts/fetch_test_tools.py
$env:PATH = "$pwd\build\native-tools\postgresql\pgsql\bin;$pwd\build\native-tools\mysql\mysql-8.4.11-winx64\bin;$env:PATH"
python scripts/live_tests.py
```

Use `--engine postgresql` or `--engine mysql` for a focused run. The download helper retrieves approximately 594 MiB of ZIP archives from the official distribution hosts, verifies pinned SHA-256 checksums before extraction, and writes only under ignored `build/native-tools/`. It does not install services or change the global PATH. Hashes are recorded from the HTTPS downloads used for this validation; the MySQL archive also matched its publisher's download-page MD5. Hash pinning is not a claim of independently verified publisher signatures.

The runner creates a unique `build/live-<id>/` workspace, generates credentials, binds servers to `127.0.0.1` on available ports, initializes source/target databases, and stops its own processes in `finally` cleanup. Native subprocesses are hidden on Windows. Credential bootstrap files are removed. Synthetic databases, SQL artifacts, manifests, server logs, JUnit XML, and test logs remain in that workspace for inspection and are ignored by Git. They can be removed after the owned servers stop. An abrupt termination of the runner can leave a process alive; inspect its command line and data directory before stopping it, never terminate all database processes by name.

On other systems the runner can consume compatible native binaries on PATH, but this milestone makes no Linux/macOS live compatibility claim. Do not set the internal `SIMAX_LIVE_*` environment variables manually; invoke the runner so it provisions isolated endpoints.

## Acceptance evidence

The successful round trip performs these operations:

1. Create fixture schemas and rows on the source through native clients.
2. Create SimaX source, target, and policy through the HTTP API; run source preflight.
3. Enqueue a backup and let the real background worker export SQL, finalize its manifest, and register the artifact.
4. Check artifact SHA-256, file size, manifest, and absence of partial files.
5. Preview the restore, authorize with the exact target name, and wait for worker replay into the separate target server.
6. Compare source and restored rows, including Unicode/emoji, quoted identifiers, binary zero bytes, JSON, decimals, timestamps, nulls, and empty strings.
7. Query restored views and PostgreSQL materialized views; execute functions/procedures; insert rows to verify identity sequences, generated columns, and trigger side effects. Verify foreign-key, check, and unique-constraint rejection, index presence, and disabled MySQL event preservation.
8. Confirm that target mutations did not change the source, and that a second restore into the nonempty target is rejected.

Additional live cases reject corrupted artifacts and invalid credentials without registering recovery points or exposing passwords; reject MyISAM tables; insert a sentinel after preview and confirm replay is blocked at execution; and deliberately fail SQL replay to verify stop-on-error. PostgreSQL rolls back the failed replay; MySQL retains preceding DDL and stops before later statements, consistent with its documented partial-restore boundary.

The event milestone additionally verifies read-only table/database fingerprints, ignored out-of-scope table changes, fractional decimal updates, inserts/deletes, column changes, table removal, and real backups requested by observed changes. Temporary fixture tables are removed before owned test servers stop. Reports for this milestone are in the ignored `build/live-2eddd9c52651/` workspace.

## Defect fixed

The initial PostgreSQL run failed when a query referenced the fixture's `résumé` table. On this Windows host, non-ASCII SQL supplied through native command arguments used the Windows code page, producing invalid UTF-8 at the server. Queries now travel as explicitly encoded UTF-8 standard input and PostgreSQL uses `PGCLIENTENCODING=UTF8`. MySQL uses raw batch output so backslashes and control characters in machine-readable query results are not escaped a second time. The Unicode and JSON/binary fixtures verify the corrected transport end to end.

The harness also avoids shell quoting for PostgreSQL server settings by writing its private configuration directly. This resolves the Windows interpretation of an empty Unix-socket directory argument.

## Limits

- This is a small-fixture logical-backup matrix, not production certification, load testing, RPO/RTO evidence, or a guarantee for every object type.
- Connections use loopback without TLS and administrator test accounts. TLS identity verification and least-privilege grants need separate live coverage.
- Restore was tested between separate instances using the same database name. Cross-engine conversion, arbitrary database renaming, external dependencies, definer remapping, replication, extensions, and version upgrades are not validated.
- The harness verifies fixture-specific data and behavior. The application itself still records only successful SQL replay and table-inventory comparison after restore. It does not automatically certify arbitrary customer data or routines.
- MySQL events are restored disabled and are not scheduled/executed. Keep event effects and source DDL quiesced during real recovery drills.

## Official references

- [PostgreSQL Windows distributions](https://www.postgresql.org/download/windows/) and [EDB binary archives](https://www.enterprisedb.com/download-postgresql-binaries).
- [PostgreSQL psql encoding, script execution, and transactions](https://www.postgresql.org/docs/17/app-psql.html).
- [MySQL 8.4 downloads](https://dev.mysql.com/downloads/mysql/8.4.html) and [SQL-format backup/reload](https://dev.mysql.com/doc/refman/8.4/en/mysqldump-sql-format.html).
