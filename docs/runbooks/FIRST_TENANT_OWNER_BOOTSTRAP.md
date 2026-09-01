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
3. Use the admin-surface Google `register` flow to create the first verified
   canonical person. Learner registration remains unavailable until the public
   tenant and reviewed consent context exist.
4. Run the owner bootstrap below for that exact verified email. Record the
   returned tenant UUID without recording any session token or secret.
5. Store that exact active tenant UUID as `AC_OPERATIONS_TENANT_ID` in the
   target Infisical environment.
6. Create or validate the separate public learner context with the same
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
7. Reapply the same reviewed staging artifact so containers receive the new
   references, then run the controlled catalog seed and runtime acceptance:

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
