# Owner Telegram audit, 12 Nov 21:00Z to 14 Nov 21:20Z (48 hours)

Why: the owner said on 15 Nov 2026, about 03:00 IST, "the delivery pipeline and the notifications I
get are just misleading on Telegram."

## How it was rebuilt

Nothing logs what the owner's Telegram receives: `ac-notify-owner` and `ac_telegram.send` keep no
record. So each message was rebuilt from its sender's own log:

- **`/var/log/ac-ship.log`:** `ac-ship`, `cutlist.sh`, `cutpatch.sh` and `promote402.sh`. Every
  `tell` line also went to the owner; `say` lines did not. Lines are counted once by timestamp and
  text, because the nested `tee` writes each line twice.
- **`/var/log/ac-web-bundle-after-release.log`** and **`/var/log/ac-play-after-release.log`:** the
  two after-release hooks.
- **`/var/log/release-comms.log`** and **`/var/lib/release-comms/salesxray/posts/*/post.json`:**
  the release card. Its `sent` field reads `fallback`, the owner's ops chat.
- **systemd journals:** every other sender (`ac-host-cpu`, `ac-status`, `ac-flow-scoreboard`, the
  cost-cap alerts, the disk and backup checks, `ac-strike-cpu-guard`, the watchdog and flow guard).

`/etc/ac-notify/routes.json` is empty, so every `purpose` (`alerts`, `dev`, `decisions`, `status`)
also landed in the owner's private chat.

Releases in the window: v1.54 to v1.59 went live; v1.60 was merged and building.

## Before and after, by message type

| # | Message (sender) | Sent in 48 h | Verdict | After this change |
|---|---|---|---|---|
| 1 | "Shipping vX from the workbench at `<sha>` … Opening the release PR; CI takes about 20 minutes" (ac-ship) | 10 (v1.56, v1.59 twice; v1.60 three times) | Reroute | Log + dev route |
| 2 | "vX merged to main as `<sha>`. Building images (about 20 minutes), then staging" (ac-ship) | 6 | Reroute | Log + dev route |
| 3 | "vX is live on staging and its canary passed: `<staging link>`" (ac-ship) | 4 | Reroute | Log + dev route |
| 4 | "Promoting vX (`<sha>`) from staging to production" (ac-ship) | 6 | Reroute | Log + dev route |
| 5 | "Ship vX stopped: …" (ac-ship `fail`) | 8: v1.54 promotion failed, v1.56 merge, staging canary and production canary failed, v1.59 merge and main build failed, v1.60 `validate-python-gates` twice. Every one of these releases shipped later. | Reroute | Log + dev route. A notice that a release can't ship (`blocked`) goes out only when the orchestrator sends it in plain words. |
| 6 | "Cut vX stopped: the hold recipe failed" (cutlist.sh) | 6 (v1.58 twice, v1.60 four times) | Reroute | Log only since 14 Nov 21:05Z (orchestrator); `cutpatch.sh` now matches |
| 7 | "vX is live on production and its canary passed: `<link>`" (ac-ship) | 4 sent by ac-ship (v1.55, v1.57, v1.58, v1.59). The orchestrator wrote the same line by hand for v1.54 and v1.56; whether it also messaged the owner is unknown. | **Keep, rewritten** | "✅ Sales X-Ray vX is live", 3-5 plain bullets from the title, and the link. No "canary". Once per version. |
| 8 | Release card (release-comms): photo with caption and WhatsApp button, a second card, and a long note with "Please check" steps, "Known issues", "Still pending" and six WhatsApp buttons | 5 posts (v1.55 to v1.59), about 3 messages each, so about 15 | Drop from the owner's chat | Posts are still written and wait for the product's own bot and channel |
| 9 | "Phones pick up vX's web app by themselves now (live web update, no Play build; bundle `<hash>`)" (web bundle hook) | 6 | Merge | One line edited into #7's message |
| 10 | "The phone app with vX is building for Play closed testing …: `<GitHub run link>`" (Play hook) | 6 | Reroute | Log + dev route |
| 11 | Web bundle "did not build"; Play "waiting for approval" / "Approve it here" | 0 | Reroute | Log + dev route |
| 12 | Daily status digest (ac-status, `purpose=status`) and daily scoreboard (ac-flow-scoreboard) | at least 2, plus 1 or 2 | Keep (twice-daily summary) | Unchanged |
| 13 | Host CPU, cost-cap, budget, disk and backup alerts; watchdog and flow guard | 0 (host CPU muted since 7 Nov; watchdog and flow guard timers idle) | Keep as incidents | Unchanged |

**Before:** about 71 release messages in 48 hours (rows 1-10), of which 4 were the live notes he
asked for, and those 4 said "canary".

**After:** one message per release that reaches production, edited once to add the phones line.
Over these 48 hours that is about 6 messages. The twice-daily summary is unchanged. A "didn't ship"
or incident notice goes out only when sent on purpose, in plain words.

## Misleading cases found

- **v1.56:** the owner got "production canary failed after v1.56.0; check now (rollback: …)" at
  13:58Z. Production was fine: the check had failed only on a provider error. The scripts sent
  nothing after that; the next line in the log is the orchestrator's hand-written "is live" at
  14:27Z.
- **v1.60:** he got four "the hold recipe failed" messages in two minutes while the orchestrator
  fixed and re-cut. Then two "failed checks: validate-python-gates" messages while flaky tests
  were being re-run.
- **v1.54:** he got "production promotion of v1.54.0 failed" four minutes before it went live.
