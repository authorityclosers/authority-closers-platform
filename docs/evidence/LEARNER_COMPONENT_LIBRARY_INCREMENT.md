# Learner component-library increment

Status: implemented on `codex/learner-component-library`, based on
`179c0db41997e6fbecb0eaaa7025f879d7b42924`.

## Scope

The Direction A learner shell already used a progress meter locally. This
increment promotes that exact presentation primitive into `@ac/ui` and keeps
the learner app as its compatibility export. The component receives the
caller-provided value and detail; it does not read, derive, or persist learner
state.

## Implementation evidence

- `packages/typescript/ui/src/progress-meter.tsx` — reusable, accessible
  progress-meter primitive with a bounded visual range.
- `packages/typescript/ui/src/index.ts` — public package export.
- `apps/learner-web/app/components/shared-ui.tsx` — app compatibility export
  now backed by `@ac/ui`.
- `apps/learner-web/app/lib/learner-ui.test.ts` — preserves the existing
  Direction A markup contract and verifies values above 100 are clamped.

## Verification

- `pnpm --filter @ac/learner-web typecheck`
- `pnpm --filter @ac/learner-web lint`
- `pnpm --filter @ac/learner-web test`

No backend contract, learner record, progress authority, payment, scoring,
provider, or deployment behavior is changed.
