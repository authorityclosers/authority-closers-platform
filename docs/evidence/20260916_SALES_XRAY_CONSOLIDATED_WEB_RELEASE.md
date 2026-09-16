# Sales Xray approved report UI consolidation

2026-09-16. Web-only candidate; production verification is recorded separately
in the release ledger after promotion.

## Source and scope

- `b06c87ab3d506149281171b774ba44ef1b792a74`: compact Overview, Moments,
  focused review and responsive report presentation.
- `e08bc561f6003690fc9ede26c777e84a62bd11a8`: quote recovery and strict optional
  recovery metadata in the report envelope. Unknown or privileged recovery
  fields remain rejected; recovered reports remain unapproved drafts.
- The user's explicit approval is for the current local report at
  `salesxray.localhost:3016`. Its native top-layer dialog correction is included
  before release to address the observed normal-motion/scrolled-shell defect.

The report and acquisition changes merged without conflicts. The coordinator
reviewed quote retry guards, explicit restored-plan acceptance, source bindings,
and recovery metadata validation. Existing processing authority and provider
routes remain server-controlled. There are no API, database or provider changes
in this web release.

## Integrated verification

On Node 24.19.0, pnpm 11.19.0, Windows:

- 242 tests across 27 frontend files passed after combining report UI and
  acquisition/report-contract fixes.
- Zero-warning ESLint passed.
- Next production build, including TypeScript, passed.

The top-layer correction has its own normal-motion and scrolled-shell browser
evidence. Production private-call interaction and fresh guest processing remain
explicit post-promotion gates; local fixture results do not establish them.

Rollback is the previously verified web artifact
`e0879a2d8b310656e8dba7348dd330d831e80ff8`. Core remains independently deployed.
