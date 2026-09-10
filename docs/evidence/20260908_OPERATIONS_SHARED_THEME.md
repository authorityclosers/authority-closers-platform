# Admin and Coach shared theme correction

Scope: shared `packages/typescript/operations-web/src/styles.css`, its focused
theme tests, and the existing Admin quiet-text contrast regression. No auth,
permissions, API, Platform Console, player, learner appearance or provider code
changed in this slice.

The shared root now supplies Clarity/cobalt light and neutral-blue dark semantic
colors to both apps, including their standalone sign-in pages. Admin's scoped
shell no longer resets the palette. Studio cards, controls, fields and secondary
actions use semantic surfaces instead of the former dark-green/lime or fixed
light-only colors. Warning, danger and success retain distinct meanings.

The palette mirrors the learner's current canonical pairs. Small secondary text
uses its stronger neutral `#626c80`, because the original subtle neutral against
the tinted card measured only 4.477:1. The chosen pair measures 4.753:1. Explicit
light/dark selectors are supported without changing stored preferences. First
paint defaults to learner-matching light, even with a dark OS preference; only
`html[data-theme="system"]` follows the OS. Existing reduced-motion rules remain
effective. This does not introduce an appearance preference editor.

## Verification

- 25 focused theme/Admin UI tests passed. They compare actual learner token
  pairs, calculate text/control/status contrast, preserve state distinctions,
  verify inherited palette ownership, reduced-motion rules and 44px controls.
- Full Admin TypeScript, scoped ESLint, Prettier and diff checks passed.
- Independent source review: no Critical or Important findings; no reviewer
  edits, browser interactions or test reruns were claimed.
- Actual local Chrome with already-running development servers: Admin sign-in,
  Coach sign-in, and authenticated synthetic Coach Studio at 1440, 390 and 320px.
  Both light and dark modes were checked after computed styles matched the
  temporary explicit mode, with reduced-motion preference active. Six additional
  checks prove default-light under a dark OS and explicit-system following that
  OS across all three pages. All 18 final captures have no
  document horizontal overflow. Screenshots were visually inspected for layout,
  readable labels, cards and controls.

[Final captures and numeric observations](screenshots/operations-theme-20260908-post-hydration/proof.json)

The earlier `operations-theme-20260908` captures were taken before color-scheme
emulation had settled, so their theme names are unreliable. They are retained
as superseded evidence, not used to claim a pass. The later
`operations-theme-20260908-verified` captures correctly measured OS-following
colors before the requested first-paint correction; they are also superseded by
the final captures above. Final checks wait for the actual expected body color
before capture and restore temporary document attributes and media emulation.
The `operations-theme-20260908-final` pass also exposed one Next development
issue while changing a document appearance attribute before login hydration had
completed. A fresh untouched login had zero issues. The accepted
`operations-theme-20260908-post-hydration` pass waits for the existing hydration
guard to enable the form before temporary attributes change; all 18 captures
then verified zero development issues. No product guard was bypassed or hidden.

Browser work used new local tabs and read-only requests. Existing cookies were
not read or replaced; no login, profile, workspace, content or preference was
submitted. Temporary device/media emulation was cleared. No runtime restart,
deployment, production/staging mutation or remote request was performed by this
slice. This is local desktop-Chrome evidence, not Safari/native-device, full
accessibility, keyboard journey or production verification.
