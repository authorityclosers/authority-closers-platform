# Free overview projection integration

The new Dipak report format is integrated into the release candidate alongside
the Gemini testing-credential smoke fix. The private guest and claimed-account
response now includes the validated `overview` object when present. Existing
reports without the new field keep the same response shape.

The projection keeps the full qualitative overview available to either owner,
preserves recording and transcript binding, and excludes internal provenance
fields. Numeric publication remains false. A forged extra provider-trace field
is rejected even when a caller bypasses normal model construction.

Validation: 47 focused report, structured-overview, access-projection and Gemini
smoke regression tests passed against the combined candidate. External JUnit:
`D:/AC-authority-closers-release-audit/projection-unit-20260914.xml`.

This is source integration evidence. It does not assert deployed guest upload,
provider execution, production report quality, or a completed hosted journey.
