# Alpha appearance runtime extraction — 2026-09-07

Status: implemented in the consolidation worktree; focused verification passed.
Base commit: `4aee7dd238136839236ed8dac81906467f65862b`.
This record describes an uncommitted local candidate, not a staged or deployed release.

## Change and boundary

The learner root previously imported `ThemeRuntime` from the settings control
module, which also imports settings CSS and Lucide presentation icons. The root
now imports `components/theme-runtime.tsx`, whose only dependencies are React and
`lib/appearance-preferences.ts`. Named presets, settings controls and settings CSS
remain in `components/theme-control.tsx`.

Preference helpers and the runtime lifecycle were extracted without changing
their decisions. Existing control-module exports remain compatible and reference
the same helper module, including its session-only storage-failure overrides.
Storage keys, light/dark/system choice, accents, density, explicit/full/system
motion behavior, bootstrap fallback, local events and cross-tab storage events
are preserved. `public/theme-init.js`, theme CSS, APIs, telemetry and business
semantics were not changed by this slice.

## Verification

Environment: Windows, bundled Node.js `v24.19.0`, bundled pnpm command shim,
Vitest `4.1.11`, local source. No full application build or browser/server restart
was run for this assignment.

- Baseline: three existing theme/PWA test files, 27 tests passed.
- Candidate: five focused files, 44 tests passed:
  `app/lib/theme-control.test.ts`, `app/components/theme-control.test.tsx`,
  `app/components/theme-runtime.test.tsx`, `app/lib/pwa-assets.test.ts`,
  `app/components/settings-runtime.test.tsx`.
- New mounted-runtime tests verify persisted/system appearance changes,
  same-tab saves, cross-tab updates, explicit motion behavior, bootstrap and
  session-only choices under blocked storage, and listener cleanup through
  Strict Mode and unmount. Dependency mocks reject runtime evaluation of settings
  CSS or icons; the layout import contract is also asserted.
- Targeted ESLint passed with zero warnings. Targeted Prettier check passed.
- `tsc --noEmit --incremental false` reported no theme errors but could not pass
  because a concurrent sidebar edit placed `onNavigate` on a native anchor
  (`components/learner-sidebar/sidebar-nav-item.tsx:127`). This was reported to
  the consolidation owner; the sidebar file was not changed by this slice.
- Follow-up verification after the sidebar owner corrected that concurrent edit:
  learner `tsc --noEmit --incremental false` passed. The original failed check
  above is retained as an observation of the earlier worktree state.

Focused test command, with the bundled Node directory first on the process PATH:

```text
pnpm --filter @ac/learner-web exec vitest run app/lib/theme-control.test.ts app/components/theme-control.test.tsx app/components/theme-runtime.test.tsx app/lib/pwa-assets.test.ts app/components/settings-runtime.test.tsx
```

## Remaining release evidence

This establishes the source dependency boundary and behavior, not measured
transfer-byte savings. The consolidation owner must build the final candidate,
inspect emitted root chunks, compare actual transferred CSS/JS, and verify
first paint and settings interactions in the browser before claiming a measured
performance improvement or release acceptance.

The root-layout import edit is complete and layout ownership has been returned
to the consolidation owner for the separate metadata update. No existing dirty
course/sidebar/style files, commits, deployment state or external records were
changed by this slice.
