# AUT-1156: billing QA credential contract

Source: latest main `e63899342d8d122e83bb01690c280640c9c1bbe3`, claimed with
`ac-gate start devenv 1156-billing-qa-contract`. The deleted AUT-1191 task branch
was finished with the gate's `done` before starting. `ac-gate check` passed.

Both transport tables now match the unchanged AUT-969 fixture's staff email
and password-variable declarations, with Infisical **dev `/application`**.
The root inner reader accepts exactly the four declared secret names; the
customer password, obsolete staff name, unrelated folder values and undeclared
names cannot be emitted. Other identities and Organisations matrices are kept.
Billing staff requires `platform_billing_manage` through the normal access API,
without acquiring Organisations permissions. The browser retains its origin,
receipt, readiness, real login, sentinel, leak, buffer and cleanup boundaries.

Initial implementation validation uses fictional values and simulated infrastructure
only. `uv run pytest tests/infra/test_dev_qa_credential_transport.py -q`:
**108 passed in 33.79 seconds**, no skips. Focused Ruff check passed. Tests bind
the transport to the fixture declarations, exercise pipe-only selection and
refusal for every identity, exclude other secrets, verify buffer zeroing after
success and failure, and require the billing grant from the normal API. The
operator tests also reject wrong source/checksums/owners/DB endpoints/networks,
unsafe inputs and non-root callers; prove input filtering and bounded immutable
container arguments; and compile both released child execution paths. No
Docker, Infisical or database execution is part of these tests. Final
`ac-gate check` and `git diff --check` passed. Markdown was formatted with
Prettier; the changed Python files passed Ruff check and format.

CTO review of `a51f8430ca98b3c2081466b67c6249b14e8186b8` found that a later
`--email=...` or `--expected-email=...` could override the pinned operations
identity. The corrected runner accepts one exact bare identity flag and its
pinned following value; repeated flags, equals forms, extended flag names and
missing values refuse before runtime inspection or secret injection. The
canonical released parsers already disable abbreviated options. Regression
coverage exercises both commands, the reproduced override and valid pinned
arguments. The corrected focused suite: **126 passed in 8.87 seconds**, no
skips. Ruff check and format passed. No live execution was required.

No live credential was read, fixture applied, refund requested or host/service
changed. Root install and non-root dev sentinel proof require reviewed, merged,
released artifacts. Actual sign-in, fixture data/settings and payment readback
remain on AUT-959; Root never performs Browser QA's single fictional refund.

## Operator runbook

Root Operator is the single operator. CTO reviews this PR, CEO approves its
exact head, watchdog merges, then Root installs from its immutable release.
This child authorizes implementation and sentinel validation, not live data,
secret or billing application. Those operations remain on
[AUT-959](/AUT/issues/AUT-959), under its saved human decision
`dc66a6ad-7823-4f4f-8c5e-02e4c63090bd`. Root verifies its accepted human
resolution and exact dev scope before applying anything; reference UUIDs alone
confer no authority.

### Executable and network proof

The native API at `0accda891cb7bdd4f0b677c1cb8588730b745e95` lacks the fixture
module. The narrowly necessary `scripts/dev-billing-qa.py` runner uses the
already released API at **`d5af14fc105a1e3539e3e9ba7fc058fc10eb8c44`**, not that
mutable native source. Root's
[4 Oct readback](/AUT/issues/AUT-959#comment-379747c3-25eb-46c6-bc12-8f5134becf9e)
identified that stored `current-staging` release. Its
[Application validation](https://github.com/authorityclosers/authority-closers-platform/actions/runs/37205047732)
and packaging job `111447810782` succeeded. The source's Dockerfile.python
installs `packages/python` into `/app/.venv`, bakes `/app/.ac-release-id`, and
defines user `ac` (10001). Local ancestry confirms this source contains AUT-969.

The launcher verifies that exact root-owned release directory's
`RELEASE-FILES.sha256`, then selects its immutable `AC_API_IMAGE` from
`release-images.env`. It checks the local image's OCI source label and probes
the baked ID, UID and installed staff/secret declarations. No tag, image pull,
build, native-source edit, service restart or release-control change is used.
Keep preflight JSON as the exact API image/network receipt. This run has no
permission to traverse `/srv/authority-closers`; Root's metadata receipt and
released install remain required. Source/publication evidence alone is not
proof of a running executable. If the stored release/image is unavailable,
stop and reuse the approved release-engine recovery path.

Root's recorded dev DB endpoint is `172.27.0.2:5432/ac_platform`, user
`ac_runtime`, owned by `acdev-postgres`. The runner discovers that container's
sole attached bridge, requires that IP, and proves DNS in the released process
resolves `acdev-postgres` to it. It converts only an injected URL's validated
bridge hostname to `acdev-postgres` in memory. AUT-969's unchanged target guard
runs inside every data command, requiring the exact hostname/driver/port/DB/user.
Query routing, other endpoints, live billing, Razorpay values and ambient `PG*`
inputs refuse. There is no hosts-file edit or target-guard exception.

Each temporary container is non-root, read-only, has no host mounts/ports,
drops all capabilities and new privileges, and is limited to **256 MB, 0.25 CPU
and 64 PIDs**. `--pull=never`, `--rm`, `--log-driver=none` and a 16 MB tmpfs
keep it bounded. Both sequential phases use the name
`ac-dev-billing-qa-<tool>-<launcher-pid>` so an interrupted Docker client leaves
an identifiable container. The root injector receives dev `/application`; only the nine
declared `INPUTS` and fixed dev/hold settings reach the executable. Token,
bootstrap, migrator URL and other folder values stay outside that process.
Values never enter argv or a credential file. The browser broker remains a
separate pipe boundary that emits only the selected staff password to QA.

### Root installation and transport check

`R` is the checked immutable release containing this PR, after its CTO/CEO
approval and merge. It is distinct from the existing API executable pin above.
Back up the two existing QA scripts and sudoers file to a root-only task backup,
preserving bytes, owner and mode. Install the credential scripts using the
development README's existing commands and identical sudoers allowlist. Then:

```sh
install -o root -g root -m 0700 "$R/scripts/dev-billing-qa.py" /usr/local/sbin/ac-dev-billing-qa
python3 /usr/local/sbin/ac-dev-billing-qa preflight
```

Expect `ok=true` naming the exact source, `sha256:` image, verified bridge and
UID 10001. Preflight injects no secrets and opens no database connection. Read
back the installed identity tables: exact AUT-969 staff email, `/application`
and `AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF`. Run as non-root QA:

```sh
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity billing-staff --sentinel-only
```

Require real login refusal, `leaks=[]` and profile cleanup. No real credential
is requested. Do not add QA sudo access to the root-only operator runner.

### Dev injection and the missing fictional person

Use the existing `ac-infisical-run` route, **dev `/application`** only. Required
existing names: `AC_DATABASE_URL`, `AC_SESSION_TOKEN_PEPPER`,
`AC_EMAIL_CHALLENGE_SECRET`, `AC_LEARNER_CONSENT_VERSION`,
`AC_PUBLIC_LEARNER_TENANT_ID`, `AC_OPERATIONS_TENANT_ID`, and
`AC_ENVIRONMENT=development`. The first six must be nonempty. Fixture inputs:
`AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF`,
`AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER`, `AC_BILLING_FAKE_PROVIDER_SIGNING_KEY`.
Root verifies that existing secrets, tenant IDs, consent version and fake key
match the native dev API. A missing name/mismatch is a stop, not a reason to
copy staging/prod values. Missing API EnvironmentFile variables do not prove
Infisical absence. Parent AUT-959 handles its separately authorized API
`AC_BILLING_ENABLED=true` through the existing refresh/cutover path; this runner
neither enables billing nor changes services/provider settings.

```sh
AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- python3 /usr/local/sbin/ac-dev-billing-qa inventory
```

This is an ORM SELECT in a PostgreSQL read-only REPEATABLE READ transaction.
It returns `grant_history_count` (including revoked history), and person IDs
for exactly **`qa-dev-operations-owner-aut959@example.test`**. Before manager
setup, **any capability-grant history stops first-manager**: escalate to CTO
under rule 2 on the parent. Never delete/hide history to open bootstrap.

There is **no reviewed person-creation path inside this card's file scope**.
AUT-828 requires an existing active, verified person with a provider identity.
AUT-514's fixed learners and either AUT-969 identity are ineligible. Smallest
follow-up card: **"API: create the dedicated fictional dev operations person
through a reviewed identity fixture"** (api, non-routine; existing identity
services, exact dev target, idempotent audit and tests). Stop manager/fixture
application until that reviewed output exists. Do not invent an identity,
credential, alias or owner session. This gap does not block the transport PR.

### Owner membership, then first manager

After that output supplies exactly one verified person, keep its read-back UUID
as `DEV_OPS_PERSON_ID`. Use separate stable `DEV_OWNER_COMMAND_ID` and
`DEV_MANAGER_COMMAND_ID` UUIDs, recorded with the operator/run on the parent.
Preview the existing AUT-828 membership command:

```sh
AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- python3 /usr/local/sbin/ac-dev-billing-qa owner \
  --environment development --email qa-dev-operations-owner-aut959@example.test \
  --command-id "$DEV_OWNER_COMMAND_ID" --approver ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0 \
  --issue AUT-959 --reason "AUT-959: fictional dev manager; owner card dc66a6ad-7823-4f4f-8c5e-02e4c63090bd"
```

Require `dry_run=true`, intended owner membership and absent grant history.
After verifying authority, repeat identically with `--apply`. Re-run inventory
immediately before first-manager: require the same sole person UUID and zero
history. The canonical first-manager CLI **commits** and has no preview flag:

```sh
AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- python3 /usr/local/sbin/ac-dev-billing-qa first-manager \
  --environment development --person-id "$DEV_OPS_PERSON_ID" \
  --expected-email qa-dev-operations-owner-aut959@example.test \
  --command-id "$DEV_MANAGER_COMMAND_ID" \
  --reason "AUT-959: first dev manager; approver ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0; owner card dc66a6ad-7823-4f4f-8c5e-02e4c63090bd"
```

Its governance fence refuses competing history. Never append `--apply`, change
UUIDs to bypass a refusal, or use another grant path. Read back the owner/grant
audit: the dedicated person holds only `platform_access_manage` and never signs
in for QA. No manager session/token is accepted by this operator workflow.

### Rollback-by-default fixture preview and guarded application

After the existing manager and named fixture inputs are present:

```sh
AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- python3 /usr/local/sbin/ac-dev-billing-qa fixture
```

Require `applied=false`, correct fixed provenance and 30 unused minutes.
AUT-969 rolls back the complete preview transaction, including prospective
identities, sessions, grants, audit and payment. Its collision/provider/history
guards are unchanged. After Root verifies the parent's authority, apply:

```sh
AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/application \
  /usr/local/sbin/ac-infisical-run -- python3 /usr/local/sbin/ac-dev-billing-qa fixture \
  --apply --approver ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0 \
  --data-approval dc66a6ad-7823-4f4f-8c5e-02e4c63090bd \
  --secrets-approval dc66a6ad-7823-4f4f-8c5e-02e4c63090bd \
  --billing-approval dc66a6ad-7823-4f4f-8c5e-02e4c63090bd --run-id "$DEV_FIXTURE_RUN_ID"
```

Record actual before/after, audit/run/approver and fake/test payment ID on the
parent. Preview IDs are not reservations; replay preserves the original
authority and verification time. The aligned non-root browser then uses real
Admin dev `/login`, `/v1/me`, `/v1/me/platform-access`; require the exact staff
identity and `platform_billing_manage`. Browser QA reads the named eligible
payment through normal Admin Billing API/UI, comparing ID, fake/test provenance,
original verification time and unused minutes. No deployed mocks/bypasses.
Browser QA alone performs the single authorized fictional refund afterwards.

Install rollback restores the saved script/sudoers bytes and modes; remove the
new root-only runner if absent before. No service/configuration changes are
part of this install. Previews/refused transactions roll back automatically.
A committed data change has no delete/reset rollback: preserve history and use
a separately reviewed, authorized superseding change. On timeout/unknown
outcome, retain command IDs and inspect before a same-intent replay. Find the
named temporary container with the metadata-only command:

```sh
docker ps --filter 'name=^/ac-dev-billing-qa-' --format '{{.Names}} {{.Status}}'
```

Read only its state with `docker inspect --format '{{json .State}}' <exact-name>`;
do not dump its environment. A killed Docker client can leave the bounded
container running. Establish its outcome before retrying or stopping it.
