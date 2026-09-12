# Local Studio video scanner pilot

The scanner is a separate, private VPS service for the isolated local upload acceptance path, not activation of uploads in staging or production. It does not alter WordPress, app routes, tenant data or payment/provider state. Official ClamAV 1.5.4 is pinned by digest; the non-root read-only container has 4 GiB RAM, two CPUs, bounded temporary storage/logs, and only a loopback port. Only signature databases persist.

The controller consumes an exact checksum-verified Git archive, retains immutable release files, and refuses implicit replacement of another scanner release. Readiness validates container bounds, mounted configuration, updater policy, live identity and clean/EICAR probes. It requires daily signatures no older than 48 hours and emits a 12-hour proof for the exact local SSH endpoint. This is not a guarantee against all malware.

Before packaging: 30 independent offline scanner tests passed; 10 launcher tests passed separately, including actual PowerShell opt-in evaluation. Independent review cleared the bounded scanner/controller/launcher changes after correcting writable signature storage and updater-policy validation. Real scanner activation, live signature verification and browser upload-to-playback are subsequent acceptance gates; these test results do not claim them completed.

Source references: [official Docker operation guidance](https://docs.clamav.net/manual/Installing/Docker.html), [ClamAV 1.5.4 security release](https://blog.clamav.net/2026/08/clamav-154-and-146-security-patch.html). The source-owned Studio upload pilot now admits at most 2,000,000,000 decimal source bytes and retains an 8 GiB private storage ceiling; a short 4K fixture does not prove long-lecture acceptance.

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

## Frozen-main reconciliation note

The frozen main source at `87e71857a29eb4a6996e937a6047aa30e93bec4d` retains
the baseline pilot statements above. This worktree also retains the reviewed
IPv4 health correction, bounded upgrade/rollback controller, explicit local
Docker endpoint pin, and named legacy-release continuity rules below; those
controls are intentionally preserved when reconciling the later source.

## Release recovery review — 2026-09-11

Tracked in [issue 52](https://github.com/authorityclosers/authority-closers-platform/issues/52).
The scanner and its committed Compose dependency were transferred from the
single UI lane using explicit SHA-256 manifests; the original files remain
preserved. Independent review found that explicit rollback incorrectly required
the failing source to be running, healthy and responsive. Rollback now verifies
the retained source archive/controller, container identity, bounds, exact mount
paths and source policy without executing inside that failing source. Upgrade
still requires source runtime proof. The target still requires Docker health,
live clean/EICAR checks and fresh signatures before readiness can be minted;
the named legacy rollback remains functional-only and health-unaccepted.

Validation: `pytest tests/infra/test_media_safety.py -q` passed 56 tests. Added
cases exercise real static container validation for stopped, unhealthy and
apparently healthy but nonresponsive rollback sources, mandatory target proof,
and wrong-source rejection. Ruff lint and formatting checks pass. These are
local unit/controller results; live transition evidence remains pending.

Live Docker 29.7.2 metadata then identified a fixture mismatch before packaging:
the three binds appear in `Mounts`, while the Compose tmpfs configuration is
in `HostConfig.Tmpfs`. The controller now validates those exact sets separately,
including unique and bounded tmpfs options. The bounded local logger may report
its documented default `compress=true`; max-size 5m/max-file 2 remain mandatory,
and unrelated logging options remain rejected. [Docker's local logging
documentation](https://docs.docker.com/engine/logging/drivers/local/) confirms
compression is enabled by default. The prior 56-test result predates this
adjustment; final tests and review are recorded in the subsequent release entry.

Final scanner candidate `3a16f0a`: **64 tests passed in 0.84 seconds** after
the Docker metadata correction; Ruff lint and formatting checks passed.
Independent rereview cleared the rollback and runtime-shape changes with no
remaining actionable findings. Packaging, CI and live transition are still
required; the unit result does not claim deployed scanner readiness.
