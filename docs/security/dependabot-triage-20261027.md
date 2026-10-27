# Dependabot triage, 27 Oct 2026

GitHub listed 72 open Dependabot alerts on `main` (seen in the v0.98 release push): 11 critical, 28 high, 26 moderate,
7 low. This note covers every critical and high alert: what it is, whether we can reach it, and what we did.
Source: `gh api repos/authorityclosers/authority-closers-platform/dependabot/alerts --paginate`, state open,
27 Oct 2026 ~03:00 IST.

## Result

| | critical | high | moderate | low | total |
|---|---|---|---|---|---|
| Before | 11 | 28 | 26 | 7 | 72 |
| After these bumps reach `main` | 1 | 6 | 19 | 6 | 32 |

Dependabot scans `main`, so the counts drop when the release carrying these commits merges, not when the workbench
commits land.

What is left after the bumps:
- 27 alerts on `torch` and `transformers` in the research bench (1 critical, 6 high, 20 moderate/low). They were
  not bumped; see "Not bumped".
- 5 moderate alerts outside this task's scope; see "Follow-ups".

## Critical and high alerts

"Runtime" means the code ships in a production image. "Dev" means tests, lint or build tooling only.

| Package | Ecosystem | Manifest | Alerts | Advisory | Runtime or dev | Do we reach it? | Action |
|---|---|---|---|---|---|---|---|
| next | npm | apps/{admin,coach,learner,sales-xray}-web/package.json, pnpm-lock.yaml | 5 critical | GHSA-673q-mjm6-r5xr: RCE in `use cache` functions returning typed arrays | Runtime | No. Nothing uses `use cache`, `cacheComponents` or `dynamicIO`. | 16.3.8 → 16.4.1 |
| next | npm | same 5 | 5 critical | GHSA-2464-fhr4-w9xw: RCE in the Image Optimization API (sharp/libvips, glibc) | Runtime | Already mitigated. Every app serves `/_next/image` and learner-web uses `next/image`, but the advisory's workaround (sharp ≥ 0.35.5) has been in the `pnpm-workspace.yaml` overrides since v0.73. | 16.3.8 → 16.4.1 |
| next | npm | same 5 | 5 high | GHSA-p3m5-59mp-jv5r: DoS through Server Actions | Runtime | No. There are no Server Actions (`"use server"` appears nowhere). | 16.3.8 → 16.4.1 |
| zod | npm | apps/{admin,coach,learner}-web, packages/typescript/operations-web, pnpm-lock.yaml | 5 high | GHSA-mrhx-c7xc-m3w5: memory exhaustion on large arrays | Runtime | No. Zod parses only our own API's responses, which are byte-capped (`readPlatformJson`), plus one tenant UUID. No route handler parses request bodies with zod. | 4.5.4 → 4.6.6 |
| happy-dom | npm | apps/learner-web, apps/sales-xray-web, packages/typescript/sales-xray-review-ui, pnpm-lock.yaml | 4 high | GHSA-834v-8h66-3h79: code injection in the ESM compiler | Dev (vitest environment) | No. It only runs our own test code. | 20.14.0 → 21.0.4 (major; see below) |
| brace-expansion | npm | pnpm-lock.yaml | 4 high | GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p: stack-exhaustion DoS | Dev (eslint, eslint plugins and @typescript-eslint through minimatch) | No. It only expands glob patterns from our lint configuration. | lockfile only: 1.1.18 → 1.1.21, 5.0.9 → 5.0.12 (also closes moderate GHSA-q2hr-2g5m-vwhr) |
| source-map-js | npm | pnpm-lock.yaml | 1 high | GHSA-68fv-2mgg-jv7q: event-loop DoS from indexed source maps | Build (postcss, used by the Next build) | No. It only reads our own source maps at build time. | lockfile only: 1.2.1 → 1.2.2 |
| vite | npm | pnpm-lock.yaml | 1 high | GHSA-587h-7wmj-h5pm: launch-editor path check bypass, Windows only | Dev (vitest) | No. We never run a vite dev server, and CI and ac run Linux. | lockfile only: 8.2.2 → 8.2.4 (also closes 4 moderate alerts and 1 low) |
| urllib3 | pip | uv.lock | 2 high | GHSA-vxq7-64xx-v4gw: unbounded chunk-size line; GHSA-8988-9cw3-xx77: HTTPS proxy TLS settings | Runtime (google-auth → requests → urllib3) | Practically no. Our code never imports `requests` or `urllib3`. google-auth uses it only for Google token endpoints over TLS, without a proxy. | lockfile only: 2.7.0 → 2.8.0 (also closes moderate GHSA-gh4c-6fx4-qh6g) |
| torch | pip | docs/research/2026-10-20-analysis-cost/bench/requirements.txt | 1 critical | GHSA-53q9-r3pm-6pq6: `torch.load(weights_only=True)` RCE | Neither: a research bench, never installed by an image, CI job or server | No (see below) | Not bumped |
| transformers | pip | same file | 6 high | GHSA-xrqw-3rrv-vx5w, GHSA-fgcw-684q-jj6r, GHSA-29pf-2h5f-8g72, GHSA-wrfc-pvp9-mr9g, GHSA-hxxf-235m-72v3, GHSA-qxrp-vhvm-j765: malicious model or tokenizer repositories | Neither (research bench) | No (see below) | Not bumped |

### How we chose the versions

Each version is the smallest one that fixes every critical and high alert on that package:
- next 16.4.1: the advisories name no 16.3.x backport.
- zod 4.6.6.
- happy-dom 21.0.4: there is no 20.x fix.
- vite 8.2.4: a patch on the 8.2 line, rather than moving to 8.3.

For brace-expansion, the newest patch on each line (1.1.21, 5.0.12) also closes a moderate alert, so we took it.

pnpm would not move `brace-expansion@5` or `vite` on its own: `pnpm update --depth Infinity` left them where they were.
So the commit pins them as follows:
1. Add temporary overrides (`brace-expansion@5: 5.0.12`, `vite@8: 8.2.4`) and run `pnpm install --lockfile-only`.
2. Remove the overrides and run `pnpm install --lockfile-only` again.

The lock keeps the new versions, `pnpm-workspace.yaml` is unchanged, and no override was added.

The npm lock diff touches only next (with its `@next/env` and `@next/swc-*` packages), zod, happy-dom, vite,
brace-expansion and source-map-js. The vitest and zod-validation-error lines change only their peer-version suffixes.

### What else had to change

Three learner-web files pinned Next 16.3.8, and the npm commit moves each of them to 16.4.1:
- `app/lib/dependency-security-pins.test.ts`: the manifest and lock pins. 16.3.8 joins the versions that must stay
  out of the lock.
- `next.config.ts`: the development trace-privacy guard. It refuses any unreviewed Next version when the local
  staging media bridge is on.
- `app/lib/dev-media-trace-privacy.test.ts`: its runtime pin. The same file runs probes against the installed Next
  trace module: a negative control that records a synthetic URL, and the `NEXT_TRACE_SPAN_THRESHOLD_MS`
  suppression. A green run on 16.4.1 is the renewed privacy evidence that the guard asks for.

One sales-xray-web test changed for happy-dom 21:
- `app/bug-report/bug-report-entry.test.tsx`: happy-dom 21 gives an iframe without `src` no document unless
  `enableIframePageLoading` is on. In real browsers an about:blank iframe always has one.
- `copyScreen()` draws in such an iframe, so the test turns the setting on around that one call and back off after.
  It uses the same `window.happyDOM.settings` route as `app/upload-check.test.tsx`.
- Every other test keeps the new, safer default, and production code is unchanged.

### Next 16.3.8 → 16.4.1: release notes against our setup

We checked the notes for proxy/middleware, caching and static-export changes:
- **Proxy (middleware):** only admin-web and coach-web have `proxy.ts`. 16.4 fixes proxy detection with compound
  `pageExtensions` (#93246), but only sales-xray-web uses compound extensions, and it has no proxy. There are no
  changes to proxy matching.
- **Caching:** the cache changes are about Cache Components and `use cache`, which we don't use. Client router cache
  fixes ("stale data after navigation despite revalidation", #95439) apply under sales-xray-web's
  `staleTimes: { dynamic: 30 }`; the e2e journeys cover navigation.
- **Static export:** the sales-xray-web static preview (`AC_SALES_XRAY_STATIC_PREVIEW=1`, `output: "export"`,
  `trailingSlash: true`) gets three fixes:
  - the trailing slash is kept on the MPA fallback (#97613);
  - configured output directories are preserved (#99507);
  - immutable static assets are supported (#97711).

  wb-ci builds the static preview and runs its browser journeys.
- **Routing:** strict route matching is now on by default (#97397). It only rejects parallel-route (`@slot`) trees
  that can't be completed, and we have no parallel or intercepting routes.
- **Build:** Turbopack now enables the shared runtime and export-name mangling in production builds by default
  (#99504, #99362). CJS tree shaking was enabled and then reverted. `experimental.appNewScrollHandler` was removed;
  we don't set it. The wb-ci `--full` (builds, vitest, visual) and `--e2e` runs cover this.
- **happy-dom 21** is a major release, used in tests only. It stops loading CSS files and iframes by default
  (an SSRF fix). Vitest runs show whether any test relied on that. Nothing in production changes.
- **zod 4.6 and urllib3 2.8** are minor releases with no API removals that affect how we use them.

None of these needs the owner: no production behaviour or setting changes, and there are no billing, data or secret
changes.

## Not bumped: the research bench (torch, transformers)

`docs/research/2026-10-20-analysis-cost/bench/requirements.txt` pins `torch==2.5.1` and `transformers==4.46.3`.

**Why not bumped:**
- It belongs to the 20 Oct analysis-cost research. It renders fictional sales calls with Kokoro and MMS TTS, and
  transcribes them with faster-whisper.
- It is installed only on a throwaway GitHub runner, in a `bench/*` branch pushed by `bench-push.sh`. Its workflows
  are kept here as `.yml.txt` files, so they never run from this repo.
- No image, CI job or server installs it.
- Fixing all its high alerts needs `transformers` 5.10, a major version. Kokoro 0.9.4 and the bench's `VitsModel`
  path have not been tested on 5.x.
- The pins also record how the 20 Oct numbers were produced. Changing them without re-running the bench would make
  that record wrong.

**Mitigation:**
- These packages are never on a production or dev path.
- The bench loads only model repositories named in its code: hexgrad/Kokoro-82M, facebook/mms-tts-{hin,mar,guj},
  ai4bharat/indic-parler-tts, and faster-whisper models by name. It never loads user-supplied models or files.
- Its jobs have `contents: read` permissions and see only the job token. The TTS job can also see an optional
  `HF_TOKEN` (a Hugging Face read token for Indic Parler-TTS).

**Decision needed (owner or orchestrator), one of:**
1. Dismiss these 27 alerts in GitHub as "vulnerable code is not actually used", with a link to this note.
2. Bump to `torch==2.6.0` and `transformers==5.10.0` the next time someone re-runs the bench, using the bench run
   itself as the test.
3. Delete the bench's `requirements.txt` if the research is closed. The results and notes stay.

## Follow-ups (moderate, out of scope here)

| Package | Manifest | Alerts | Fix |
|---|---|---|---|
| @vitest/mocker (through vitest) | pnpm-lock.yaml | 2 moderate | vitest 4.1.11 → 4.1.12 in 6 package.json files (dev only) |
| Mako | uv.lock | 1 moderate | 1.4.1 → 1.4.2 (Alembic templates, dev/migrations) |
| opentelemetry-api | pyproject.toml, uv.lock | 2 moderate | 1.45.0 → 1.45.1 |

Not a Dependabot alert, but found while landing: four loopback-only Sales X-Ray previews run on ac from their own
lane checkouts (`acdev-xray-sx-{shell,org,prospects,report}`, under `~/src/lanes/`). Those checkouts are two weeks
old, run Next 16.3.6 or 16.3.8, and the workbench does not update them, so restarting them changes nothing. They
listen only on 127.0.0.1. Retire them later (orchestrator, 27 Oct).

## Evidence

- Alert export: 72 open alerts, grouped by package (in this session's scratch directory, not committed).
- Lock resolution was done in manifest-only copies of the workbench on ac, under `nice`/`ionice`, without installing
  anything.
  - npm: `pnpm install --lockfile-only`, pnpm 11.19.0, node 24.19.0.
  - pip: `uv lock --upgrade-package urllib3==2.8.0`, uv 0.12.19. The diff is 3 lines.
- wb-ci on the npm commit alone:
  - `--e2e` green on Next 16.4.1: run 40417164548 (static export and acquisition journeys).
  - `--full --web` (lint, tsc, vitest): see the pin commit's message.
- Each lockfile change is a new CI-prerequisite identity, and each identity needs its own bundle of about 431 MB.
  The bundle budget (1 GiB, with a 512 MiB reserve) holds the current workbench identity plus one more. So the
  Python, visual and e2e jobs ran on the stacked npm + pip tree with a single bundle, not on each commit (agreed with
  the orchestrator, 27 Oct).
- The pin commit (`scripts/ci/ci-prerequisite-bootstrap.json`) names the producer run and the verification runs.
