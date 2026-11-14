# What the owner's Telegram gets from releases

Owner, 15 Nov 2026, about 03:00 IST: "the delivery pipeline and the notifications I get are just
misleading on Telegram. I want that to be fixed." His standing rule (19 Oct) allows three kinds of
message only:

1. "vX LIVE": 3-5 plain bullets of what's new and a link, when the release reaches production;
2. real incidents, with their fix status;
3. the twice-daily summary.

No technical words, no review asks, no buttons that do nothing. The 48-hour audit behind this change
is in `docs/evidence/owner-telegram-audit-20261115.md`.

## How the release scripts speak now

Every release script talks through `ac-release-notice` (`infra/release/ac_release_notice.py`,
installed as `/usr/local/sbin/ac-release-notice`). The step text stays in each script's own log
unchanged, because the hooks and `promote402.sh` read those log lines.

| Command | Goes to | Used by |
|---|---|---|
| `step TEXT` | `/var/log/ac-notify.log`, plus the `dev` route if one is set up in another chat. Never the owner. | `ac-ship` (every phase and every "stopped"), `cutlist.sh`, `cutpatch.sh`, Play hook, web bundle failures |
| `live --version vX --title T` | The owner: one message per release, sent once per version | `ac-ship`, after the production check passes |
| `phones --version vX` | The same live message, edited in place to add one line | Web bundle hook, once phones can pick the release up |
| `blocked --version vX --what --who --next` | The owner, sent on purpose only | The orchestrator, when a release truly cannot ship without action |
| `incident --what --who --next` | The owner, sent on purpose only | The orchestrator, for a real production problem |

`blocked` and `incident` refuse technical words (exit 2) and never send the same notice twice. A step
the orchestrator is already retrying is never a `blocked`.

### The live note

```
✅ Sales X-Ray v1.60 is live

• Ask Dipak learning library (10 topics, 150 questions, 12 full lessons, saved lessons, next-call missions)
• Reports opens on Main and All Reports with search, lead-type and date filters and saved reports
• Home and Leads fixes (Leads count, New leads, Pending action, Today's list, Done today)
• Growth tiles balanced and tappable, hour chart in AM/PM
• Also: Didn't call with Undo; analysis time left shown in New analysis and Settings, per seller for owners; …

Open it: https://salesxray.authorityclosers.com
📱 The phone app picks this up by itself; no Play Store update needed.
```

- The bullets come from the release title's `;`-separated items. Items with engineering words (CI,
  PR, migration, commit ids and similar) are left out, and `left_out` in the log lists them. After
  four bullets, the rest go into one "Also:" bullet.
- To write the bullets by hand, put `/etc/authority-closers/owner-notes/<version>.txt` next to the
  play-notes and user-notes, one `- ` bullet per line (up to five). It wins over the title.
- The phones line is added to the same message when the web bundle is live. If the bundle is ready
  first, the line goes into the note when it is sent.

## For the orchestrator

- **A release you mark live by hand.** If ac-ship stopped but you checked production and wrote the
  "is live on production" line yourself (as for v1.54 and v1.56), also send the note:
  `ac-release-notice live --version vX.Y.Z --title-file /root/tNNNN.txt`
- **A release that cannot ship without action** (not a step you are re-running): send
  `ac-release-notice blocked --version vX.Y.Z --what "…" --who "…" --next "…"` in plain words. Say what
  is wrong for him, who is fixing it, and when he hears next.
- **Don't call `ac-notify-owner` for progress.** It still reaches the owner directly, and it now logs
  every send to `/var/log/ac-notify.log` with its caller.
- **Check what he got:** `sudo tail /var/log/ac-notify.log`. Each line is JSON: `kind`, `to` (owner,
  owner-edit, dev, log, refused), `ok`, `version`, `text`.

## The dev route

No Telegram route is set up (`/etc/ac-notify/routes.json` is empty), so until one is, steps reach
only the logs. A dev group gets them once someone with the owner's account types `/route dev` in that
group; the bot accepts route commands from the owner only. The tool never sends a step to the
owner's own chat, even when the dev route points there.

## Host files (not in this repository)

`infra/release/host-patches/owner-notices-20261115.patch` records the host-side edits. Each edit is
applied with `patch` and has a dated backup next to the file (`.bak-20261115-owner-notices`):

- `/usr/local/sbin/ac-ship`: `tell` sends a step; the production line sends the live note.
- `/usr/local/sbin/ac-notify-owner`: logs every send to `/var/log/ac-notify.log`.
- `/opt/release-comms/relcomms.py`: Sales X-Ray posts no longer fall back to the owner's ops chat.
  They are still written, and wait for the product's own bot and channel (`setup` + `flush`).
- `/root/cutpatch.sh`: cut steps are steps. `/root/cutlist.sh` was already log-only (orchestrator,
  14 Nov 21:05Z).

The two hooks in `infra/application/scripts/` get this change's diff applied in place, with the
same backups. The installed Play hook also carries a host-only change (the `play-major` forced
update, 3 Nov) that is not in the repository; applying the diff instead of copying the file keeps it.
