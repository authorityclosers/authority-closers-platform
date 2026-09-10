# Local Studio video scanner pilot

The scanner is a separate, private VPS service for the isolated local upload acceptance path, not activation of uploads in staging or production. It does not alter WordPress, app routes, tenant data or payment/provider state. Official ClamAV 1.5.4 is pinned by digest; the non-root read-only container has 4 GiB RAM, two CPUs, bounded temporary storage/logs, and only a loopback port. Only signature databases persist.

The controller consumes an exact checksum-verified Git archive, retains immutable release files, and refuses implicit replacement of another scanner release. Readiness validates container bounds, mounted configuration, updater policy, live identity and clean/EICAR probes. It requires daily signatures no older than 48 hours and emits a 12-hour proof for the exact local SSH endpoint. This is not a guarantee against all malware.

Before packaging: 30 independent offline scanner tests passed; 10 launcher tests passed separately, including actual PowerShell opt-in evaluation. Independent review cleared the bounded scanner/controller/launcher changes after correcting writable signature storage and updater-policy validation. Real scanner activation, live signature verification and browser upload-to-playback are subsequent acceptance gates; these test results do not claim them completed.

Source references: [official Docker operation guidance](https://docs.clamav.net/manual/Installing/Docker.html), [ClamAV 1.5.4 security release](https://blog.clamav.net/2026/08/clamav-154-and-146-security-patch.html). The local upload pilot remains capped at 100 MiB source bytes and 8 GiB private storage; a short 4K fixture does not prove long-lecture acceptance.

## IPv4 health reconciliation (source-only correction)

A read-only check on 2026-09-10 reconciled an unhealthy Docker status with a
successful application-path scanner proof. The pinned image health script sent
`PING` to `localhost`; that container resolves `::1` first, while the reviewed
clamd policy deliberately binds its private TCP listener on IPv4. The identical
probe to `127.0.0.1:3310` returned `PONG`, and the owned SSH path independently
passed ClamAV version/daily-definition matching plus clean and EICAR probes.
This showed a persistent healthcheck false-negative, not permission to ignore
health.

The corrected source uses an explicit `127.0.0.1` PING/PONG healthcheck and
refuses to mint readiness evidence unless Docker reports `healthy`. The
controller now has bounded `upgrade` and `rollback` transitions that require
exact source and target release identities and immutable archive checks. It
reconciles only the named scanner service; a failed target health or functional
proof automatically restores and live-probes the exact source release. The one
named legacy pilot release may be restored for continuity but remains
`functional_only_health_unaccepted` and cannot mint a new proof.

An independent review found that stripping Docker endpoint environment
variables did not override a saved active CLI context. The controller now pins
every Docker command to `unix:///var/run/docker.sock` and rejects caller-supplied
host/context overrides, preventing proof or transition operations from being
redirected to another daemon.

Local verification after the correction: 48 scanner control-plane tests passed;
the adjacent launcher/readiness set passed 76 tests total; Ruff passed; and
`docker compose config` resolved one `scanner` service, the explicit IPv4
health command, and only the loopback `127.0.0.1:13310` publication. This source
has not been packaged, installed, restarted or applied remotely. Promotion
still requires a new immutable release/archive identity and an independently
reviewed controlled transition from the retained legacy release.
