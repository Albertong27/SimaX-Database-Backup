# Application architecture

## Local web application with SQLite

The implementation chooses the web option allowed by the PRD. FastAPI serves browser-native HTML/CSS/JavaScript and a JSON API. SQLite stores application metadata; the backup sources remain external database engines. Rust remains a possible future desktop packaging choice.

The interface follows the supplied PDF and HTML: Schibsted Grotesk text, JetBrains Mono identifiers, a 240px sidebar, neutral surfaces, indigo actions, numbered policy sections, recovery summaries, and separate evidence states. Original bundled Latin fonts are served locally with their licenses. No frontend build service is needed.

| Module | Responsibility |
| --- | --- |
| `simax/models.py` | Strict request validation and supported configuration modes |
| `simax/db.py` | SQLite schema, transactions, records and audit events |
| `simax/adapters.py` | Native PostgreSQL/MySQL inspection, export and replay |
| `simax/schedules.py` | Shared schedule calculation, bounded cron parsing and previews |
| `simax/service.py` | Scheduling, queue execution, policy snapshots, finalization and authorization |
| `simax/events.py`, `simax/mqtt.py`, `simax/observation.py` | Durable intake, independent observers, broker lifecycle and read-only table fingerprints |
| `simax/app.py` | Local HTTP boundary, API routes and static assets |
| `simax/static/` | Forms, navigation, tables, filters and visual styles |

## Persistence and execution

`data/simax.sqlite3` uses WAL and foreign-key enforcement. Schema version 2 retains sources, policies, runs, artifacts, audit, settings, schedule occurrences, and restore confirmations, and adds trigger state plus timestamped event receipts. JSON documents have relational keys for policy/source relationships and uniqueness. Passwords are stored only as environment-variable references.

One runtime owns the catalog using an OS file lock; one worker serializes backup and restore jobs. Accepted jobs are persisted before acknowledgment. Restart marks previously running work interrupted and resumes queued work. Allow active native operations to finish before stopping the server. A hard stop can leave partial files or partial restore effects; inspect them before retrying.

Daily, weekly and numeric five-field cron schedules share the same IANA wall-clock calculator for previews and execution. Repeated DST times run once at the first occurrence; nonexistent times are skipped. Only the latest due occurrence from the current local day can catch up after downtime. An edit's timestamp excludes earlier occurrences. Enqueue rechecks the policy revision within the SQLite transaction to reject a stale scheduler snapshot.

Occurrence keys persist across restarts. Daily/weekly policies use policy/day keys, preserving existing daily records; cron policies use policy/UTC-instant keys. An occurrence during an active backup for the source coalesces into that job and is audited. Scheduled jobs record their intended UTC time. Pausing prevents new enqueues; accepted jobs remain queued unless cancelled. The preview endpoint is read-only and searches up to eight years for up to five future occurrences. See [scheduling rules](scheduling.md).

## Event observation and intake

An event supervisor reconciles MQTT subscriptions and submits at most two independent table scans, leaving backup execution separate. Scans compare row and column fingerprints; they cannot recover transient changes or provide a database-wide transactional observation snapshot. Webhooks and MQTT require policy-bound HMAC signatures and recent timestamps. Event identities are retained for seven days; intake and pending state commit atomically. A pending follow-up survives an active source backup and waits for its policy cooldown. Dispatch commits the run and consumes pending state in one transaction. Policy edits invalidate earlier pending revisions.

MQTT uses QoS 1 with acknowledgments after persistence, clean sessions and reconnect/resubscribe. Invalid/retained messages are discarded. There is no durable offline broker replay guarantee. See [event trigger configuration, scope and failure semantics](event-triggers.md). SQLite v1 catalogs receive additive schema-2 tables; older releases reject the new catalog version.

## Backup completion

1. Inspect the source and native exporter.
2. Record export start as a conservative lower bound for the native snapshot time.
3. Stream SQL to a unique `backup.sql.partial` file.
4. Flush, compute SHA-256, and rename to `backup.sql`.
5. Flush and finalize the companion `manifest.json`.
6. Register the completed artifact and finish the run.

Partial exports never enter the restorable catalog. A crash after file finalization but before registration can leave an uncataloged backup; reconciliation/import is planned. Partial files remain for manual inspection. No automatic cleanup or retention runs.

Checksums verify bytes, not semantic completeness. External deletion or corruption is detected at restore preflight; background rescanning is not implemented. Catalog integrity records the last check, not a continuous guarantee.

PostgreSQL exports omit ownership/grants and cluster-global accounts/tablespaces. MySQL uses a transactional InnoDB export with routines/events/triggers; matching target definer accounts may be required. Quiesce source DDL during export. Selective objects and dependency closure remain unavailable until verified.

## Restore boundary

Only same-engine, same-major, empty dedicated targets labeled DISPOSABLE are accepted. Original source identity is checked against the immutable run record. Preflight verifies managed path, size, SHA-256, engine/version and target emptiness. Authorization expires after five minutes, is single-use, and requires typing the exact target name and acknowledging SQL execution.

Execution repeats checks and rejects changed target configuration. No concurrent target writers are allowed. PostgreSQL uses one transaction with stop-on-error; MySQL can leave partial changes. After replay, only table names are compared. Row contents, routines, constraints and application behavior still require operator verification; the UI labels the evidence accordingly.

A valid checksum does not make SQL safe. Routines and triggers may execute code or have external effects. Use trusted source databases and isolated targets. Production and replacement restores are disabled.

## Security and deployment

- Loopback-only, single trusted local operator. Shared authentication and roles are not implemented.
- Host validation, same-origin mutation checks, required application header, no CORS, and restrictive CSP.
- No shell execution for database commands. Conservative validation of connection identifiers.
- SQL inspection queries are sent as UTF-8 standard input, avoiding Windows argument code-page conversion. PostgreSQL client encoding is explicit; MySQL batch output is raw UTF-8.
- Only `SIMAX_SECRET_*` credential references are allowed. Inherited database-client overrides are removed; saved identity determines each command.
- Native tools receive passwords through their environment. The same OS user or an administrator may inspect that environment; a protected credential broker is future work.
- TLS identity verification is default. Operators may explicitly disable database TLS for a connection, including private-network remote servers; there is no automatic fallback or Tailscale detection. Native stderr is not persisted because it can expose SQL, data or credentials.
- The CLI loads the working directory's `.env` before constructing the app, or an explicit `--env-file`. Existing process variables win; variable interpolation is disabled. Parent directories are not searched, and the file is never served by the web app.
- OS permissions and protected volumes are required for plaintext backups and private metadata.
- Audit history is not tamper-evident compliance evidence.

Pagination, future schema migrations, stronger secret custody, independent worker deployment, and production packaging remain future work.
