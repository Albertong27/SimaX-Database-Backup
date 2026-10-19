# Development status — 0.1.0 preview

Date: 2026-10-19. Branch: `feat/web-foundation`, based on `docs/initial-prd`. The PRD remains the target product definition; this milestone does not claim its whole scope is complete.

| Area | Delivered | Remaining |
| --- | --- | --- |
| Management | Eight design-aligned pages, source/policy forms, preflight, run controls, filters, preferences, audit export | Shared administration and delete/archive flows |
| Storage | SQLite v1, durable queue and transactional metadata | Future migrations, pagination, catalog recovery/import |
| Engines | PostgreSQL/MySQL native SQL adapters; Oracle/SQL Server connection records | Live engine certification; Oracle/SQL Server execution |
| Triggers | Manual and daily IANA schedules | General cron, change, webhook, MQTT and Redis |
| Scope | Whole database with documented native-export limits | Individual objects, dependencies, schema/data-only modes |
| Destinations | One required local copy | FTP/SFTP/S3/GCS, multiple copies, transfer-only retries |
| Formats | Single SQL plus manifest | Grouped SQL and authenticated encrypted binary |
| Restore | Empty disposable target, expiring authorization, repeated checks, table inventory | Production/original targets, mappings, selection, full data/behavior verification |
| Lifecycle | SHA-256, interrupted-job recovery, queued cancellation | Retention/deletion/pinning, active cancellation, background integrity rescanning |
| Administration | Single operator, audit history, freshness notices | Sign-in, roles, outgoing alerts and key management |

## Validation

- Local result: 27 automated tests passed; wheel packaging, Python compilation, JavaScript syntax and documentation checks passed.
- Browser smoke result: connection creation/persistence, missing-tool preflight, policy creation/run failure, desktop and 390px layouts passed; no browser console errors were observed.
- API/service tests use real SQLite and a controlled adapter. Coverage includes persistence, policy snapshots, duplicate prevention, partial export exclusion, DST schedules, cancellation, corruption, authorization/replay, target rechecks, path containment, and single runtime ownership.
- Native argument tests ensure passwords stay out of command arguments and inherited client overrides are removed.
- Browser checks use a separate `build/ui-check` catalog; the user's normal `data/` catalog starts empty.
- Python compilation and JavaScript syntax are checked locally. GitHub Actions runs the suite and builds a wheel after publication.
- PostgreSQL/MySQL clients are absent and the development host's Docker daemon is unavailable. No live database backup/restore compatibility result is claimed.

## Next acceptance milestone

1. Provision isolated PostgreSQL/MySQL fixtures.
2. Exercise native round trips with Unicode, binary values, generated identities, views, constraints, routines, triggers and events.
3. Compare definitions, row contents and application behavior, then publish a tested server/client version matrix.
4. Implement dependency closure before enabling selective objects.
5. Add remote storage, event triggers and encrypted output in separate reviewed branches with failure and recovery tests.

No remote repository or hosted CI run is configured. The owner still needs to select a project license and GitHub organization before public publication.
