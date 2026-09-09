# Three-app release wiring — local source verification

Date: 2026-09-08. Existing `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform` worktree.

## Implemented

- Immutable `authority-closers-coach-web` image joins API, Learner and Admin in
  the exact-SHA workflow build/publish/export. The strict 14-field manifest binds
  Coach runtime, OCI transport and registry digests. Missing, wrong-repository or
  mismatched Coach values fail admission. Existing storage ceilings and immutable
  tag, archive, source, image and migration checks are retained.
- Profiles select `learner[-staging]`, `admin[-staging]`, `coach[-staging]` app
  origins and exact `ac-{environment}-coach` edge aliases. Installer env isolation,
  image verification, startup/wait, rollback stop and deployment evidence include
  Coach. Admin and Coach unauthenticated probes require 307 to exactly same-host
  `/login`, without following redirects, then a 200 login page.
- Caddy proxies the six named app hosts to separate web services, preserving the
  existing shared API and security/log-redaction boundary. Legacy `app` and
  `staging` learner pages redirect temporarily (302 GET/HEAD). Old `/v1`, including
  OAuth callbacks with query credentials, and unsafe methods stop with no-store
  410/sign-in-again; they are not redirected or credential-proxied. No apex/www
  matcher or WordPress origin change was made.
- Windows staging verification checks the Coach image and exact login redirect,
  canonical learner origin, legacy transition and unchanged WordPress boundary.
- Staging public-film composition accepts only the old/new exact staging learner
  origin. Signed URL origin follows the selected setting; five-minute TTL,
  provider hold and no canonical Watch evidence remain unchanged. The API-only
  fixture overlay gives Coach no fixture mount or media activation.

Root owns `Dockerfile.web` and `compose.yaml`; the other agent owns versioned
backup parity and historical/new image manifests. This slice did not edit them.

## Actual checks

- Combined release/archive/controller/fixture-overlay/media suite:
  **217 passed, 7 skipped** in 35.93s. Four skips require a local Caddy binary or
  Docker daemon for real adaptation; three require POSIX atomic file-mode proof.
- Executed local Bash profile, rollback and exact redirect-destination harnesses;
  PowerShell Coach sign-in probe runs against no-network fixtures. Real Compose
  config-only override test passed without starting containers.
- Complete Python mypy: **157 files clean**. Scoped Ruff lint/format, Bash `-n`,
  PowerShell parser, workflow YAML/README Prettier and `git diff --check` passed.

No deploy, restart, image build/push, SSH, DNS/provider configuration, database or
account mutation was performed. Live Caddy adaptation is not claimed. Shared
edge cutover/rollback must be coordinated with the matching application release;
the application installer alone cannot restore an independently changed Caddy
configuration. Exact Google callback registration remains an operational gate.

## 2026-09-09 transactional cutover closure

The earlier limitation above remains historical evidence for the 2026-09-08
source state. The release transaction now owns independently versioned staging
and production selectors and closes the two release-blocking findings:

- Foundation and application installers share one non-blocking release lock.
  Each environment selector must resolve to a root-owned, mode-`0444`,
  route-only projection whose release identity, full checksum manifest and
  bytes match its immutable foundation/application owner. Caddy mounts only the
  selector and projection directories read-only; no application release tree,
  state directory or secret path is exposed to its UID/GID `1000:1000` runtime.
- A target environment first enters its release-owned no-store 503 route.
  Database writers are fenced before backup/migration; runtime access and web/API
  startup happen only between repeated maintenance-route proofs, with the worker
  stopped. Pre-exposure failure may restore the verified backup, previous app
  link and its matching route. Once ingress can accept writes, any later failure
  instead reselects and verifies maintenance ingress, stops all application
  services, fences writers and appends forward-recovery evidence. It never
  restores the backup or selects an older app after accepted writes are possible.
- Prepared, committed and forward-recovery evidence use unique names and atomic
  no-clobber moves. Backup capture also uses a unique private path; an unverified
  partial dump is removed rather than retained as recovery evidence.
- The trusted PowerShell controller selects `staging` or `production`, verifies
  the exact environment's six containers and public routes, keeps the staging
  OAuth mutation probe staging-only, and re-proves the unchanged WordPress apex
  and `www` boundary. CI now requires the dedicated Studio draft/revision
  PostgreSQL suites and fails closed when its real Docker transport proof cannot
  run.

Actual verification after these changes:

- Focused application release/archive/controller/runtime/transport suite:
  **177 passed, 6 skipped** in 49.39s. The skips are only unavailable local
  Docker/Caddy capabilities; CI fails rather than skips the required Docker
  cases.
- On the VPS, the fresh Linux foundation transaction harness passed its
  exact-archive install, shared-lock rejection, cross-environment selector
  rejection and injected rollback checks. Its temporary directory was removed.
- A separate VPS Docker proof ran the current pinned Caddy image as
  UID/GID `1000:1000` with no network, read-only root, dropped capabilities and
  only bounded tmpfs plus the three reviewed mounts. Caddy followed both
  absolute selector links through the route-only projection and validated the
  complete modular configuration. Its temporary directory was removed.
- Bash syntax, PowerShell parser, scoped Ruff format/lint, Prettier and
  `git diff --check` passed.

This addendum records source/test readiness only. At the time it was written,
no candidate commit, workflow artifact, foundation/application installation,
DNS/Access change or staging/production acceptance had yet occurred.

## 2026-09-09 exact-candidate CI parity correction

Workflow run `34365367103` checked out candidate
`a391dfa4299197d66606c13de35aed4b3203182f`. Its database migration, privilege,
backup-role, seed, catalog-locking and Studio PostgreSQL parity gates passed, as
did the capacity simulation. The aggregate suite then stopped packaging after
three stale registry assertions failed: one fresh-migration test still named
migration `0019`, the practice populated-upgrade fixture stopped at `0021`, and
the explicit registry set omitted the practice and Studio command models that
are already in migrations `0020`-`0023`.

The correction keeps the historical seeded upgrade stages, then migrates to the
Alembic script directory's single current head and proves that exact revision is
installed. The explicit permanent-table registry now includes the eleven
practice/focus tables and `catalog_authoring_commands`. It does not change a
migration, model or runtime behavior.

Actual focused checks after the correction:

- Model-registry file: **3 passed**.
- Fresh learning migration/head/append-only guard case: **1 passed** against a
  random disposable loopback PostgreSQL schema.
- Populated `0019` through current-head migration and autogenerate-drift case:
  **1 passed** against a separate random disposable loopback PostgreSQL schema.
- Scoped Ruff format/lint and `git diff --check` passed.

No image was packaged from the failed run, and no VPS installation or DNS change
was attempted from that candidate.

Workflow run `34367814630` then validated replacement candidate
`90e40001bc93527d686bdd51a8498f0a4b35af70`, including the complete aggregate
suite, and built all four release images. Publication stopped at the exact Linux
operations-image runtime proof, before tags or an artifact, but that controller
collapsed every already-fixed `GateError` reason into one generic message. The
diagnostic boundary now maps Docker argument prefixes to fixed phase labels and
prints only those internal `GateError` messages. It still never renders Docker
arguments, subprocess output, runtime responses, environment values, or
unexpected exception details. The focused controller/probe suite passed
**50 tests**; scoped Ruff format/lint and `git diff --check` also passed. This is
diagnostic hardening, not an image-runtime pass or release approval.
