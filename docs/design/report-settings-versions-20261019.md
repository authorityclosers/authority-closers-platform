# Report settings with versions (owner order, 19 Oct 2026; v0.65)

How the Report, Prospect and Coaching tabs present a call, in numbered versions that Admins choose per organisation.

## What the owner gets (Admin → Sales Xray setup → Report settings)

- **Version 1 is today's Report, Prospect and Coaching, frozen.** It lives in code (`report_settings.VERSION_1`), so nothing can edit it.
- **New version:** start from any version, change what you want, give it a name and, optionally, a target industry. It gets the next number. Versions are never edited; a change is a new version.
- **Choose:** pick a version for an organisation, as an industry's default, or as the general default.
  - **Rolling back** means choosing an earlier version again. The History list has a one-click Roll back on the newest choice of each scope.
  - **Who changed what:** every version and every choice is a new row with the person, time and reason. Each command also leaves an audit event.
- **Which version applies, in order:**
  1. the organisation's own choice;
  2. its industry's default;
  3. the general default;
  4. version 1.

  The industry is the `industry_code` on the organisation profile, which AUT-2115 fills. Until then, industry defaults can be set but nothing matches them.

## The settings (`ac.sales-xray.report-settings/1`)

| Tab | Settings |
|---|---|
| Report | style (guided, compact or scorecard), detail (simple, standard or expert), parts on/off (Overview & Score, Detailed Call Analysis, Final Call Outcome; at least one stays), which of the 27 pointers, the most pointers at once, scores, evidence quotes, how-to-improve tips |
| Prospect | tab on/off, detail, the ten sections of the owner's Prospect design, inferred facts |
| Coaching | tab on/off, detail, moments and how many, across-calls patterns, tone (AI wording, later) |

**In the app now:** Report parts and the Prospect and Coaching tabs (`apps/sales-xray-web/app/report-settings.ts` filters the panels in `report-modes.tsx`). Any read failure, a guest or an older server falls back to version 1.

The rest is saved and validated. Each tab adopts it through `useReportSettings()`, and the Admin form labels each setting "In the app now" or "Saved; each tab adopts it".

## Built for auto-tuning later (AUT-2116, not built)

Every parameter in `report_settings.PARAMETERS` declares:
- its kind and bounds;
- whether it changes display or AI generation;
- whether it is tunable;
- which signals would tune it: product events such as `sx.pillar_read`, `sx.clip_played`, `sx.prospect_edited`, and outcomes such as `gold.agreement`.

A tuner would propose a version with `origin = 'tuner'`, which the table already allows. It never chooses one: an Admin does, and the history shows it.

**Next step for attribution:** tag report-view events with the version number, so that each version's results can be compared.

## Storage

- Migration `20261019_0098` adds two append-only tables:
  - `conversation_report_settings_versions` (number at least 2, settings JSON with a sha256);
  - `conversation_report_settings_events` (`version_created` and `assigned`, scoped to organisation, industry or general).
- Backup parity v65 covers both tables in all three host scripts.
- Downgrade only while both tables are empty.

## Routes

- `GET /v1/admin/conversation/report-settings`: Admin read of parameters, versions with their changes, who uses which version, defaults and history.
- `POST /v1/admin/conversation/report-settings/versions`: create a version (Idempotency-Key required).
- `POST /v1/admin/conversation/report-settings/choices`: choose for an organisation, industry or everyone. It carries the version the Admin saw as current; a stale screen is refused (409).
- `GET /v1/conversation/acquisition/report-settings`: the version for the signed-in workspace.
