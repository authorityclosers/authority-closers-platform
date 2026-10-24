# Telemetry improvement loop

Owner, 24 Oct 2026: "where is the telemetry data of each device … I want it to be nicely
visualised and presented and more importantly use in our recursive improvement pipeline each
new update we improve the app using that data".

This page describes how Sales X-Ray's own usage and performance telemetry decides what to build
next, and whether each release made the app better.

## The loop

1. **Collect.** The web app and the Android app record usage and speed, under the analytics
   switch (option B).
2. **See.** Admin → Product telemetry shows four pages:
   - **Overview:** speed, screens, funnels, errors.
   - **Devices:** every phone model and device kind.
   - **Releases:** each release against the one before it.
   - **Fix next:** the ranked list of what to fix.
3. **Rank.** Fix next ranks problems by the people they affect times how bad they are.
4. **Card.** A finding becomes a task card with its evidence, screen and suggested owner.
5. **Fix and ship.** The fix goes out through the normal release train.
6. **Gate.** Before a release is promoted, the gate checks that no key action got slower past
   the limit.
7. **Measure.** The same finding is measured release by release. The next window's Fix next
   lists it under "Improved" (gone, or 20% better), or keeps it ranked if it isn't.

Every finding has a stable key, such as `slow:lead_open:leads` or `exit:crash`. The key travels
on the card, so the result of every fix can be read back from telemetry.

## What is recorded

Option B, decided by the owner on 24 Oct 2026:

- Recording is on in every workspace. Each person can opt out, and an owner or admin can turn it
  off for the whole workspace.
- Sandboxes never record.
- The notice is versioned. The current version is `sx-product-analytics-2026-10-24-v2`.

The data is counts, timings, tiers and codes only:

- No call content, lead names, numbers, email addresses, contacts or locations.
- No person is ever named or listed in Admin.
- Events are kept for 180 days and are never used to score a person or to decide access,
  payments or plans.

**Web** (`telemetry-auto.tsx`) records:

- screens and flows;
- the time from a tap to the screen settling, for key actions;
- Web Vitals and app start;
- script errors, as a fingerprint and never the message;
- slow or failed API calls, with ids removed from the path;
- rage and dead taps;
- named features.

**Android app** (1.0.26 and later, sent by the page through the phone bridge) records:

- launch time;
- frames, with slow and frozen counts;
- why the app last closed (crash, ANR, memory);
- a daily device profile: maker, model, Android and WebView versions, memory and storage tiers;
- battery, standby and network state;
- which of its permissions are granted.

## Devices (`/telemetry/devices`, `GET /v1/admin/telemetry/devices`)

A **device** is one person's phone model, which the Android app reports from 1.0.26. Without
that, a device is the device kind: app, class (phone, tablet or computer) and speed tier. Devices
are grouped by model or kind. For each group, the page shows:

- people, and their app, Android and WebView versions, memory, tiers and networks;
- speed on the four key actions: open a lead, switch tab, call, and open a report. Each shows
  its taps, median, 75th percentile and slow share;
- the group's share of the slowest 10% of all taps on each key action. A device whose taps sit
  over 10% is over-represented among the slow taps;
- script errors, errors shown, failed calls, crashes, Android memory kills, and rage and dead
  taps.

**Speed index.** A device's index is the median, over its key-action taps, of the tap time
divided by that action's slow limit. An index of 1.0 means the typical tap is exactly at
"slow". A device needs at least 3 key taps to be ranked.

**Slowest 10% of devices.** The top tenth of ranked devices by speed index. Each one is shown by
its model, app version, Android version, memory and network only, never by a person.

The slow limits are 1 s for open a lead and call, 500 ms for switch tab, and 1.5 s for open a
report.

## Releases (`/telemetry/releases`, `GET /v1/admin/telemetry/compare`)

The page compares the newest release that has taps against the release before it, or any two
releases you name, over the last 30 days. It covers:

- **Key actions:** the 75th percentile.
- **Problems per 100 sessions:** script errors, errors shown, failed and slow server calls, rage
  and dead taps, and app crashes and freezes.
- **Page speed:** the 75th percentile of Largest Contentful Paint and Interaction to Next Paint.
- **Funnels:** the share reaching the last step, from a report to an outcome and from Leads to
  an outcome.

Each measure is marked better, about the same, worse, or too few to say:

| Measure      | "Worse" when                                                          | Minimum sample              |
| ------------ | --------------------------------------------------------------------- | --------------------------- |
| Key action   | p75 at least 10% and 50 ms slower; a **regression** at 20% and 150 ms | 20 taps in each release     |
| Problem rate | 50% and one event per 100 sessions higher                             | 20 sessions in each release |
| Page speed   | p75 at least 20% and 50 ms slower                                     | 20 samples in each release  |
| Funnel       | last step 10 points lower                                             | 20 people at the first step |

The page shows regressions and other worse measures as amber cards at the top. They are never
red banners.

## The release gate (`GET /v1/admin/telemetry/gate?release=<id>[&baseline=<id>]`)

The gate is an input to Align 3's release train.

```json
{
  "schema": "ac.sales-xray.telemetry-gate/1",
  "environment": "production",
  "release": "<id>",
  "baseline": "<id or null>",
  "verdict": "pass | block | not_enough_data",
  "blocks_promotion": true,
  "reasons": ["Open a lead: 75th percentile 920 ms → 1240 ms (1610 → 702 taps)"],
  "warnings": ["Slow server calls: 8.2 → 13.5"],
  "override": "The owner can override a block; the release train records who and why.",
  "thresholds": {"block": "…", "warn": "…", "gate_ratio": 1.2, "gate_ms": 150, "gate_min_taps": 20},
  "metrics": [ ... ]
}
```

- **block:** at least one key action regressed. That means its p75 is at least 20% and 150 ms
  slower than the baseline, with 20 or more taps in each release. Only key actions block.
  Everything else is a warning.
- **not_enough_data:** the release is unknown, there is nothing to compare it with, or there
  are too few taps. This never blocks.
- **Access:** `release` is required. The endpoint is read on the admin host, either by an AC
  control account in the operations workspace or with a staff key that has `admin:read`.

**Suggested wiring (Align 3 owns the train):**

1. **Before a promotion,** read the staging gate for the candidate. Staging has little real
   traffic, so this mostly returns `not_enough_data` until QA smoke runs tap through the key
   actions.
2. **After a promotion,** read the production gate for the new release once it has traffic,
   for example 24 hours later. A `block` holds the next promotion until a fix ships or the
   owner overrides it.
3. **Recording an override:** the train records the owner's override, with who and why,
   alongside the promotion.

## Fix next (`/telemetry/fix-next`, `GET /v1/admin/telemetry/fix-next?window=`)

| Finding                             | Key                                           | Crosses the line when                    | Severity                               |
| ----------------------------------- | --------------------------------------------- | ---------------------------------------- | -------------------------------------- |
| Slow action on a screen             | `slow:<action>:<screen>`                      | 10 taps or more and at least 20% slow    | 3 for key actions, 2 for others        |
| Script error (ours, not extensions) | `error:<class>:<fingerprint>`                 | any                                      | 3 if from our code, 2 if from a vendor |
| Failing server call                 | `api_failed:<endpoint>`                       | 3 or more 5xx responses                  | 3                                      |
| Slow server call                    | `api_slow:<endpoint>`                         | 5 or more calls with p75 of 3 s or more  | 2                                      |
| Rage taps                           | `tap:rage:<screen>:<target>`                  | 3 or more                                | 2                                      |
| Dead taps                           | `tap:dead:<screen>:<target>`                  | 3 or more                                | 1                                      |
| Android crash or ANR                | `exit:crash`, `exit:crash_native`, `exit:anr` | any                                      | 4                                      |
| Android memory or resource kill     | `exit:low_memory`, `exit:excessive_resource`  | any                                      | 2                                      |
| Slow page (LCP or INP poor)         | `vital:<metric>:<screen>`                     | 10 samples or more and a poor p75        | 2                                      |
| Refused permission                  | `permission:calls`, `permission:rec_files`    | 4 or more asked and at least 25% refused | 2                                      |

- **Score:** people affected × severity. Ties go to the finding with more events.
- **Each finding carries:**
  - its evidence;
  - its screen;
  - a suggested owner session;
  - its measure now and in the window before;
  - its measure for the last 4 releases;
  - "new" if it wasn't a finding in the window before;
  - the task text.
- **Improved:** findings from the window before that are now gone, or at least 20% better.

**Suggested owners by screen.** These are suggestions; Align 3 or the orchestrator assigns the
card.

| Screens                                     | Owner                        |
| ------------------------------------------- | ---------------------------- |
| Leads, a lead, prospects                    | Lead OS                      |
| Report, analysis, calls, new call, coaching | Report (Brain 4.0)           |
| Chats                                       | Chats inbox                  |
| Settings, account, apps, developers         | Settings and Admin (admin-2) |
| Billing, plans                              | Billing                      |
| Organisation pages                          | Organisations                |
| The Android app                             | Android app                  |
| Anything else                               | Sales X-Ray web              |

## Task cards

- **Now (v0.87):** each finding has a **Copy task** button. It copies the title, people, window,
  environment, severity, evidence, screen, suggested owner and finding key, ready to paste into
  the bug board or AC Pulse.
- **Next (v0.88), proposed:** a weekly job, `ac-telemetry-board`, built like `ac-bug-board`.
  - It runs on Monday at 09:00 IST and reads the production Fix next.
  - It opens a card for each new finding scoring 6 or more (for example 2 people on a serious
    problem).
  - It de-duplicates by finding key, using its state file.
  - It comments on the card when the finding shows up under "Improved".
  - The destination is Paperclip, through the `ac-bug-board` route, or AC Pulse through Align 3.
    That choice is the orchestrator's.

## Measuring a fix

A card names its finding key. After the fix ships, there are three checks:

1. On Fix next, the finding's measure for its release shows whether it improved.
2. In the next window, the finding appears under "Improved", or stays ranked.
3. On Releases, the comparison of the fix release against the one before it shows the same
   measure.

## Limits and next steps

- Each Admin read takes at most 200,000 rows from `analytics_events` for its window: 7 days, or
  14 days for Fix next. If volume grows past that, add an index migration on
  `(retention_policy_id, occurred_at)`; Align 3 assigns migration numbers.
- Release order is the order in which releases are first seen in telemetry.
- Crashes come from the app's own exit reasons, not from Crashlytics. Crashlytics stays in the
  Firebase console.
- Report section reads (`sx.section_read`) are waiting for the Report owner's hooks. The
  report funnel's middle step stays thin until then.
