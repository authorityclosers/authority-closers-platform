# Canary marker, retention and capacity exclusions

AUT-108 slice 1 adds append-only `conversation_canary_submissions`, linked to acquisition usage. A tenant-scoped SQL EXISTS predicate excludes marked recordings before retention selection and from owner recording/byte caps. Global storage still includes them.

Migration `20260929_0052` maps to `ac-postgres-parity-v32` and 104 tables in all three backup/restore catalogues. Historical mappings remain unchanged; install matching foundation tools before deploying this head. Parity compares table row counts, not every value or a live restore.

Local proof: 5 canary tests pass (SQLite build, PostgreSQL append-only history, earlier canary skipped while ordinary recording is erased, both owner caps, global cap); 7 registry/drift checks and 89 release tests pass. Downgrade refuses with `forward-only`. Ruff format/check and mypy pass; three catalogue checks agree on v32/104.

Dev: migrated the sandbox from 0051 to 0052 using `~/.config/acdev/database.env`. `http://127.0.0.1:8100/health/live` and `/health/ready` return alive/ready. No errors appeared in the sampled dev API log. The web remains at https://salesxray-dev.authorityclosers.com; this slice has no UI change. No separate dev retention service is running, so ongoing worker-log verification is unavailable.

Local limitations: broader retention/authority tests fail during native C1 fixture setup; FFmpeg/FFprobe are absent. Root-only parity tests skip and passwordless sudo is unavailable. CI supplies those prerequisites; its result is recorded on the PR. No real audio, provider calls, staging, or production changes.
