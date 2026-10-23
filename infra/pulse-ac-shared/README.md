# Authority Closers in the shared Pulse (23 Oct 2026, AUT-2207)

On 23 Oct 2026 the owner approved moving Authority Closers' Pulse from its own install on ac into EA's shared Pulse on
ea, as its own organisation (`350ce338-d796-4de2-b17b-07cbc337f27a`). The move tool is
`scripts/data-changes/pulse-org-move.py`. This folder holds the server pieces installed around it, as installed. The
servers are the source of truth; update this copy whenever one of them changes.

| Where | Installed as | What it does |
|---|---|---|
| ea | `/usr/local/sbin/pulse-ac-tasks` (forced command), `/usr/local/sbin/pulse-ac-tasks-root` | AC's task route. One JSON request in, fixed task operations inside AC's organisation only, never SQL from the caller; plus `project` (work_project_save), `check` (task_check_set) and `chat` into channels listed in `/etc/pulse-ac-tasks.chat-allow` (today AC Leadership, for Align 3's release cards) |
| ea | `/root/ac-org-move/ac-pulse-contacts-import` (run once, AUT-2210) | AC contacts through Pulse's own API (`/api/v0/settings/types`, `/api/v0/contacts`) as the owner, on a short-lived organisation-switch session that is signed out at the end; used for the Sales X-Ray Play testers |
| ea | `/usr/local/sbin/pulse-org-export`, `/usr/local/sbin/pulse-org-export-root` | AC-only export of the shared Pulse (`pulse-org-move.py export`) streamed as a tar; organisations listed in `/etc/pulse-org-export.allow` |
| ea | `/usr/local/lib/pulse-org-move/pulse-org-move.py` | a copy of the move tool, which the export uses |
| ea | `/home/pulsesync/.ssh/authorized_keys`, `/etc/sudoers.d/pulsesync` | one key per route from ac (187.127.163.77): `ac-pulse-org-export`, `ac-pulse-tasks`, `ac-pulse-forward`; the old `ac-pulse-sync` line is removed |
| ac | `/usr/local/bin/ac-pulse-tasks` | the client of the task route (root: key `/etc/pulse/secrets/ac_tasks_ed25519`) |
| ac | `/usr/local/sbin/ac-pulse-gold-bridge`, `/usr/local/sbin/ac-pulse-sample-watch` | the Sales Xray gold-review bridge and the sample watcher, through the task route |
| ac | `/usr/local/sbin/ac-pulse-snapshot` (+ timer drop-in `nightly-shared-pulse.conf`, 21:40 UTC) | nightly AC-only export pulled from ea → gpg → AC Drive "AC Backups/pulse" (`pulse-shared-*`) |
| ac | `ac-pulse-forward.service` | AC's own address: 127.0.0.1:8090, behind AC's Cloudflare tunnel for pulse.authorityclosers.com, is an SSH forward to the shared Pulse on ea (127.0.0.1:4002). The key `/etc/pulse/secrets/forward_ed25519` can only forward there (`restrict,port-forwarding,permitopen="127.0.0.1:4002"`, from ac, no shell) |
| ac | `/usr/local/sbin/ac-pulse-redirect`, `ac-pulse-redirect.service` (disabled) | the 23 Oct interim 301 to https://ac-pulse.estateautopilots.com, replaced by the forward when the owner asked for AC's own domain |
| ac | `rotate-db-passwords` (run once, from `/root/ac-org-move`) | rotated the old install's four login-role passwords without printing them |

**The old install on ac** (compose project `pulse`, containers `pulse-pulse-1` and `pulse-postgres-1`) is frozen:
- the web container is stopped (restart policy: no);
- the database is `default_transaction_read_only = on`;
- the timers `ac-pulse-sync` and `ac-pulse-snapshot` (old hourly mode) are retired.

It is kept frozen and intact, by the owner's decision of 23 Oct, as the likely first node of the federation (EST card "Pulse federation", P2). Don't remove it.

**Addresses** (`pulse.org_domain`): `pulse.authorityclosers.com` is AC's only address (primary, password sign-in). The interim `ac-pulse.estateautopilots.com` was removed on 23 Oct 08:20 UTC, both its route and its row.

To skip the forward's detour through ac, the owner can add a tunnel connector on ea in AC's Cloudflare account (or the Pulse team can build Cloudflare for SaaS custom hostnames) and stop `ac-pulse-forward`.

**Rollback before people work in the shared Pulse:**
1. Stop `ac-pulse-forward`.
2. On the old database, run `alter database pulse reset default_transaction_read_only`.
3. Run `docker start pulse-pulse-1`.
4. Remove AC's rows from the shared Pulse. That is a deletion, so it needs the owner's approval.

Tests: `tests/unit/ci/test_pulse_ac_shared.py` (the task route's request checks and SQL quoting, and the redirect).
