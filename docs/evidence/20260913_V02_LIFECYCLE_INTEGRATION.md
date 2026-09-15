# v0.2 hosted lifecycle integration

The consolidation tree integrates native supervision, distinct operations control,
single-charge audio minutes and hosted worker lifecycle from the reviewed Sales
Xray lane. The ordinary filesystem-media selector is retained alongside the hosted
selector; both resolve the requested release on each Compose invocation.

The first combined test run exposed incomplete shell extraction in two tests: the
hosted test omitted the existing filesystem selector, and the profile test omitted
the new hosted selector. Both tests now execute the actual required installer
functions. Runtime access checks were not bypassed or stubbed to make them pass.

Combined verification:

- Conversation unit and native supervisor suite: 519 passed, 17 skipped in 28.61s.
  The skips are 16 cases requiring a native build and one POSIX ownership case;
  this Windows run is not native numerical or Linux ownership evidence.
- Hosted lifecycle and profile installer suite: 23 passed, one POSIX ownership
  skip in 12.38s. This includes exact target overlay selection, ambient configuration
  removal, normal drain, forced exit 137, surviving worker and failed-drain rollback.
- Ruff check and formatting pass for the integrated test files.

A broader application-release test pass exposed seven more outdated shell test
fixtures after integration: the application probe omitted the real hosted
selector, containment expected one combined service stop, and the startup assertion
expected a literal worker name. The fixtures now include the actual selector and
ordered stop helper, preserve the accepted-write/no-restore assertions, and check
the release's worker array. All seven regressions pass in 8.30s; receipt:
`D:/AC-authority-closers-release-audit/v02-lifecycle-application-02.xml`.

External receipts are retained at
`D:/AC-authority-closers-release-audit/v02-unit-048b3be.xml` and
`D:/AC-authority-closers-release-audit/v02-lifecycle-e683f25-02.xml`.

The committed overlay carries file references, not credentials. Activation still
requires the exact release's external approved descriptor and hashes, provider
configuration and native helper. These integration results do not establish live
activation or authorize paid inference. Linux ownership, final CI and actual
staging/production acceptance remain required.
