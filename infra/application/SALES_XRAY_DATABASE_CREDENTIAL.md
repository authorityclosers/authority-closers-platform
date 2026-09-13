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
