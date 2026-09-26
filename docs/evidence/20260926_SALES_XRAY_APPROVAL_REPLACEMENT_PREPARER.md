# Sales Xray hosted approval replacement preparation evidence

Date: 2026-09-26

## Scope

The offline native activation preparer accepts an optional replacement hosted
approval for a new target release. When the option is omitted, it retains the
source activation's existing approval path and digest. The preparer does not
activate a release, contact a provider, access a database, or edit the source
activation artifacts.

The replacement input is supplied as a file plus its lowercase SHA-256 digest.
The preparer parses the exact bytes with the hosted `load_hosted_approval_bundle`
contract and requires canonical serialization. It checks the approval window,
environment, provider-control tenant, stage and acquisition-policy expiry,
bounded benchmark and supplement windows, and the hosted prohibition on
synthetic provider scopes. Every provider credential reference used by an
approval stage or acquisition route must already be configured by the source
service. Duplicate configured provider or credential references are rejected.

Replacement is refused when the target release equals the source activation's
release, the file digest does not match, only one of the file/digest arguments
is supplied, or any hosted scope check fails. The output contains the exact
replacement bytes in a digest-named approval artifact. Its digest and path are
bound in the generated activation descriptor, compose environment, and service
configuration. The output is written with exclusive file creation; an existing
nonempty output directory or colliding artifact is refused. Source artifacts
remain unchanged.

The existing native artifact source-commit check is unchanged: the immutable
native manifest's `source_commit` must equal the new target release SHA. This
change does not add native artifact reuse across releases.

## Verification

Focused coverage verifies replacement bundle creation and all generated
approval hash bindings, source-byte preservation, output no-clobber behavior,
unchanged default approval carry-forward, same-release refusal, incomplete
arguments, digest mismatch, noncanonical input, expiry, environment and tenant
mismatch, provider and credential mismatch, and synthetic hosted-scope refusal.
The pre-existing native source-commit mismatch test remains in the focused file.

Command:

```text
uv run --frozen pytest tests/unit/test_prepare_sales_xray_native_activation.py -q
```

Result: **17 passed**.

```text
uv run --frozen ruff check infra/application/scripts/prepare-sales-xray-native-activation.py tests/unit/test_prepare_sales_xray_native_activation.py
```

Result: **All checks passed**.

No provider calls, database writes, service activation, deployment, commit, or
push were performed for this change.
