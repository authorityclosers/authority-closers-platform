# First-tenant owner bootstrap

This is an explicit operations command for an already OAuth-verified canonical
person. It never creates a `Person` or `ProviderIdentity`, and it refuses
production unless the operator supplies the explicit production opt-in.

The API image must already contain the current package and the database must
already be migrated. `AC_DATABASE_URL` and `AC_ENVIRONMENT` are supplied to the
container by the deployment environment; the identity email, tenant slug, and
tenant name are command inputs, not application defaults.

Example staging invocation (replace the values for the intended verified
person and tenant):

```sh
python -m ac_platform.bootstrap \
  --environment staging \
  --email admin@authorityclosers.com \
  --tenant-slug authority-closers \
  --tenant-name "Authority Closers"
```

The command commits one transaction only after it has locked and validated the
canonical person, the tenant, and the composite membership. Re-running the
same command is safe when the existing tenant has the same name and the
existing membership is already an active `owner`; mismatched or inactive state
fails closed without repair. Active unrevoked, unexpired sessions for the
person are selected to the resulting tenant. The JSON result contains only
identifiers and counts; it does not print database settings, tokens, or other
secrets.

For production, repeat the same command with the deployment's explicit
production environment and add `--allow-production` only after the verified
person, slug, and name have been independently confirmed.
