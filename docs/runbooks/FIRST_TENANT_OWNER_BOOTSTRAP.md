# First-tenant owner bootstrap

This is an explicit operations command for an already OAuth-verified canonical
person. It never creates a `Person` or `ProviderIdentity`, and it refuses
production unless the operator supplies the explicit production opt-in.

The API image must already contain the current package and the database must
already be migrated. `AC_DATABASE_URL` and `AC_ENVIRONMENT` are supplied to the
container by the deployment environment; the identity email, tenant slug, and
tenant name are command inputs, not application defaults.

## Empty-environment sequence

An empty database has no legitimate operations or public-learner tenant UUID.
Bootstrap it without inventing one or editing SQL:

1. Configure the database, session, OAuth, email-challenge, and Google secrets.
   Keep `AC_EXTERNAL_SIDE_EFFECTS_HOLD=true`; omit both tenant references.
2. Deploy the reviewed artifact. The held worker remains unavailable and all
   tenantless operations fail closed while the control tenant is absent.
3. Create or validate only the explicitly approved operations tenant using the
   new tenant-only command below. It creates no identity, verification,
   membership, role, capability, consent or session. The command ID, operator
   reference, reason, slug and name form one immutable audited intent; keep
   those exact inputs for replay and never include credentials in them:

   ```sh
   python -m ac_platform.bootstrap \
     --environment staging \
     --operations-only \
     --command-id <stable-reviewed-command-uuid> \
     --operator-reference <non-secret-approved-operator-reference> \
     --reason "Approved empty-environment operations tenant bootstrap" \
     --tenant-slug <approved-operations-slug> \
     --tenant-name "<approved-operations-name>"
   ```

   For production, use `--environment production --allow-production`. The
   reviewed baked release and explicit database configuration remain required.
   Successful output contains only `tenant_id`, `tenant_created`, and `replayed`,
   after the tenant and canonical audit commit together. A different later
   command or changed intent fails closed; this is not a general tenant-creation
   or tenant-repair command.

4. Store that exact active tenant UUID as `AC_OPERATIONS_TENANT_ID` in the
   target Infisical environment. Supply the updated configuration to the next
   canonical command through the same reviewed deployment environment.
5. Create or validate the separate public learner context with the same
   reviewed artifact. This command creates no person or membership:

   ```sh
   python -m ac_platform.bootstrap \
     --environment staging \
     --public-learner \
     --tenant-slug authority-closers-public-learners \
     --tenant-name "Authority Closers Public Learners"
   ```

   Store its returned UUID as `AC_PUBLIC_LEARNER_TENANT_ID`. Do not reuse the
   operations tenant: one person has one role per tenant, so an operations
   owner cannot simultaneously satisfy the public tenant's learner-role gate.

6. Configure the exact reviewed consent version and reapply the same reviewed
   artifact so containers receive both tenant references and that consent
   version. Staging legal text is not production consent approval.
7. The explicitly approved person completes normal learner-surface Google
   registration with current consent (or email verification followed by normal
   authenticated Google linking). Admin and Coach registration are forbidden;
   authentication alone must not create a new identity. Run the existing owner
   command below only for the exact verified OAuth identity explicitly approved
   to be the operations owner. Naming another administrator does not silently
   authorize another owner. The separate public membership remains `learner`.
8. For staging only, run the controlled catalog seed and runtime acceptance
   after the reviewed configuration reapplication:

   ```powershell
   pwsh -File scripts/Deploy-Staging.ps1 `
     -ReleaseSha <exact-40-character-sha> `
     -ReapplyConfiguration
   ```

Reapplying is an explicit mutation: it verifies and downloads the same
digest-bound artifact, takes a pre-migration backup, runs the idempotent
migration path, restarts the exact images, and reruns release/route/OAuth proof.
Without `-ReapplyConfiguration`, an already-current SHA remains a read-only
verification no-op.

## Held verification-email bootstrap for the initial activation hold

This is a bounded identity delivery recovery command. It is source-owned and
does not claim that production is launched or that recovery is reconciled. It
exists for the initial empty-environment deadlock while
`operations_recovery_state` is still generation `1`, status `held`, with hold
reason `initial_activation_requires_reconciliation`.

Run normal password registration first. The command accepts only the exact
active, unverified person, one unconsumed and unexpired verification challenge,
and its canonical pending verification event. It creates no person,
credential, challenge, membership, session, or identity assertion. It creates
the durable `outbox:<event-uuid>` job when needed, appends one immutable
operator audit intent, and keeps the global recovery hold in place:

```sh
python -m ac_platform.bootstrap.verification_email_cli \
  --environment production \
  --allow-production \
  --person-id <exact-person-uuid> \
  --challenge-id <exact-active-challenge-uuid> \
  --command-id <stable-reviewed-command-uuid> \
  --expected-email <exact-canonical-email> \
  --operator-reference <non-secret-approved-reference> \
  --reason "Approved initial activation verification delivery"
```

Staging and production require the reviewed Resend provider and valid sender
configuration before any database intent is written. The provider key is
`outbox:<event-uuid>`; the challenge ID is never used as an external
idempotency key. A 120-second job lease and 30-second provider timeout bound
the dispatch. A receipt is persisted before success is reported. Replaying the
same command ID returns the stored receipt without a second provider delivery;
an expired, consumed, superseded, restored-generation, or ambiguous challenge
remains refused or quarantined for normal audited reconciliation. Never print
the verification token. After mailbox verification, use the normal
authenticated Google linking flow and then the existing owner bootstrap.

The disposable PostgreSQL proof is
`tests/integration/test_verification_email_postgresql.py`; it covers the held
send, normal token consumption, replay, expired/consumed/restored refusal, and
durable ambiguity quarantine. The proof uses a random schema and must be run
only against the dedicated disposable PostgreSQL target.

An installed but held empty environment is not a completed production launch.
Email activation, production consent/content, additional membership and scoped
capability provisioning, and enabled media/practice providers remain separate
reviewed prerequisites. This tenant-only command does not enable any of them.

Example staging invocation (replace the values for the intended verified
person and tenant):

```sh
python -m ac_platform.bootstrap \
  --environment staging \
  --email admin@authorityclosers.com \
  --tenant-slug authority-closers \
  --tenant-name "Authority Closers"
```

The owner command commits one transaction only after it has locked and validated the
canonical person, the tenant, and the composite membership. Re-running the
same command is safe when the existing tenant has the same name and the
existing membership is already an active `owner`; mismatched or inactive state
fails closed without repair. Active unrevoked, unexpired sessions for the
person are selected to the resulting tenant. The JSON result contains only
identifiers and counts; it does not print database settings, tokens, or other
secrets.

The `--public-learner` form locks and validates only the exact tenant slug,
name, and active lifecycle state. It is idempotent, creates no membership, and
prints only the resulting tenant UUID and whether the tenant was created.

For production, repeat the same command with the deployment's explicit
production environment and add `--allow-production` only after the verified
person, slug, and name have been independently confirmed.
