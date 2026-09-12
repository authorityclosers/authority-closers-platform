# Admin command reason entry and pending dispatch

Validated on 2026-09-12 UTC (2026-09-13 in Asia/Calcutta), following local
checkpoint `257072eeab5b23d99f2c59b9c57ba9b56c5263e3`.

The shared Admin command form disabled every field until an execution handler
existed. Correction, enrollment grant, job retry, publication and recovery
reconciliation create that handler only after a nonblank reason is entered.
An authorized operator with a resolved target therefore could not enter the
reason needed to prepare the command. Two submit events before React updated
the pending state could also dispatch the command twice.

The form now permits editing when the existing permission check succeeds and
the target is resolved. Its submit button and handler still require valid
command fields. Multiline reason entry works before submission is ready. A
synchronous in-flight guard refuses repeated dispatch until the request settles;
the pending state disables fields, and rejection preserves the reason for
recovery. The API remains authoritative for actor, tenant, resource ownership,
revision, idempotency and command validity.

## Scope and controlled basis

This is a latent component defect: current People correction/grant and Learning
Operations pages do not yet supply resolved targets, and no production caller
of `PublishVersionForm` was found. They remain unavailable. No target lookup,
diagnosis route, permission, reviewer assignment, server command, business policy
or provider was activated or changed.

AC-IMP-04 section 12 requires safe learner diagnosis and explicitly authorized
corrections. The controlled Admin specification requires target context, reason
and append-only audit. AC-UXA-01 requires understandable operator preparation and
recovery. Exact source IDs and the broader remaining capability map are recorded
in recovery `ui-remaining-acceptance-matrix-20260912.md`; required initial source
reads are in `ui-controlled-source-register-20260911.json`.

## Verification

The mounted regression uses the actual `AdminSessionProvider`, controlled
session-loading I/O and mocked command functions. It covers all five callers:
reason entry, whitespace refusal, exact trimmed arguments, unresolved target,
missing command permission, missing Admin surface permission and loading session.
It separately covers duplicate dispatch before React flush, pending controls,
rejection feedback, retained reason and retry. Synthetic identifiers, ETags and
mock responses are component fixtures, not backend acceptance evidence.

- Unchanged runtime: **6 failed, 20 passed**. Five failures reproduce the input
  lock; one observes two dispatches instead of one.
- Fixed runtime: **26 passed**.
- Full Admin suite under supported **Node 24.19.0: 662 passed in 29 files**.
- Admin TypeScript, full lint, scoped Prettier and diff checks passed.
- Independent final source/test review found no P0/P1/P2 defect in this diff.

Recovery packet: `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.
The original regression and final passing run are retained in
`admin-command-forms-before-20260912T183323Z` and
`admin-command-forms-after-20260912T183346Z`. Final supported-runtime suite and
static logs are in `admin-command-node24-validation-20260912T183656Z`; source
hashes bind the runtime and test bytes to that validation.

The earlier full run in `admin-command-validation-20260912T183413Z` used the
shell's Node 22.17.0 and produced 649 passes plus 13 native privacy-probe
failures. An isolated import reproduced `ERR_UNKNOWN_FILE_EXTENSION` for the
shared TypeScript transport under Node 22, while the identical import succeeded
under the launcher's installed Node 24.19.0. The process-local PATH was corrected;
the product and privacy tests were unchanged. That failed run is preserved and
superseded by the complete Node 24 pass.

No backend mutation, browser workflow, support capability activation or deployment
is claimed by this component-only fix. Canonical draft persistence/session
recovery and the missing Admin support read model remain separate acceptance work.
