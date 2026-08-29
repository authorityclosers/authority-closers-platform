# Authority Closers infrastructure handoff

Updated 2026-08-27 (Asia/Kolkata).

## Ready now

- VPS: `ac-kvm4-prod`, operator alias `ssh ac`.
- SSH: Cloudflare Access protects `ssh.authorityclosers.com`; the Access policy allows `admin@authorityclosers.com` and the local private key is used through `cloudflared`. Public TCP/22 is denied by UFW.
- Tunnel: `ac-kvm4-prod` routes SSH and the two internal health hostnames to the loopback-only service. The WordPress apex and `www` records were not moved.
- Host controls: UFW, Fail2ban, auditd, AppArmor, unattended upgrades, bounded journald, swap, Docker hardening, loopback-only Caddy, and the five-minute foundation health timer are active.
- Secrets: runtime and recovery configuration are separated in Infisical projects `AC Infrastructure Secrets` and `AC Human Recovery`. VPS and backup machine-identity client secrets were rotated and their old versions revoked.
- R2: private Standard buckets `authority-closers-backups-prod` and `authority-closers-objects-prod`; current usage is approximately 353 KB Standard storage, zero Infrequent Access, and far below the local operating envelope.
- Backups: encrypted Restic backup runs daily; restore/integrity drill runs weekly. The latest backup and restore drill passed after credential rotation.
- Resend: domain-restricted Sending-access key; the latest runtime test returned HTTP 200. Google Workspace remains the receiving system.

## R2 safety policy

The local fail-closed guard limits operations to 8 GiB Standard storage, 700,000 Class A operations/month, 7,000,000 Class B operations/month, and zero Infrequent Access. Cloudflare does not provide a hard provider-side free-tier spending cutoff, so Cloudflare billing alerts remain an additional control rather than a guarantee.

## Operator commands

```bash
ssh ac
sudo /usr/local/sbin/ac-foundation-health
sudo /usr/local/sbin/ac-infisical-verify
sudo systemctl start ac-r2-usage-guard.service
sudo systemctl start ac-restic-backup.service
sudo systemctl start ac-restic-restore-check.service
```

## Remaining gates before application development

1. Sign in to the Google Cloud project owner account for `ac-identity-production`, reset the existing OAuth client secret, and update `GOOGLE_OAUTH_CLIENT_SECRET` in both Infisical Production projects. The current browser identity did not have project access, so this was not changed automatically.
2. Complete Google Workspace DKIM generation when the Admin Console makes it available. Preserve the existing Google/legacy SPF senders until the old WordPress host is retired.
3. Before deploying an application, replace project-wide Viewer identities with workload-specific identities and path-level permissions; configure GitHub Actions OIDC only when the application repository and deployment workflow exist.
4. Migrate the Infisical Linux package source from Cloudsmith to `artifacts-cli.infisical.com` before the vendor retirement date shown by the CLI.

## Credential hygiene note

During setup, one diagnostic invocation exposed credentials in process output. The R2 S3 credentials, Resend sending credential, Cloudflare API tokens used for testing, and Infisical VPS/backup bootstrap credentials were rotated or revoked. Do not reuse any pre-rotation values. The Google OAuth client secret is the one remaining credential that must be reset before Google sign-in is used.

There is intentionally no universal plaintext “master key.” Recovery is through the Workspace/Infisical administrator account, the human-only recovery project, and the escrowed Restic passphrase.
