# Authority Closers VPS Operations

## Access

- Preferred operator: `suyash` using Ed25519 public-key authentication.
- Root SSH and password authentication are disabled.
- Public TCP/22 is denied by UFW. The private management path is Cloudflare Access SSH through the `ssh.authorityclosers.com` hostname.
- Do not add ordinary operators to the `docker` group; use `sudo docker`.

The human control plane is `admin@authorityclosers.com` in Infisical. Use the `AC Infrastructure Secrets` Production project for runtime configuration and `AC Human Recovery` Production for machine bootstrap credentials and the Restic passphrase. There is intentionally no single plaintext “master key”; the admin account plus the human-only recovery project are the recovery path.

Cloudflare Access protects the SSH application with the `AC VPS SSH Admin` policy. The local alias is:

```sshconfig
Host ac
  HostName ssh.authorityclosers.com
  User suyash
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  ProxyCommand cloudflared access ssh --hostname %h
```

Keep `cloudflared` installed on the operator workstation. A successful `ssh ac` test proves the Access policy, tunnel, local key, and UFW lock-down are all working together.

For a fresh host, use the Ansible playbook with the reviewed archive path/SHA/release ID in `reviewed-release.yml`. It verifies the remote checksum, extracts only that archive, verifies its embedded Git commit and paths, and executes every bootstrap control from the extracted payload. Public TCP/22 is an explicit, temporary bootstrap exception:

```yaml
ac_release_id: foundation-<full-reviewed-git-sha>
ac_release_archive_local: /absolute/controller/path/ac-foundation-<full-reviewed-git-sha>.tar
ac_release_archive_sha256: <reviewed-archive-sha256>
```

```bash
ansible-playbook -i <inventory> ansible/playbooks/bootstrap.yml \
  --extra-vars @reviewed-release.yml --extra-vars ac_bootstrap_phase=baseline
ansible-playbook -i <inventory> ansible/playbooks/bootstrap.yml \
  --extra-vars @reviewed-release.yml \
  --extra-vars '{"ac_bootstrap_phase":"harden","ac_allow_public_ssh_bootstrap":true}'
```

After a second operator session independently proves Cloudflare Access SSH, remove the exception:

```bash
ansible-playbook -i <inventory> ansible/playbooks/bootstrap.yml \
  --extra-vars @reviewed-release.yml \
  --extra-vars '{"ac_bootstrap_phase":"lockdown","ac_cloudflare_ssh_verified":true}'
```

Never run the lock-down phase on the strength of the same SSH session that performed the bootstrap.

## Runtime layout

- Active immutable release: `/srv/authority-closers/current` -> `/srv/authority-closers/releases/foundation-<full-40-character-git-sha>`
- Compose manifests: `/srv/authority-closers/current/compose/`
- Protected configuration: `/srv/authority-closers/env/`
- Durable state: `/srv/authority-closers/volumes/`
- Staged backups: `/srv/authority-closers/backups/`
- Released operational material: `/srv/authority-closers/current/runbooks/`
- Recorded host baseline: `/etc/authority-closers/os-baseline.env` and `/var/lib/authority-closers/baselines/`
- Release-scoped toolchain evidence: `/var/lib/authority-closers/toolchains/foundation-<full-git-sha>.env`
- Root-only Infisical bootstrap: `/etc/authority-closers/secrets/infisical-bootstrap.env` (mode `600`; contains only machine-auth bootstrap values)
- Transitional recovery export: `/etc/authority-closers/secrets/production.env` (mode `600`; do not use for runtime jobs and remove only after an independent recovery check)

## Foundation commands

```bash
sudo docker compose \
  --env-file /srv/authority-closers/current/config/release/foundation-images.env \
  -f /srv/authority-closers/current/compose/foundation/compose.yaml ps
sudo systemctl status cloudflared
sudo systemctl status ac-docker-firewall.timer
sudo systemctl status ac-foundation-health.timer
sudo journalctl -u ac-foundation-health.service --since today
sudo /usr/local/sbin/ac-foundation-health
sudo AC_PUBLIC_HEALTH_URL=https://infra.dipakvishwakarma.com/healthz \
  /usr/local/sbin/ac-validate-foundation
sudo /usr/local/sbin/ac-infisical-login
sudo /usr/local/sbin/ac-infisical-verify
sudo /usr/local/sbin/ac-resend-check
```

## Public ingress

- Tunnel: `ac-kvm4-prod`
- Public health URL: `https://infra.dipakvishwakarma.com/healthz`
- Origin target: `http://localhost:8080`
- Caddy is bound only to loopback; ports 80 and 443 remain closed at the VPS.
- The remotely managed tunnel configuration includes a terminal HTTP 404 rule.
- The connector token is root-owned at `/etc/cloudflared/tunnel-token` and readable only by the dedicated `cloudflared` group.
- Restart with `sudo systemctl restart cloudflared`, then validate both the local and public health URLs.
- The one-minute `ac-docker-firewall.timer` removes duplicate managed rules and inserts established-connection acceptance plus public-ingress drop as rules 1 and 2 in both IPv4/IPv6 `DOCKER-USER`, before Docker's terminal `RETURN`. The five-minute `ac-foundation-health.timer` checks that ordering, Docker, both foundation containers, loopback health, the connector, and the complete public Cloudflare path.
- The GitHub-hosted external probe is intentionally disabled while Free Bot Fight Mode challenges GitHub runner IPs. Do not disable Bot Fight Mode or broadly allow GitHub address ranges merely to make that check green.

## R2 cost and activation gate

R2 is active and the following private Standard buckets exist in Cloudflare's automatic Asia-Pacific placement:

- `authority-closers-backups-prod`
- `authority-closers-objects-prod`

Cloudflare R2 does not provide a hard free-tier spending cap. The repository therefore sets a conservative operating envelope of 8 GiB Standard storage, 700,000 Class A operations per month, 7,000,000 Class B operations per month, and zero Infrequent Access storage. The authoritative policy is `config/r2/free-tier-policy.conf`.

The current pre-platform recovery export is root-only at `/etc/authority-closers/secrets/production.env` and is deliberately excluded from Restic source paths. Runtime, R2 guard, probes, and backup/restore jobs use short-lived Infisical injection through identity-only `/etc/authority-closers/secrets/infisical-bootstrap.env`. Before enabling any additional writer:

1. Supply a rotated metrics-capable Cloudflare API token only through the process environment.
2. Run `scripts/r2-usage-guard.sh`; treat API, unknown-operation, or threshold failures as a deployment block.
3. Use separate bucket-scoped Object Read & Write credentials for backups and application objects.
4. Run `scripts/r2-probe.sh`; it requires both buckets to exist, performs reversible write/read/delete tests in both, and leaves no probe object.
5. Configure Cloudflare account budget email alerts as an additional notification layer. Alerts are not hard caps.

Restic is enabled with the current IP-restricted R2 credential, a human-escrowed passphrase, the usage guard, and successful restore drills. `ac-r2-usage-guard.timer` runs every 30 minutes; `ac-restic-backup.timer` runs daily; `ac-restic-restore-check.timer` runs weekly. The metrics evaluator distinguishes a present empty dataset (valid zero) from a missing field/account/dataset (hard failure). Do not enable public R2 domains, Infrequent Access, Data Catalog, SQL, Sippy, Super Slurper, or another ingestion path without a new cost review.

Useful checks:

```bash
sudo systemctl start ac-r2-usage-guard.service
sudo systemctl start ac-restic-backup.service
sudo systemctl start ac-restic-restore-check.service
systemctl list-timers --all | grep -E 'ac-(r2|restic|foundation)'
```

The backup captures `/srv/authority-closers`, managed host configuration, baseline/toolchain records, released Infisical/rclone binaries, `/usr/local/sbin`, `/usr/local/libexec/authority-closers`, and Docker volumes while excluding `/etc/authority-closers/secrets`. Retention is 7 daily, 4 weekly, and 6 monthly snapshots. The weekly drill restores into an isolated no-exec target and verifies the restored release against the independently installed immutable release, the OS baseline record and complete dependency graph, toolchain hashes, installed-file content/modes/ownership, shell/config syntax, Compose resolution, secret exclusion, snapshot age, restore time, and a repository integrity sample. Restored binaries are never executed by the credentialed drill.

## Infisical runtime injection

The VPS has the Infisical CLI and a root-only bootstrap wrapper:

```bash
sudo /usr/local/sbin/ac-infisical-login
sudo /usr/local/sbin/ac-infisical-verify
sudo /usr/local/sbin/ac-infisical-run -- sh -c 'exec your-command'
sudo /usr/local/sbin/ac-infisical-run-backup -- sh -c 'exec backup-command'
```

The wrappers exchange Universal Auth credentials through a root-owned environment/stdin pipe, expose the short-lived token through `INFISICAL_TOKEN`, remove the bootstrap credentials before the workload starts, and never place either credential or token in process arguments. The VPS bootstrap file is identity-only; use the separate backup identity for backup jobs and separate projects/paths for each future workload.

## Immutable foundation release

The release installer accepts only a full reviewed Git commit and never overwrites an existing release. Build the archive on the trusted workstation from the exact checked-out commit:

```bash
release_sha="$(git rev-parse HEAD)"
git archive --format=tar --output="ac-foundation-${release_sha}.tar" \
  "$release_sha" -- infra/vps-foundation
release_archive_sha="$(sha256sum "ac-foundation-${release_sha}.tar" | awk '{print $1}')"

sudo AC_RELEASE_ID="foundation-${release_sha}" \
  AC_RELEASE_ARCHIVE="/absolute/path/ac-foundation-${release_sha}.tar" \
  AC_RELEASE_ARCHIVE_SHA256="$release_archive_sha" \
  /path/to/reviewed/infra/vps-foundation/scripts/bootstrap-host.sh runtime
```

The trusted controller verifies the archive before any remote extraction. The installer then verifies the SHA-256 and embedded Git commit again, rejects unexpected archive paths and non-regular entries, requires the complete bootstrap payload to equal that archive, generates a release content manifest, reconciles Infisical/rclone to binary hashes in the release policy, installs every explicitly declared script and unit, recreates and health-checks the target Compose foundation, and only then changes `current`. A transaction snapshot restores the previous binaries, managed files, symlink, Compose project, firewall, and timers if any post-mutation gate fails. Provider writers remain disabled until the separate `activate r2-jobs` gate succeeds.

Resend uses a domain-restricted Sending-access key. A send test returning HTTP 200 is the expected runtime check; delivery-log lookup is intentionally unavailable to a sending-only key. Google Workspace remains the receiving system for both domains.

The Infisical runtime and backup Universal Auth client secrets were rotated on 2026-08-27. If either bootstrap identity must be rotated again, create the replacement first, update the recovery project and root-only VPS bootstrap atomically, run `ac-infisical-verify`, then revoke the old client secret.

## Patch procedure

1. Review pending Ubuntu, Docker, and Cloudflare package updates.
2. Create a new `AC_OS_BASELINE_ID` and update every changed exact version/key checksum in `config/release/` through review and CI.
3. Confirm fresh backup, restore, and rollback evidence.
4. Run the reviewed `baseline` phase during a maintenance window. It snapshots the prior hold set, temporarily unholds only packages managed by the old/new baselines, installs and verifies the new exact graph, then holds the new graph. A failure restores the prior managed hold set. Never use an ad hoc `dist-upgrade` in a release phase.
5. Reboot if `/var/run/reboot-required` exists, then run the complete local and external validation suite.

## Rollback

- Host configuration archives are under `/root/ac-bootstrap-backups/`; each has exact package and package-hold sidecars for recovery.
- Restore only the required configuration subtree; do not overwrite unrelated current state.
- Validate `sshd -t` before restarting SSH.
- Keep an established SSH session open until a fresh session passes.
- To roll back a foundation release, run the installer from the already verified target release with its own full release ID. It revalidates the recorded OS package set, re-installs that release's host manifest, reconciles its binary-pinned toolchain, recreates the target Compose foundation, verifies local health, and only then changes `current`:

```bash
sudo AC_RELEASE_ID=foundation-<previous-full-git-sha> \
  /srv/authority-closers/releases/foundation-<previous-full-git-sha>/scripts/install-foundation-release.sh
```

## Non-negotiable deployment rule

Never deploy with `git pull` or compile product code on this VPS. Deploy reviewed OCI image digests with externalized configuration and a documented rollback digest.
