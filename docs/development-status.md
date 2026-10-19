# Development status — 0.1.0 preview

Date: 2026-10-19. Current branch: `feat/flexible-schedules`, based on `feat/private-network-connections`. The PRD remains the target product definition; this milestone does not claim its whole scope is complete.

| Area | Delivered | Remaining |
| --- | --- | --- |
| Management | Eight design-aligned pages, source/policy forms, preflight, run controls, filters, preferences, audit export | Shared administration and delete/archive flows |
| Storage | SQLite v1, durable queue and transactional metadata | Future migrations, pagination, catalog recovery/import |
| Engines | PostgreSQL 17.11/MySQL 8.4.11 native SQL round trips verified on Windows; Oracle/SQL Server connection records | Broader engine/platform/version matrix; Oracle/SQL Server execution |
| Triggers | Manual, daily, weekly and numeric five-field cron; IANA zones and upcoming-run previews | Change, webhook, MQTT and Redis |
| Scope | Whole database with documented native-export limits | Individual objects, dependencies, schema/data-only modes |
| Destinations | One required local copy | FTP/SFTP/S3/GCS, multiple copies, transfer-only retries |
| Formats | Single SQL plus manifest | Grouped SQL and authenticated encrypted binary |
| Restore | Empty disposable target, expiring authorization, repeated checks, table inventory | Production/original targets, mappings, selection, full data/behavior verification |
| Lifecycle | SHA-256, interrupted-job recovery, queued cancellation | Retention/deletion/pinning, active cancellation, background integrity rescanning |
| Administration | Single operator, audit history, freshness notices | Sign-in, roles, outgoing alerts and key management |

## Validation

- Local result: 63 automated tests passed, including weekly/cron schedules, preview validation, DST gaps/folds, sparse leap-day schedules, restart deduplication, coalescing, stale-revision rejection, concurrent policy edits and legacy daily compatibility. The five live-test cases are opt-in and skipped by the default suite. Python compilation, JavaScript syntax and documentation checks passed.
- Schedule browser result: Monday/Friday selection, local offset previews, weekly save/reopen, cron editing, impossible-date errors, six-hour previews, save without running and pause passed in an isolated catalog with its worker disabled. No database connections were made.
- Earlier browser smoke result: connection creation/persistence, missing-tool preflight, policy creation/run failure, desktop and 390px layouts passed; no browser console errors were observed.
- API/service tests use real SQLite and a controlled adapter. Coverage includes persistence, policy snapshots, duplicate prevention, partial export exclusion, DST schedules, cancellation, corruption, authorization/replay, target rechecks, path containment, and single runtime ownership.
- Native argument tests ensure passwords stay out of command arguments and inherited client overrides are removed.
- Browser checks use a separate `build/ui-check` catalog; schedule checks use `build/ui-schedules-20261019` with the worker disabled; normal user data is separate.
- Python compilation and JavaScript syntax are checked locally. GitHub Actions runs the suite and builds a wheel after publication.
- Live native result: PostgreSQL 17.11 passed four tests (one MySQL-only test skipped); MySQL 8.4.11 passed five tests. Source and target were separate native processes on private loopback ports, with generated credentials and fresh data directories. Docker was not used for these tests.
- Fixed Windows Unicode query handling by feeding UTF-8 SQL through standard input, explicitly setting PostgreSQL client encoding, and using raw MySQL batch output. Live fixtures cover non-ASCII identifiers, emoji, binary data, JSON, null/empty values, identities, views, indexes, constraints, routines, triggers, and disabled MySQL events.
- See [live database validation](live-database-validation.md) for reproducible commands, scope, and limitations. The product's restore evidence still reports table-inventory validation; fixture-specific data/behavior checks are test assertions, not a new general verification feature.

## Next acceptance milestone

1. Expand the live matrix to Linux, TLS identity checks, least-privilege accounts, and larger/concurrent workloads.
2. Implement configurable data/object verification and recovery drills beyond table inventories.
3. Implement dependency closure before enabling selective objects.
4. Add remote storage, event triggers and encrypted output in separate reviewed branches with failure and recovery tests.

A GitHub remote is configured. This milestone has not been pushed or validated by hosted CI. The owner still needs to select a project license before public publication.
