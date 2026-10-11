# Admin console on the console shell — AUT-1798 (Strike G)

Owner order 11 Oct 2026: rebuild the Admin panel on Pulse's shell so that
dipak@, admin@ and assigned coaches can review every call and keep improving it.
Round 1 merged as #441; this note covers round 2 (#445).

## What changed

- **Call review console**: queue filters (organisation, rep, language,
  provider, prompt version, upload dates; folded behind one button on phones);
  one screen per call with player, transcript, report, six pillars, Coaching,
  metrics and runs; failed steps listed per call with the existing admin job
  retry (only for steps that never reached a provider); "Y" copies a link to
  the current moment (`?at=`), which opens paused on that line; compared runs
  mark the words that changed; a click anywhere on a queue row opens the call.
- **Analysis health**: per prompt version and Report model (analyses,
  finished, running, failed and retried steps, typical Report step time,
  estimated cost per minute; operational only, never quality), each version
  linking to its calls.
- **Home** opens on today's calls and analysis health for call reviewers.
- **Usage** names Sales Xray's `telemetry/1` events and shows the rep journey;
  it stays empty, and says why, until product analytics has a consent and
  retention policy.
- **Older screens** on the kit or console tokens: People, Organisations,
  Reviewers, Providers & costs, Minutes, Execution & budget, Analysis
  settings, saved report, synthetic data, safety, product updates, releases,
  and the reviewer workspace for invited reviewers. Failed reads are small
  "unavailable" cards; times are India time on server and browser alike.

Not changed: sign-in (Admin and reviewer), the proxy's admission rules, billing
panels, migrations and dependencies.

## New or extended read APIs (no writes, same admission as call review)

`GET /v1/admin/conversation/calls` (`prompt` filter, `prompts` facet),
`/calls/{id}` (`failed_jobs`), `/health` (`versions`), `/usage`,
`/product-updates`, `/synthetic`, `/synthetic/{call_id}`.

## Verification

- Python unit and route tests for every endpoint above, PostgreSQL cases for
  the call review and health reads (CI); ruff, format and mypy on changed
  modules.
- admin-web: vitest for every changed screen and normaliser, including all
  console pages rendering with every read failing and with empty reads; typecheck
  and ESLint (no warnings) on changed files.
- Browser checks on a production build against a synthetic fixture API
  (fictional data only), 1440 and 390 px, light and dark: a sweep of 24 routes
  renders with no sideways overflow; the reviewer workspace was checked with a
  synthetic reviewer session.
- Accessibility (axe-core 4.13, WCAG 2.1 A/AA) on 14 routes in both themes at
  1440 and 8 routes at 390: clean after fixing badge contrast in light mode and
  an unnamed phone button.
- Layout shift measured on 17 routes at 1440 and 390: largest 0.0022, phones 0.

Screenshots and audit reports are kept privately in the strike folder
(`/home/acdev/strikes/1798/shots/`, `axe-2026-10-11*.json`).

## Known limits

- Re-running a finished call needs its own admin command (a new provider
  charge); the button stays disabled and says so.
- Verdicts, notes, gold labels and training/test marks need the append-only
  label store, which waits for the shared migration slot and the owner's
  approval.
- Deal outcomes wait for the Report strike's outcome store; Usage waits for a
  product-analytics consent and retention policy.
