# Implementation status

## Applied on 2026-08-26

- Ubuntu host fully patched and rebooted into kernel `6.8.0-138-generic`; no further updates or reboot are pending.
- Named `suyash` administrator with key-only SSH; root and password SSH disabled.
- UFW, Fail2ban, auditd, AppArmor, unattended upgrades, bounded journald, sysstat, swap, and conservative sysctl/limits enabled.
- Docker Engine and Compose from Docker's official repository with bounded local logs, live restore, no-new-privileges, an empty Docker group, and a `DOCKER-USER` ingress guard.
- `/srv/authority-closers` runtime layout installed.
- Digest-pinned, loopback-only Caddy health endpoint and internal OpenTelemetry collector running as non-root, read-only, resource-limited containers.
- Named Cloudflare Tunnel `ac-kvm4-prod` running under a dedicated, capability-free system account with four healthy QUIC edge connections and a catch-all 404 route.
- Cloudflare Access protects `ssh.authorityclosers.com` with the `AC VPS SSH Admin` policy for `admin@authorityclosers.com`; local `ssh ac` uses `cloudflared access ssh` and the VPS firewall denies public TCP/22.
- The tunnel routes `ssh.authorityclosers.com` to SSH and `infra.authorityclosers.com` plus `infra.dipakvishwakarma.com` to the loopback health service; the WordPress apex and `www` records remain on the existing host.
- `https://infra.dipakvishwakarma.com/healthz` published through the tunnel to loopback-only Caddy, externally returning HTTP 200 with security headers and `Cache-Control: no-store`.
- Five-minute host timer validates Docker, both foundation containers, loopback health, the connector, and the full public Cloudflare request path.
- Cloudflare `dipakvishwakarma.com` origin certificate validated, edge mode changed to Full (strict), minimum TLS raised to 1.2, TLS 1.3 retained, and Always Use HTTPS enabled.
- Resend test domain `notify.dipakvishwakarma.com` verified with DKIM, SPF, MX, and DMARC; a delivery probe reached Resend's test sink with final status `delivered`.
- Cloudflare R2 activated; private Standard buckets `authority-closers-backups-prod` and `authority-closers-objects-prod` created with automatic Asia-Pacific placement.
- No public bucket domain, application writer, migration, Data Catalog, SQL, or Infrequent Access storage is enabled. The current retained encrypted foundation backup is approximately 353 KB in the backup bucket.
- The current long-lived Cloudflare R2 account token has Object Read & Write limited to the two AC buckets and the VPS IPv4 address; its credentials passed reversible write/read/delete probes in both buckets.
- VPS rclone upgraded to the official stable release `v1.75.0`; the probe explicitly disables bucket creation and uses R2's `auto` region.
- Conservative R2 cost policy and fail-closed usage guard added at 8 GiB Standard storage, 700,000 Class A operations, 7,000,000 Class B operations, and zero Infrequent Access usage.
- Historical secret-free infrastructure source was published privately as `authorityclosers/authority-closers-infrastructure` and installed on the VPS from immutable commit snapshots under `/srv/authority-closers/releases/`.
- Existing apex and `www` continue to route to the old VPS.

## Applied on 2026-08-27

- Infisical organization projects are organized as `AC Infrastructure Secrets` and a separate `AC Human Recovery` project. Production provider configuration is stored in the infrastructure project; machine bootstrap material and the generated Restic passphrase are stored in the human-only recovery project.
- Project-level machine identities were created for VPS runtime, backup, agent operations, and GitHub Actions preparation. They are permanent, Viewer-scoped identities; path-level least privilege should be tightened before application production.
- The AC Google OAuth client secret was added to Infisical Production without placing the JSON file in the repository.
- The fresh R2 account token is restricted to the two AC buckets, Object Read & Write, Forever TTL, and the VPS IPv4 address. Because the VPS also has IPv6, R2/Restic systemd services are explicitly restricted to IPv4; the host's IPv6 remains enabled.
- R2 object write/read/delete succeeded in the backup bucket, Restic repository initialization succeeded, one encrypted foundation snapshot was created, and a restore plus integrity check succeeded.
- R2 usage guard runs every 30 minutes and is also a fail-closed preflight for each backup. The latest check reports 352,857 Standard bytes, zero Infrequent Access bytes, and operation counts far below the declared envelope.
- Daily encrypted Restic backups and weekly restore drills are enabled with 7 daily, 4 weekly, and 6 monthly retention windows. Secret material is excluded from the backup source set.
- VPS Infisical CLI bootstrap is installed and verified through a no-value-printing wrapper. `ssh ac` remains the operator entry point.
- Runtime, R2 guard/probes, Resend checks, and Restic backup/restore jobs use dedicated Infisical machine identities with short-lived injected configuration; only identity bootstrap values remain on the VPS.
- Resend API authentication succeeded; `authorityclosers.com` sending is enabled, its Resend DNS records are verified, and the latest scoped-key delivery test to `rsuyash123@gmail.com` was accepted by Resend with HTTP 200. Receiving remains Google Workspace's responsibility.
- `https://authorityclosers.com/` still returned HTTP 200 after the changes; no WordPress DNS cutover was performed.

## Explicit gates

- The supplied Cloudflare API token remains read-only for tunnel and DNS writes; future automation requires a least-privilege replacement token.
- Cloudflare Free Bot Fight Mode challenges GitHub-hosted runners, so the GitHub external-health schedule is disabled instead of weakening protection or accepting a false-green 403. Cloudflare security events identified the service and matching runner requests.
- The originally supplied R2 key is read-only in practice and was not persisted. The replacement production token is bucket-scoped, IP-restricted, and stored in Infisical; operational jobs receive it only through short-lived injection.
- Cloudflare has no hard R2 free-tier spending cap. The local guard is a deployment gate, not an account billing stop; workloads that bypass the guard could still incur overages.
- Production secrets are in Infisical; runtime and operational jobs use short-lived injection. The previous root-only all-secrets export remains only as a transitional recovery artifact until an independent recovery check permits its removal.
- Backups are enabled only after the R2 probe, usage guard, Restic initialization, encrypted snapshot, and restore drill all succeeded.
- Public TCP/22 is denied by UFW. The Cloudflare Access SSH path was independently verified after the lock-down and is the operator management path.
- No Authority Closers application, database, queue, or product source has been deployed.

## Deliberate follow-up gates

- Google Workspace DKIM generation is waiting on Google's 24–72 hour post-domain-activation window. Do not remove the existing Google/legacy SPF senders until WordPress and old-host sending are explicitly retired.
- The Google OAuth client secret remains stored for future application work, but its Cloud Console project is not accessible in the current signed-in browser identity; rotate it before using Google sign-in in a product.
- Cloudflare does not provide a hard R2 billing cutoff. The local guard is fail-closed for the declared envelope, but it cannot stop an unrelated workload or a direct Cloudflare write from creating overage.
- The current Infisical machine identities are project-level Viewer identities on the free plan. VPS and backup bootstrap client secrets were rotated and old secrets revoked on 2026-08-27. Before application production, split projects or path permissions and issue workload-specific identities.
- GitHub Actions OIDC/deployment wiring remains intentionally unconfigured because no Authority Closers application repository or image promotion workflow is in scope yet.

## G0 reconciliation opened on 2026-08-30

- The active VPS release is `infra-22fa9d9`, but the live backup, restore, usage-guard, and Infisical operational files match historical working-tree files that were not included in that immutable release.
- The complete secret-free working tree was snapshotted into `authorityclosers/authority-closers-platform` under `infra/vps-foundation` with provenance. The next release must be produced from a reviewed commit in that canonical repository.
- CI now rejects mutable Compose image references and validates all operational scripts.
- Host hardening now refuses to reset the firewall without an active Cloudflare connector unless temporary public SSH is explicitly requested. A separate, confirmation-gated `lockdown` phase removes TCP/22 after independent Access-path verification.
- Initial foundation targets are RPO <= 24 hours and repository-restore duration <= 4 hours. The restore drill reports observed snapshot age and duration; full application recovery and side-effect reconciliation remain G1 gates.
- Host packages are now a separately versioned exact-package baseline. Runtime releases cannot mutate APT state and fail unless the recorded baseline matches policy.
- New releases require a full 40-character reviewed commit and are materialized from an exact Git archive; working-tree and untracked files cannot enter a trusted release ID.
- Infisical/rclone versions and checksums are release content, are reconciled on rollback, and are covered by backup/isolated-restore evidence.
- Docker ingress rules are lifecycle-bound to Docker and continuously revalidated by a one-minute systemd timer; IPv4 and IPv6 UFW numbered-rule fixtures protect the TCP/22 lockdown parser.
- Every mutating bootstrap phase must now run from the checksum-verified exact Git archive; the official Ansible path no longer copies a mutable working payload.
- Baseline verification compares the complete live package manifest to the recorded baseline, restore validation anchors operational binaries directly to release-policy hashes/versions, and rollback recreates plus health-checks the target Compose foundation before changing `current`.
