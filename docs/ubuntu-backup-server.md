# Ubuntu backup-server installation

This is a deployment template, not evidence that a production server has been configured. The runtime belongs on the separate backup server described in [MySQL recovery operations](mysql-recovery-operations.md). Confirm its Ubuntu release, MySQL release series, disk layout, private routing and time zone before installation. Ubuntu 24.04 with Python 3.12 is the supplied CI target.

## Install under a dedicated account

Provision a dedicated filesystem at `/var/lib/simax` with enough capacity for the chosen history and reserve. Mount it before enabling the service; if it is a separate mount, add `RequiresMountsFor=/var/lib/simax` in a systemd unit override so backups cannot silently land on the root disk. Enable volume encryption according to the host's recovery procedure. Use administrator-controlled, non-production SSH access.

After reviewing and transferring the desired project commit to `/opt/simax` (root-owned code), install Python and the MySQL **client matching the production release series**. The distribution's `mysql-client` may not match MySQL 8.4; select an appropriate trusted vendor package rather than mixing release series. The backup server does not require a MySQL server for normal backup operation; recovery drills belong on a separate isolated instance.

```sh
sudo apt-get update
sudo apt-get install python3.12-venv
sudo useradd --system --user-group --home-dir /var/lib/simax --shell /usr/sbin/nologin simax
sudo install -d -m 0700 -o simax -g simax /var/lib/simax
sudo python3.12 -m venv /opt/simax/venv
sudo /opt/simax/venv/bin/python -m pip install /opt/simax
sudo install -m 0644 /opt/simax/deploy/ubuntu/simax.service /etc/systemd/system/simax.service
sudo systemctl daemon-reload
sudo systemctl enable --now simax.service
sudo systemctl status simax.service
```

These are first-install commands; do not recreate an existing account or overwrite an existing data mount. The service creates the encrypted catalog and local key as `simax`. The unit uses `UMask=0077`, a private state directory and read-only system paths; [systemd's directory and filesystem controls](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html) describe their behavior. Allow only `/var/lib/simax` for runtime writes. Native clients must be installed on the service's PATH. For a private CA, install a readable CA certificate under `/etc/simax` and use a unit override such as `Environment=SIMAX_MYSQL_SSL_CA=/etc/simax/mysql-ca.pem`. Do not put passwords into the unit, command arguments, shell history or `.env`.

From the administrator workstation:

```sh
ssh -N -L 8765:127.0.0.1:8765 BACKUP_ADMIN@BACKUP_SERVER
```

Open `http://127.0.0.1:8765` on the workstation and enter the source credentials directly into SimaX. The management API remains loopback-only. Do not expose it through a reverse proxy or a public bind address. Create the two-hour policy initially paused; check the source, run one manual backup, validate a restore and confirm the time zone before enabling the schedule.

## Scheduling and monitoring

Use only SimaX's `0 */2 * * *` policy. Do not create a competing `mysqldump` cron job or `OnCalendar` backup timer. The service restarts on failure; after downtime SimaX catches up only the latest due occurrence in the current local day, coalescing active jobs. Inspect overdue alerts and gaps rather than assuming missed historical points were reconstructed.

Read safe runtime messages using `journalctl -u simax.service`. An independent monitoring system should run `/opt/simax/venv/bin/python /opt/simax/scripts/check_protection.py --policy POLICY_ID` locally and alert on exit 1/2, as well as monitor server reachability, filesystem utilization and immutable-copy freshness. Test notification delivery. No outgoing notification provider is configured by these instructions. SimaX has a single execution queue: long recovery drills can delay backups, so schedule representative drills carefully and inspect recorded queue time.

Before an upgrade or planned stop, wait until no jobs are queued/running. Stopping the unit can interrupt native SQL operations; a failed MySQL restore may leave partial data. Never retry against a partially restored target without inspecting and reprovisioning that disposable target. Back up the catalog/key, install a reviewed release, restart and check `/api/health/protection` and the UI. No host service has been installed by the development tests.

## Catalog, key and independent recovery copies

The Linux key is `/var/lib/simax/credentials.key`, readable only by its owner. Preserve it with the matching consistent encrypted SQLite catalog, SQL artifacts and manifests, in a separate encrypted offline/immutable recovery store. Stop the idle service before copying SQLite, or use the SQLite backup API; copying a live main file while ignoring its WAL is not a consistent backup. Restrict recovery-media access separately from the backup service account. Record the MySQL version, grants/definers, server/application configuration, CA material and recovery contacts outside production too.

For a Linux catalog restore, provision a clean supported host, restore matching catalog/key/artifacts, set ownership to the `simax` service account, restrict the key to `0600` and data directory to `0700`, and start SimaX only after validating the source/target network destinations. Protect against starting an old policy against an unintended endpoint. Verify the catalog unlocks and perform a restore drill before relying on it. Never generate a replacement key for an encrypted catalog.

The existing Windows development catalog uses DPAPI and cannot simply be moved to Ubuntu with its key file. Create a new Ubuntu catalog and provision credentials locally. Portable DPAPI key export and automated catalog import are not implemented. Keep the original Windows account/profile for its recovery. See [credential custody](credentials.md) for full limits.

Keep immutable/offline copies outside the service's writable filesystem and outside production's authority. A second disk mounted writable by SimaX is not immutable, and a replica is not protection against malicious DELETE statements.
