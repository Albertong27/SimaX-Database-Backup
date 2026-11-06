# SimaX Database Backup

A local database backup workspace by **Simply Smart X (SimaX)**, with a web interface and SQLite for configuration, job history, artifacts, and audit events.

**Status: working development preview.** Native backup and restore round trips are verified on Windows with PostgreSQL 17.11 and MySQL 8.4.11. See the [tested matrix and limits](docs/live-database-validation.md). Source data is not copied into the application's SQLite catalog.

## Start locally

Requires Python 3.12 or later. From the project directory:

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m simax
```

macOS / Linux:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m simax
```

Open [SimaX locally](http://127.0.0.1:8765). The catalog starts empty. No Node build step or external font service is required.

Use `python -m simax --port 8765 --data-dir data` to choose a port and runtime directory. The default is `data/` in the current directory. Keep the process and host running for schedules; closing the browser does not stop execution. An OS lock prevents two processes from owning one catalog.

At startup, SimaX creates a local encryption key if this is a new catalog, and reuses it on later starts. Database and MQTT credentials and event signing secrets are entered in the app and stored in encrypted catalog records. Windows protects the key with current-user DPAPI; other platforms use an owner-only key file. Normal startup no longer loads `.env`. See [credential storage, migration and recovery](docs/credentials.md).

## First backup and restore

1. Install `psql` and `pg_dump` for PostgreSQL, or `mysql` and `mysqldump` for MySQL, on the runtime's `PATH`. Adapter preconditions are PostgreSQL 14+ with a matching exporter major version, or MySQL 8.x with InnoDB tables. Only the exact versions in the tested matrix have live verification evidence.
2. Enter the database username and password in **Sources**. Passwords are never returned by the API; leave the password blank when editing to keep the saved value. Changes take effect without restarting.
3. Add a source in **Sources** and run **Check**. TLS identity verification is the default. For private certificate authorities, set `SIMAX_PG_SSL_ROOT_CERT` or `SIMAX_MYSQL_SSL_CA` to the trusted CA file. For a trusted private network such as Tailscale, explicitly select **No database TLS — trusted private network** when the database server does not support SSL. This disables database TLS for that connection; SimaX does not detect or configure the network's encryption.
4. Create a manual, scheduled or event-triggered policy; preview upcoming times for schedules, choose a local folder label, then run it. Inspect stages in **Runs** and integrity evidence in **Artifacts**. Quiesce schema changes during export.
5. For a recovery drill, add a separate empty database, used as a restore target and labeled `DISPOSABLE`. Preview the restore, type the exact target name, and acknowledge execution of trusted SQL.

SQL files are unencrypted. Protect the runtime directory with OS permissions and appropriate volume encryption. Existing policies retain backups indefinitely by default. Optional historical retention expires eligible copies only after a successful backup; pins and incident holds preserve evidence. See [MySQL recovery operations](docs/mysql-recovery-operations.md).

## Implemented now

- Eight design-aligned navigation areas, responsive layouts, local fonts, light/dark theme, and truthful empty states.
- Authenticated encryption of catalog records and persistent local keys, including credentials in queued jobs and restore confirmations.
- SQLite persistence, source create/edit/check, revisioned policies, audit export, filters, and saved freshness preferences.
- Manual/daily/weekly/five-field cron execution, time-zone-aware previews, durable queues, serialized jobs, duplicate coalescing, queued cancellation, and interrupted-run recovery.
- Table/database change polling, authenticated webhook and MQTT triggers, durable event coalescing and visible observation gaps. See [event setup and limits](docs/event-triggers.md).
- Two-hour MySQL policy preset, historical retention with pins/incident holds, protection health probe, and recorded recovery drill timings.
- Separate Ubuntu backup-server deployment template using the existing scheduler; no production deployment is included.
- Whole-database logical SQL export to one required local copy, staged finalization, companion manifest, and SHA-256 checks.
- Guarded same-engine restore (matching MySQL release series, no older target patch) to an empty disposable target, expiring single-use authorization, and execution-time rechecks.
- Table-name comparison after SQL replay. This does not verify row contents, every object type, or application behavior.

## Still planned

Oracle/SQL Server execution; selective objects and dependency closure; Redis triggers and log-based change capture; FTP/SFTP/S3/GCS; grouped SQL and encrypted binary; catalog import; immutable/offline copy automation; binary-log archiving/PITR; broader restore modes; active-job cancellation; shared authentication/roles; outgoing alerts; full recovery verification.

Unsupported execution modes are unavailable in the UI and rejected by the API. The original product scope remains in the PRD.

## Project documents

- [Product requirements document](docs/PRD.md)
- [Architecture and operational boundaries](docs/architecture.md)
- [MySQL backup-server and attack recovery](docs/mysql-recovery-operations.md)
- [Ubuntu service setup](docs/ubuntu-backup-server.md)
- [Scheduling rules and cron examples](docs/scheduling.md)
- [Encrypted credentials and key recovery](docs/credentials.md)
- [Event triggers and publisher setup](docs/event-triggers.md)
- [Implementation status and validation](docs/development-status.md)
- [Native database tests and compatibility evidence](docs/live-database-validation.md)

- [Contributing and branch workflow](CONTRIBUTING.md)
- [GitHub publication checklist](docs/github-setup.md)

## Local checks

Run with Python 3.12+, Git, and Node (for the syntax check only):

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q simax
node --check simax/static/app.js
python scripts/check_docs.py
git diff --check
```

The default suite uses real SQLite catalogs and controlled native-tool output; live tests are skipped unless explicitly enabled. `python scripts/live_tests.py` provisions fresh native servers and runs the real round trips when the required binaries are on PATH. It uses no Docker, existing database services, or production connections. See the validation document for Windows setup. GitHub Actions includes the default suite and wheel build on Ubuntu 24.04, plus pinned native database round trips on Windows 2025 after publication.

## Local access

SimaX binds to `127.0.0.1` and assumes one trusted local operator. There is no shared-user authentication; do not expose it through a proxy, tunnel, or public interface. Host/origin checks and a mutation header are not a substitute for authentication.

## License status

This project is intended for open-source publication. The license has not yet been selected; no open-source license grant is currently provided. Selecting a license and adding its full text are publication prerequisites.

Bundled fonts retain separate SIL Open Font License notices in [font licenses](simax/static/fonts/LICENSE.txt). The original supplied PDF and HTML design bundle are preserved in `docs/`.
