# Event-triggered backups

Table change, database change, webhook and MQTT policies request whole-database SQL backups. They do not provide incremental backups, replication, transaction-log archiving or point-in-time recovery. Redis remains planned.

## Shared execution rules

Choose a trigger in the policy form. The event coalescing window starts at the **first** event and does not move with subsequent events. Once it expires, the policy is eligible, subject to the configured minimum interval between event backup starts (60 seconds minimum, 300 by default). One pending request per policy accumulates a bounded count and the latest event identity.

If a backup for the same source is queued or running, the pending request waits. It becomes a follow-up because the active backup's snapshot may precede the event. Pending state and enqueue are transactional; accepted events survive restart. Failures or cancelled runs do not automatically replay consumed events; a new event or manual run is required. Multiple policies share the existing per-source concurrency guard; cooldown is per policy, not a global source rate limit.

Editing, pausing or re-enabling a policy invalidates pending events from the previous revision, with the policy edit recorded in the audit log. Already queued jobs retain their policy snapshots. Change-observation pending state is also invalidated when the source connection revision changes. Scheduled occurrences retain their previously documented coalescing behavior.

The policy list shows trigger health, pending count and the last check. A stopped runtime cannot observe or execute work. Status changes, first events in a pending group and queued runs are audited. Run details identify the trigger and coalesced count. Raw webhook/MQTT payloads, broker passwords and database rows are not stored in the event catalog.

## Table and database change observation

This implementation compares read-only fingerprints of visible base-table rows and column metadata on PostgreSQL and MySQL. Each table's rows are hashed in the database, sorted by hash, and reduced to a digest locally. Only row hashes pass through a temporary file, which is closed and removed after the scan. Stable ordering avoids triggering solely because row order changes. No source-side objects, SQL triggers, replication slots or database configuration changes are installed.

| Mode | Observed scope | Limits |
| --- | --- | --- |
| Table change | Named tables' persistent row contents and column definitions | Use preflight inventory names: `schema.table` for PostgreSQL; `table` for MySQL. A dropped/missing watched table marks the observer degraded. |
| Database change | Visible base tables, their persistent row contents and column definitions, table additions/removals | Does not watch objects outside the selected database or hidden by the account's metadata privileges. |

Observed effects include inserts, updates, deletes, truncation and column changes that remain until the next scan. Index and constraint definitions (beyond column nullability), routines, triggers, views, permissions, sequence counters and engine-global configuration are **not** observed. Those objects can still be included in the backup according to the normal native-export scope.

The first successful poll records a baseline without requesting a backup; use **Save and run first backup** for an initial recovery point. Restart preserves the baseline but marks an observation gap. A later poll can detect the remaining net change; it cannot reconstruct intervening changes. A source or policy edit establishes a new baseline. Errors retain the previous fingerprint and mark coverage degraded.

Polling is not transaction-log capture: changes reversed between polls can be missed. Each table scan is read-only, but a multi-table scan is not a single database-wide snapshot. Concurrent writes/DDL may produce another observation or a failed scan. Source downtime, host sleep, restarts and slow scans all create gaps. The UI marks overdue scans separately from normal polling.

Operators must explicitly acknowledge scanning cost. Defaults are 300 seconds between completed scans, with a 60-second minimum. At most two policies scan concurrently, up to 100 tables per policy, and each row-hash command times out after 35 seconds. Large tables may exceed this budget. Scans consume database CPU, I/O and sorting space and may take read locks; use appropriate intervals and ordinary scheduled backups for workloads unsuitable for scanning. Backups and MQTT reconciliation run independently of scans.

The observer needs SELECT access to every watched row and column metadata. PostgreSQL scans disable row-security filtering so restricted RLS access fails instead of silently hashing a subset. MySQL hides objects the account cannot see, so database-level completeness requires database-wide visibility and SELECT privileges; SimaX cannot infer invisible objects. Missing selected tables, permission errors and scan timeouts are degraded states, not unchanged-data evidence. Changes caused by an external restore are observed like any other changes; SimaX does not automatically restore as a result of a trigger, so there is no automatic backup/restore feedback loop.

## Signed webhooks

The endpoint is `POST http://127.0.0.1:8765/api/triggers/webhook/POLICY_ID`. It remains loopback-only alongside the management app. Use a local integration on the SimaX host; shared network ingress/authentication is not delivered by this milestone. Do not expose the management app through a proxy to make this endpoint public.

Enter a separate random signing secret of at least 32 bytes in the policy. It is stored encrypted, never returned in API responses, and takes effect without a restart. Leave the field blank when editing to retain the saved secret.

Send a UTF-8 JSON body containing only `event_id` (1–128 ASCII letters, digits, dots, underscores, colons or hyphens; first character alphanumeric). Maximum body size is 4096 bytes. Headers:

- `Content-Type: application/json`
- `X-SimaX-Request: 1`
- `X-SimaX-Timestamp: UNIX_SECONDS` (integer, within five minutes of the runtime clock)
- `X-SimaX-Signature: LOWERCASE_HEX_HMAC_SHA256`

The signature input is the policy ID, newline, decimal timestamp, newline, and the **exact request body bytes**. The secret is the HMAC key. This binds the request to one policy even if an operator reuses the same secret. Unknown payload fields cannot supply SQL, paths, credentials or other configuration.

HTTP 202 means the event was durably accepted, not that a backup completed. Duplicate event IDs are rejected with 409. IDs are deduplicated per policy across revisions for seven days from receipt. Expired timestamps or bad signatures return 401, invalid schemas 422 and oversized bodies 413. The receipt catalog is capped at 100,000 identities across all policies; saturation returns 503 until old receipts expire. Retry with the same ID and a fresh timestamp/signature after a transient failure. Configure callers to retry on delivery/storage errors, not authorization/schema errors.

Use the included helper from the project root:

```sh
python scripts/send_event.py webhook --policy pol_0123456789abcdef --event-id orders-commit-42
```

Use `--data-dir path/to/data` or `--base-url http://127.0.0.1:PORT` when needed. The helper unlocks the local encrypted catalog using the same OS account and reads the saved policy credentials; it does not read `.env`. The example policy ID must be replaced with a real saved policy ID. Synchronize publisher/runtime clocks. The helper does not print signing secrets.

## MQTT

Configure an explicit broker host/port, exact topic, optional broker username/password, and event signing secret. Broker credentials and the event signing key are separate. TLS with certificate/hostname verification is default; use `SIMAX_MQTT_CA_CERT` for a private CA. Plain TCP requires choosing the trusted-private-network transport explicitly. Wildcard topics are not accepted.

The subscriber uses Eclipse Paho, MQTT **3.1.1**, QoS **1**, and a **clean session**. Reconnect uses backoff and resubscribes. Subscription rejection or inability to obtain QoS 1 is degraded. Sessions end with the connection; there is no persistent offline queue/session expiry extension. Messages published while disconnected can be lost. Publishers must verify intake through SimaX's policy/run evidence and retry after gaps. A broker publish acknowledgment alone does not prove SimaX accepted the event.

Payloads are at most 4096 bytes and contain only `event_id`, integer `timestamp`, and a 64-character lowercase hexadecimal `signature`. The signature input is the policy ID, newline, timestamp, newline, and event ID (UTF-8). The same five-minute clock window and seven-day deduplication apply. This is deliberately different from the webhook's raw-body signing.

Retained messages, QoS 0 messages, other topics, bad signatures, expired events and malformed payloads cannot request backups. Invalid messages are discarded; valid duplicate deliveries are harmless. QoS 1 acknowledgments occur only after durable intake (or deliberate rejection/duplicate handling). Persistence failure disconnects without acknowledging and reports degraded intake; clean sessions still require publisher retries after reconnection.

```sh
python scripts/send_event.py mqtt --policy pol_0123456789abcdef --event-id sensor-batch-42
```

The helper uses the saved broker, transport, topic and credentials. Clear the broker username in the app to remove broker authentication; leave an existing password blank to preserve it. The helper publishes non-retained QoS 1 messages. External publishers must provision the shared signing key through their own secure credential store and implement the signature format above.

## Validation and upgrade

SQLite schema 2 adds trigger state and timestamped event receipts without rewriting existing source, policy, artifact or run records. Keep a consistent catalog backup before upgrades; older schema-1 releases reject schema 2 instead of silently ignoring pending events. Polling hashes and receipt retention are not backup retention or an audit compliance guarantee.

Automated isolated tests cover signature scope, replay, expiry, payload boundaries, restart persistence, coalescing, cooldown, active-backup follow-ups, policy/source edits, scan failures and schema upgrade. A scripted loopback MQTT broker exercises the real Paho network client, QoS acknowledgment, reconnect/resubscribe, duplicate/retained/wrong-topic rejection and persistence failure. It is a protocol integration fixture, not certification against every production broker. Live native tests cover PostgreSQL 17.11/MySQL 8.4.11 table/database fingerprints and real event-triggered exports using disposable servers; no Docker or user database is used.

References: [Eclipse Paho client behavior and limitations](https://eclipse.dev/paho/clients/python/docs/), [PostgreSQL binary hashing functions](https://www.postgresql.org/docs/18/functions-binarystring.html), [MySQL JSON construction](https://dev.mysql.com/doc/refman/8.4/en/json-creation-functions.html).
