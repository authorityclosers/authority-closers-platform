# AUT-398: single-account production verification

Implementation: AUT-1077. Execution: Root on AUT-398, after CTO review and CEO
approval of the exact merged revision. This document grants no additional
authority. The recorded owner approval is interaction
`a64d5f9b-5c52-40d3-bee9-56e4e82527ff`, answered 4 October 2026 at 00:25:41 UTC
by owner `ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0`.

Root must confirm that no release is running, name the operator, take and verify
a production snapshot, and post the dry-run result on AUT-398 before applying.
Use only the reviewed script and injected production application settings in
the existing runtime. `require_baked_release_id` binds those settings to that
runtime's baked release. Do not inject a production URL into the dev checkout.

The confidential input is **only** `AC_SMOKE_EMAIL` from
`/home/acdev/.config/ac-qa/production-account.env` (0600; directory 0700), piped
to stdin. Extract only that field through the existing confidential execution
path, without sourcing the file, shell tracing, terminal output, password
parsing or copying credentials. Single or double quotes around the field value
are supported. Do not put the address on argv or in task text. The script never
opens that file or reads its password.

Pin `--person-id` from Root's read-only application-model lookup of that exact
field before preview. Do not guess an ID or change fixture fields to pass the
checks. The target must be active, have both names `Rowan Fixture`, use the
recorded production QA alias pattern on the company domain, retain registration
consent and an existing password credential. Memberships may be absent or
active public-learner memberships only. Any other state is refused.

With the confidential email stream connected to stdin, run:

```sh
python scripts/data-changes/production-smoke-email-verification.py \
  --environment production \
  --person-id <pinned-person-uuid> \
  --approver ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0 \
  --approval-reference a64d5f9b-5c52-40d3-bee9-56e4e82527ff \
  --issue-reference AUT-398 \
  --operator-reference <root-agent-uuid> \
  --run-reference <execution-run-uuid> \
  --command-id <stable-command-uuid>
```

Preview is PostgreSQL-enforced read-only. Its `after` reports planned verification
and revision; it makes no timestamp or audit write. Identity operator audits use
the configured operations tenant, following `identity/email_login.py`; both that
tenant and the configured public learner tenant must exist and be active. No
membership is created to satisfy audit tenancy.

Add `--apply` only after the recorded production snapshot and preview steps.
Keep the same target, command and attribution. One transaction changes the
verification timestamp, increments the person's revision (with the model's
automatic update time), and appends the hash-chained audit including actual
before/after timestamps and owner, approval, issue, operator and run references.
It does not consume challenges or alter credentials, sessions, memberships,
access, billing or credits. Success is printed only after commit. Expected
failures return exit 2 with a fixed message and no confidential input.

The same command returns `replayed` without writes; a new command for an already
verified fixture returns `already_verified` without writes. Existing timestamps
are preserved. Reusing a command with different attribution or target is refused.
Do not change attribution on an existing command to accommodate a later run.

Root then verifies through the app/API and completes AUT-398's three smoke
checks: acquisition HTTP 200 with `state: account` and at least 195 seconds,
profile write-eligibility HTTP 204, and authenticated dashboard HTTP 200. Report
only statuses, state, seconds and session file path/mode. Keep the session at
0600 and its directory at 0700. Within two working days, Root and Chief of Staff
must arrange an approved seed or Admin feature covering this state. This remains
a follow-up on this card until capacity permits; it is outside this script.

## Fictional dev verification

```sh
uv run pytest -q tests/unit/identity/test_smoke_verification_data_change.py \
  tests/integration/test_smoke_verification_data_change_postgresql.py
```

The injected local `AC_TEST_DATABASE_URL` is restricted to localhost. The tests
migrate and remove an isolated schema, insert fictional fixtures, and substitute
test settings without reading production configuration. They prove a read-only
preview, exact target checks, atomic rollback after audit append, first apply,
repeat preservation, command conflict refusal, output containment and concurrent
apply serialization. No public endpoint or screen changes; the existing dev site
is https://salesxray-dev.authorityclosers.com.
