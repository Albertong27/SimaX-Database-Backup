# Encrypted credentials and local keys

Enter database usernames/passwords, MQTT usernames/passwords and event signing secrets directly in the local app. Catalog schema 3 encrypts every JSON record body, including credentials copied into queued runs and restore confirmations. SQLite relational indexes retain record IDs, display names, statuses and receipt timestamps in plaintext. SQL backup files and exported manifests are separate artifacts and remain unencrypted.

The implementation uses [Fernet authenticated encryption](https://cryptography.io/en/stable/fernet/) from the pinned `cryptography` library. At each initialization SimaX checks for `DATA_DIR/credentials.key`. A fresh catalog gets a randomly generated key; subsequent starts reuse it. Replacing the key at every start would destroy access to saved records. Keys are atomically published without overwriting a concurrent initializer's key.

On Windows, the key file contains a [DPAPI current-user protected blob](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata). It requires the original Windows account and its DPAPI credentials, normally on the original computer. On Linux/macOS, the key file has mode `0600`; a newly created data directory has mode `0700`. Protect the data directory with OS permissions and full-disk encryption. This design does not protect against malware or an administrator executing as the runtime account.

The key and credentials are never put in browser localStorage. Passwords and signing secrets are omitted from all API responses, including job snapshots; only `*_saved` booleans are returned. Usernames remain visible in the connection editor, but are encrypted on disk. Blank password/secret fields on an edit preserve saved values. Clearing the MQTT username removes its stored broker password. New values apply immediately; already queued jobs retain their encrypted credential snapshots.

Decryption happens in runtime memory. Native PostgreSQL/MySQL tools receive passwords through their short-lived process environments, never command arguments; no `.env` file is needed. Usernames are native command arguments. MQTT receives decrypted credentials in memory. Normal startup does not load `.env`, and credential environment-reference fields are no longer accepted by the API. Optional non-secret CA-file paths and `SIMAX_DATA_DIR` can still be supplied in the process environment.

## Existing installations

Finish active jobs, then stop the old runtime. From the project directory, with updated dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m simax --data-dir data --migrate-env-file .env
.\.venv\Scripts\python.exe -m simax --data-dir data
```

The explicit migration reads the specified file without interpolation or process-environment overrides. It resolves database/MQTT/event secret references across current records and historical snapshots, encrypts records in a transaction, and advances the schema to 3. A missing required value aborts the catalog migration and preserves the original environment file. Migration refuses to run while the runtime lock is held.

All `SIMAX_SECRET_*` entries in the specified file are retained in encrypted storage, including unused entries, before removal from that file. Other file entries are preserved. An interrupted removal can be retried with the same command. Migration rebuilds SQLite pages and truncates WAL to remove old plaintext records from the active files. This is not secure erasure of filesystem snapshots, SSD remnants or previous manual copies. Existing historical catalog copies and `.env` copies outside this migration remain the operator's responsibility.

Changing an environment file after migration does not update saved credentials. Make future changes through the app. The signing helper uses `--data-dir` to unlock the saved policy under the same OS account; no secret arguments or environment file are required. Remote publishers should provision their shared signing key through their own secure credential store.

## Recovery and boundaries

Keep a consistent copy of the catalog **and** `credentials.key`, together with SQL artifacts. Stop SimaX before copying the catalog, or use SQLite's backup API to obtain a consistent snapshot. Windows recovery also requires the original DPAPI account/profile; copying just these files to another account or computer is not a portable recovery method. Portable key export and key rotation are not implemented in this release.

If an encrypted catalog's key is missing, corrupt, incompatible with the account or unable to authenticate a record, startup fails closed. SimaX never silently replaces that key. Restore the matching key/catalog and OS account. Older releases cannot open schema 3. Re-entering credentials alone cannot recover an encrypted catalog whose key has been lost.

Automated tests cover key persistence/concurrent creation, wrong keys and tampering, failed and successful imports, old snapshots, SQLite/WAL plaintext checks, secret-free API responses, edits preserving credentials, and native database backup/restore. CI runs the credential suite on both Ubuntu and Windows so filesystem permissions and DPAPI are exercised on their respective platforms.
