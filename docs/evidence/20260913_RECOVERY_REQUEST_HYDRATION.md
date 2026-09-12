# Hydrate recovery safely before accepting input

Date: 2026-09-13 (Asia/Kolkata). Source parent: `b4b1a52`.

The real local reset journey exposed a second pre-existing problem before it
could reach the corrected reset-token form. RecoveryRequestForm rendered active
server controls with an implicit GET method. An early submit navigated back to
the same page with an email query parameter; no recovery API call occurred.

The retained receipts `canonical-password-reset-20260912T215227Z`,
`canonical-password-reset-20260912T215348Z` and
`canonical-password-reset-20260912T215510Z` failed at request-reset on exact
checkout/API `b4b1a527a5d4910361be7660f5fa29db4e6dd1ca`. The final diagnostic
records only the query key `email`, the empty reloaded input and masked imagery;
it does not record the synthetic account address in that diagnostic. No external
email/provider was contacted.

The recovery request now uses the same hydration gate as registration. Its input
and submit button remain disabled before hydration, the form explicitly uses
POST, and the handler refuses pre-hydration or already-pending submissions.
Generic account-discovery responses and canonical challenge issuance are unchanged.

Receipts under
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`:

- `recovery-request-hydration-red`: two failures reproduced the implicit GET and
  duplicate pending API dispatch before implementation.
- `recovery-request-hydration-green`: all 55 tests across five recovery, reset,
  registration, Google-continuation and API-client files passed. Formatting and
  scoped zero-warning ESLint passed.
- `recovery-request-final-static`: final learner TypeScript results and the
  source/both recovery regression SHA-256 bindings are recorded in `result.json`.

Independent Luna xhigh review found no actionable P0-P3 defect in the two-file
change. The final exact-checkpoint browser journey remains the acceptance gate;
the earlier failed receipts are retained and are not a successful reset claim.

Final static result: learner TypeScript passed at 2026-09-12T22:00:18Z.
