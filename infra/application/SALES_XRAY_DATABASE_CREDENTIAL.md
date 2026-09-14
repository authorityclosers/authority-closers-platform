# Hosted Sales Xray database credential

The dedicated hosted worker reads only the external file mounted at
`/run/ac-sales-xray/database-url`. The source-owned provisioning command is
`scripts/provision-sales-xray-database.py`; it accepts only `staging` or
`production` and derives the destination from the fixed path
`/etc/authority-closers/secrets/sales-xray/{environment}/database-url`.

Run it as root inside the existing Infisical child so `AC_DATABASE_URL` is
available only in that child process:

```sh
AC_INFISICAL_ENVIRONMENT=staging AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- \
  python3 /srv/authority-closers/application/releases/<reviewed-release-sha>/scripts/provision-sales-xray-database.py staging
```

Use the exact immutable reviewed release directory; do not resolve this tool
through a mutable `current-*` link during provisioning.

For production, use `AC_INFISICAL_ENVIRONMENT=prod` with the `production`
argument; the wrapper's Infisical environment name is `prod` while the fixed
destination and script environment name are `production`.
The wrapper supplies the value from the managed secret store; do not pass the
URL as an argument or write it to a rendered environment file. The command
accepts only the `postgresql+psycopg` private Compose profile with host
`postgres`, database `ac_platform`, and user `ac_runtime`. Owner, migrator,
backup, localhost, loopback, local fixture, and foreign-host URLs are refused.

The managed directory is root-owned and non-writable to unprivileged users.
The final file is a singly-linked regular file owned by UID `10001`, GID `0`,
mode `0400`. Creation is create-only and atomic; an exact existing file is an
idempotent success, while any differing bytes or metadata fail closed. Errors
and success output contain no URL, secret, path payload, hash, or digest.

Provision the file before the hosted Compose overlay is started. Rotation is a
separate create-new/update/restart/revoke operation and is outside this
create-only command.

## Validation of this implementation

The reviewed provisioner SHA256 is
`1e1ef8943f2e24e1e05fb11fd37800b4e0014dd2bbf0a205af612d9ab39ac1e0`.
Windows focused pytest passed16cases with7POSIX skips. A separate Linux-root
assertion harness passed6cases covering ownership/atomic replay, strict URL and
encoding, writable/foreign ancestors, symlinks and nonblocking FIFO refusal.
It used synthetic values exclusively in an ephemeral `/run` proof directory.
No actual credential, database, provider or `/etc` target was touched.

External receipts:
- D:/AC-authority-closers-release-audit/sales-xray-db-linux-proof-20260913214653.xml
- D:/AC-authority-closers-release-audit/sales-xray-db-source-receipt-20260913214653.txt

The application workflow also runs the complete provisioner pytest file in its
existing root-owned activation validation step. That new CI invocation is pending
the combined release run; the local six-case harness is not reported as CI pytest.

## Staging runtime credential rotation

The source-owned staging rotation command is `scripts/rotate-sales-xray-database.py`. It is staging-only and requires the existing root Infisical machine identity plus the fixed `/application` path. It reads current values in process, validates private runtime and migrator URL shapes, snapshots the `ac_runtime` role attributes and grants, changes only that role's password through the owner connection, and verifies a new runtime login with the same privilege snapshot. It then updates `AC_DB_RUNTIME_PASSWORD` and `AC_DATABASE_URL` in Infisical and atomically replaces the existing staging worker credential file. The production runtime password is compared in memory only; production is never updated.

Run it from the exact immutable release directory after reviewing the staging window:

```sh
AC_INFISICAL_ENVIRONMENT=staging AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- \
  python3 /srv/authority-closers/application/releases/<reviewed-release-sha>/scripts/rotate-sales-xray-database.py
```

The command refuses a missing or mismatched existing worker file, a foreign URL/role/host, an unsafe path, a concurrent rotation, or any privilege drift. It rolls the role, Infisical values, and worker file back on an update failure; if rollback itself cannot be proven, it fails closed with a generic message. It prints no URL, password, digest, exception body, or database result. A successful rotation still requires a separately reviewed Compose restart and candidate health proof before the old connection path is considered retired.

Validation of the rotation path: tests/infra/test_sales_xray_database_rotation.py passed 6 focused cases on the Windows development host. The tests use synthetic credentials and fake Infisical/database adapters, covering strict URL scope, no-secret argv, unchanged privilege snapshots, atomic file replacement, and rollback after a store failure. No actual Infisical, database, VPS, /etc, or provider target was touched.
The focused rotation file and existing provisioner file together passed 23 cases with 7 expected POSIX-only skips on Windows. The POSIX root-only path and the real Infisical/database operation remain pending operator review; this branch has performed no staging or production mutation.
