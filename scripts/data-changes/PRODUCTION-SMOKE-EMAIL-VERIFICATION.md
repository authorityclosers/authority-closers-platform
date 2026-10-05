# AUT-398: single-account production verification

Implementation: AUT-1077; named prior consent amendment: AUT-1237. Execution:
Root on AUT-398, after CTO review and CEO
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
consent and an existing password credential. By default that consent must match
the configured, nonblank `learner_consent_version`. The CEO's 5 October decision
permits only the recorded prior version `ac-learner-terms-privacy-2026-09-13-v1`
when explicitly named with `--recorded-consent-version` and exactly equal to the
person's recorded version. Wrong, unnamed or other prior versions are refused in
preview and apply. Naming the prior version when the person has a different
version is also refused, even if that person has current consent. Memberships may
be absent or active public-learner memberships only. The script never records or
replaces consent; the approval still covers the same fixture and verification.

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
  --command-id <stable-command-uuid> \
  --recorded-consent-version ac-learner-terms-privacy-2026-09-13-v1
```

Omit `--recorded-consent-version` for a fixture whose recorded consent matches
the current configuration. Use the same named version for preview and apply.

Preview is PostgreSQL-enforced read-only. Its `before.learner_membership` reports
`present` or `absent`; `after.learner_membership` reports `present` or `planned`.
It reports planned verification and revision without timestamp, membership or
audit writes. Identity operator audits use the configured operations tenant,
following `identity/email_login.py`; both that tenant and the configured public
learner tenant must exist and be active.

Preview and audit include `consent.recorded_version`,
`consent.configured_version` and `consent.named_prior_version` (null when omitted).
For the named prior path, the intent binds both the named and configured versions.
The provisioning helper receives only the consent version already recorded and
accepted by these checks; consent version and consent timestamp are never written.

Add `--apply` only after the recorded production snapshot and preview steps.
Keep the same target, command and attribution. One transaction changes the
verification timestamp, increments the person's revision (with the model's
automatic update time), ensures the one active public-learner membership through
the app's `AsyncLearnerProvisioningApplication`, and appends the hash-chained audit
including actual before/after timestamps, membership state and owner, approval,
issue, operator and run references. This is the same learner provisioning used by
the app's email verification route. Only an absent learner membership may be
created; existing roles and memberships are preserved. It does not consume
challenges or alter credentials, sessions, other accounts, billing or credits.
Success is printed only after commit. Provisioning and audit failures roll back
the entire change and return exit 2 with a fixed message and no confidential input.

The same command returns `replayed` without writes; a new command for an already
verified fixture with its learner membership returns `already_verified` without
writes. A verified fixture lacking that membership is eligible for provisioning;
its timestamp and revision remain unchanged. No repeat creates a second membership
or audit. Reusing a command with different attribution, target, configured learner
tenant or consent version is refused. Do not change attribution on an existing
command to accommodate a later run.

For the older consent, Root first signs in and checks GET `/v1/me/consent` reports
`renewal_required`. Renew through POST `/v1/me/consent/renew` with the current
`expected_version` obtained from the app's consent response. Consent renewal is
only through the app, never SQL or this script.

Root then verifies through the app/API and completes AUT-398's three smoke
checks: acquisition HTTP 200 with `state: account` and at least 195 seconds,
profile write-eligibility HTTP 204, and authenticated dashboard HTTP 200. Report
only statuses, state, seconds and session file path/mode. Keep the session at
0600 and its directory at 0700. The 195-second check depends on the account's
personal allowance or tester exemption; this script grants no minutes. If that
check fails, Root raises the minute grant with the CEO on AUT-398. Within two
working days, Root and Chief of Staff
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
repeat timestamp/membership preservation, named-prior acceptance, unchanged
recorded consent, wrong/unnamed/other consent refusal, preview/audit consent
provenance, command conflict refusal, output containment and concurrent apply
serialization. No public
endpoint or screen changes; the existing dev site
is https://salesxray-dev.authorityclosers.com.

AUT-1237 implementation evidence (5 October 2026): the command above passed
all 70 tests against an isolated local PostgreSQL schema, including both named
prior and current consent paths. `uv run ruff format --check packages/python tests
scripts/data-changes/production-smoke-email-verification.py`, `uv run ruff check
packages/python tests scripts/data-changes/production-smoke-email-verification.py`
and `uv run mypy packages/python` passed (419 source files). No production settings
or account were read or changed. Root owns the production snapshot, preview,
apply, consent renewal and authenticated smoke evidence after merge.
