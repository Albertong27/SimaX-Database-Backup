# MySQL backup server and attack recovery

## Deployment contract

The requested workload is MySQL 8 on Ubuntu, currently below 1 GB, with a full backup on another server every two hours. Peak hours are 09:00–18:00 and the required maximum downtime is 15 minutes. The exact MySQL release, infrastructure and peak-hour time zone have not been supplied. Asia/Jakarta is the client time-zone default, **not a confirmed deployment time zone**. No production deployment or production recovery-time acceptance has been performed.

Run SimaX on the **separate backup server**, pulling the database over a restricted network connection. Its local destination is then on the backup server. No production SSH key, agent or filesystem mount writes to the backup server. This deployment uses the existing local storage adapter; it does not implement SFTP/cloud uploads. Keep the backup host, its administrators, service identity and storage credentials separate from production. Allow only backup-server-to-database traffic for the required DB port; deny production-to-backup management and storage access. Manage SimaX through an administrator SSH tunnel to its loopback listener. Verify these firewall rules before enabling the policy.

The supplied [systemd unit](../deploy/ubuntu/simax.service) runs one SimaX scheduler. Do not add a cron job, systemd calendar timer or production-side job that also performs the same backups. systemd keeps the service running; SimaX schedules the backups. Monitoring may run independently because it is read-only.

## Consistent full logical backups

The MySQL adapter requires InnoDB tables and a `mysqldump` client from the same release series as the server (8.0 versus 8.4). It exports schema, rows, views, triggers, routines and events using `--single-transaction --quick`, disables table locking, omits tablespace metadata and GTID-purged changes, and encodes binary values as hex. Normal transactional writes can continue; prevent DDL, table renames and truncation during export. A logical export is not a backup of MySQL accounts, grants, server configuration, plugins or external files. Source/target definer accounts and other prerequisites must be recorded separately. [MySQL documents these consistency limits and privileges](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html).

Have the DBA supply a dedicated account restricted to the database and backup server address. Confirm SELECT and SHOW VIEW coverage, TRIGGER/EVENT access for those objects, and routine-definition visibility appropriate to the exact minor version (SHOW_ROUTINE is available from 8.0.20). Do not blindly grant global administrative privileges to bypass an export failure. MySQL's TRIGGER and EVENT privileges also permit object changes: this is a least-privilege backup account, not a promise of a strictly read-only account. Keep its credentials only in SimaX's encrypted catalog on the backup server. Restore credentials belong to a different isolated server and must not permit access to production.

Use TLS identity verification with a trusted CA. An explicitly configured private-network connection without database TLS remains supported, but requires verified network isolation/encryption. SimaX does not configure Tailscale or firewall rules. The unknown production version must be checked before choosing the Ubuntu MySQL client package. Restores require the same release series and a target patch no older than the source; compatibility beyond the tested versions is not certified.

## Policy and historical retention

Create a MySQL source using **Sources**, entering credentials locally through the SSH tunnel. Use **Check** and a manual first backup. In **New backup policy**, choose that source and apply **Use two-hour MySQL preset**:

| Setting | Preset and meaning |
| --- | --- |
| Trigger | Existing five-field cron, `0 */2 * * *`, all day including overnight |
| State | Paused until the operator confirms configuration and time zone |
| Retention | Keep every copy for at least 30 days and always keep the newest 12 copies |
| Freshness | Alert when the latest export-start recovery point is older than 150 minutes |
| Recovery target | Settings default: 15 minutes for measured technical drills |

The 150-minute threshold is the two-hour interval plus 30 minutes of operational grace; it is not a 150-minute backup interval or a guaranteed RPO. At 12 full copies/day, 30 days is about 360 dumps. Capacity must be based on measured SQL size, not the database's reported size: hex-encoded BLOBs expand, and additional offline/immutable copies need more storage. Keep room for a new dump, partial exports, catalog, logs, and restoration workspace. The free-space reserve defaults to 2 GiB and is adjustable under Settings. The check blocks a new export below the reserve; it cannot predict the final export size or prevent all disk-full failures.

Retention is opt-in; old policies keep their existing keep-all behavior. Cleanup runs only after a newly finalized, checksum-verified successful backup using the unchanged policy and source configuration. Failure, a changed policy/source revision, a paused policy, or **Incident preservation hold** prevents that cleanup. The age rule checks both creation and snapshot times. Pinned artifacts, the newest-copy floor, active restore jobs and unexpired restore previews are protected. Previous source endpoints are not automatically expired when a connection is repointed. The preview shows eligibility under the saved rules, not a promise of immediate deletion.

Cleanup deletes only the owned SQL and manifest files; it rejects linked paths, directory escapes and unexpected files. A durable `deleting` record makes an interrupted cleanup unavailable for restore; the next successful backup can retry. Expired metadata stays visible in the catalog and audit history. Pins and holds protect against SimaX retention, **not an attacker with backup-server filesystem access**.

## Failure and freshness visibility

The overview shows policy-specific missing/stale recovery points, failed or interrupted backups, prolonged queued/running jobs, incomplete retention, and low free space. The latest file's existence and size are checked; a full checksum is checked before restore. A new failed export never advances the recovery point. The runtime has no built-in email/SMS delivery.

An external monitor on the backup host can run:

```sh
/opt/simax/venv/bin/python /opt/simax/scripts/check_protection.py --policy POLICY_ID
```

Exit 0 means the selected policy is enabled/current, the runtime is running and storage is above reserve. Exit 1 means attention is required; exit 2 means unreachable/invalid runtime response. Without `--policy`, every configured policy must be enabled and current. The equivalent loopback endpoint is `GET /api/health/protection`, returning HTTP 200 or 503. Connect these failures to an independent alerting system and test an unreachable runtime and a deliberately failed disposable backup. Poll every few minutes; monitor the backup host itself externally too, because a dead host cannot alert itself. Do not expose the management listener to make it monitorable.

## Timed restore and the 15-minute target

Use **Restore** to a clean, separate instance with the appropriate MySQL release and an empty database marked DISPOSABLE. Inspect the SQL's origin and prerequisites, run preflight, type the target name and authorize replay. SimaX rechecks identity, emptiness, size and checksum, then records queue time, execution time and accepted-job-to-finish time. The run page and downloadable recovery JSON report compare that technical interval to the configured 15-minute target, including queue delay. A failed restore never passes that comparison.

The timed interval excludes incident detection, operator decisions, preflight before authorization, rebuilding hosts, application validation, credentials/network changes and traffic cutover. SimaX automatically compares table inventory; this is not general row/data or application verification. Therefore a fast technical drill does **not** certify 15-minute production downtime. Do not restore unreviewed, possibly malicious routines into a privileged server with production connectivity. Keep the drill host isolated, disable its event scheduler, and use no production write credentials.

Before accepting the peak-hour target, run a representative drill from the **actual backup server** to a provisioned recovery host with the actual schema/data volume, storage, network path and comparable load. Capture incident-start, clean-point selection, host readiness, authorization, SQL completion, exact data/application checks, credential rotation, routing cutover and service-ready times. Include realistic operator response and queue delays. A proposed 15-minute budget is 2 minutes containment/point selection, 2 minutes preparation, 7 minutes replay, and 4 minutes validation/cutover; these are planning allocations, not measured results. If the total exceeds 15 minutes, pre-provision recovery capacity and remove bottlenecks before declaring readiness. Do not simply change the reported target.

The opt-in native test provides a reproducible synthetic throughput measurement:

```sh
python scripts/live_tests.py --engine mysql --benchmark-mib 128
```

It creates fresh loopback source/target instances, populates 128 MiB of BLOB payload, backs up and restores through SimaX's encrypted catalog, and checks every payload hash, row count, byte count and identity sum. Reports are saved to `build/live-*/mysql-recovery-benchmark.json`, with exact server/client versions and host platform. Sizes up to 1024 MiB are supported, but even a 1 GiB synthetic test does not replace a production-representative drill. No Docker or existing database services are used. See [validation evidence](live-database-validation.md).

## Attacks, immutable copies and PITR

When compromise is suspected: isolate the compromised application/host, apply a retention hold, pin known-good copies predating the suspected intrusion, preserve logs, and identify the last clean recovery point. Never blindly restore the newest dump: it may contain malicious changes. Recover into a clean isolated server, verify critical rows and application invariants, rotate exposed credentials, fix the entry point, and only then approve application cutover. SimaX deliberately does not automate production overwrite or routing changes.

Full dumps alone lose changes after the chosen snapshot: normally up to roughly two hours plus export/operational delays, and potentially much more when the last clean point is older or backups have failed. Replication can copy malicious deletes and corruption; it is not an independent historical backup.

Add an independently administered immutable/object-lock or offline copy of SQL, manifests, catalog and recovery materials. Use a separate copy identity and retention authority that production **and the SimaX service account** cannot use to delete those copies. Test object-lock retention and access denial from production, and test offline media recovery. SimaX does not yet upload or enforce immutable retention; an independently managed storage process is required. Protect plaintext SQL with encrypted volumes and encrypted off-host transport/storage. Retention holds alone do not create immutability.

**Binary-log archiving and point-in-time replay are not implemented.** They are the next recovery capability if the business needs a clean point between two-hour full snapshots. A complete implementation requires snapshot-aligned file/position or GTID coordinates, continuous off-host raw log archiving, rotation/reconnect handling, gap and lag detection, retention longer than the oldest retained base, protected keys for encrypted logs, and tested replay stopping before the malicious transaction. This release does not capture synchronized coordinates, so do not pair a casual `SHOW BINARY LOG STATUS` query with a dump and claim PITR. MySQL's [remote log backup facilities](https://dev.mysql.com/doc/refman/8.0/en/mysqlbinlog-backup.html) and [event-position recovery](https://dev.mysql.com/doc/refman/8.0/en/point-in-time-recovery-positions.html) describe the building blocks. Do not purge source logs before confirming archive continuity. Do not automatically replay unreviewed attack transactions.

## Deployment inputs still required

- Exact production MySQL version, database name, table engines, measured dump size, schema-change windows and routine/definer requirements.
- Backup-server Ubuntu release, private address, storage capacity/mount, network route and CA/private-network choice; confirm no production-side management/storage access.
- Administrator access for installation and locally provisioned DB credentials. Never send plaintext passwords or keys in chat.
- Confirmation of the scheduling/09:00–18:00 peak-hour time zone; 30-day history and the 150-minute alert threshold; an incident decision maker and alert destination.
- A clean isolated restore host, representative dataset/load, application validation and cutover plan, and a complete timed drill demonstrating the 15-minute target.
- Independent immutable/offline copy location, deletion authority, catalog/key recovery owner and successful recovery test.

Use the [Ubuntu setup guide](ubuntu-backup-server.md) once those inputs are ready.
