# Authority Closers in the shared Pulse (23 Oct 2026, AUT-2207)

On 23 Oct 2026 the owner approved moving Authority Closers' Pulse from its own install on ac into EA's shared Pulse on
ea, as its own organisation (`350ce338-d796-4de2-b17b-07cbc337f27a`). The move tool is
`scripts/data-changes/pulse-org-move.py`. This folder holds the server pieces installed around it, as installed. The
servers are the source of truth; update this copy whenever one of them changes.

| Where | Installed as | What it does |
|---|---|---|
| ea | `/usr/local/sbin/pulse-ac-tasks` (forced command), `/usr/local/sbin/pulse-ac-tasks-root` | AC's task route. One JSON request in, fixed task operations inside AC's organisation only, never SQL from the caller |
| ea | `/usr/local/sbin/pulse-org-export`, `/usr/local/sbin/pulse-org-export-root` | AC-only export of the shared Pulse (`pulse-org-move.py export`) streamed as a tar; organisations listed in `/etc/pulse-org-export.allow` |
| ea | `/usr/local/lib/pulse-org-move/pulse-org-move.py` | a copy of the move tool, which the export uses |
| ea | `/home/pulsesync/.ssh/authorized_keys`, `/etc/sudoers.d/pulsesync` | one key per route from ac (187.127.163.77): `ac-pulse-org-export` and `ac-pulse-tasks`; the old `ac-pulse-sync` line is removed |
| ac | `/usr/local/bin/ac-pulse-tasks` | the client of the task route (root: key `/etc/pulse/secrets/ac_tasks_ed25519`) |
| ac | `/usr/local/sbin/ac-pulse-gold-bridge`, `/usr/local/sbin/ac-pulse-sample-watch` | the Sales Xray gold-review bridge and the sample watcher, through the task route |
| ac | `/usr/local/sbin/ac-pulse-snapshot` (+ timer drop-in `nightly-shared-pulse.conf`, 21:40 UTC) | nightly AC-only export pulled from ea → gpg → AC Drive "AC Backups/pulse" (`pulse-shared-*`) |
| ac | `/usr/local/sbin/ac-pulse-redirect`, `ac-pulse-redirect.service` | 127.0.0.1:8090 (pulse.authorityclosers.com) → 301 to https://ac-pulse.estateautopilots.com |
| ac | `rotate-db-passwords` (run once, from `/root/ac-org-move`) | rotated the old install's four login-role passwords without printing them |

**The old install on ac** (compose project `pulse`, containers `pulse-pulse-1` and `pulse-postgres-1`) is frozen:
- the web container is stopped (restart policy: no);
- the database is `default_transaction_read_only = on`;
- the timers `ac-pulse-sync` and `ac-pulse-snapshot` (old hourly mode) are retired.

Keep it until 30 Oct 2026; removing it needs the owner's deletion approval.

**Rollback before people work in the shared Pulse:**
1. Stop `ac-pulse-redirect`.
2. On the old database, run `alter database pulse reset default_transaction_read_only`.
3. Run `docker start pulse-pulse-1`.
4. Remove AC's rows from the shared Pulse. That is a deletion, so it needs the owner's approval.

Tests: `tests/unit/ci/test_pulse_ac_shared.py` (the task route's request checks and SQL quoting, and the redirect).
