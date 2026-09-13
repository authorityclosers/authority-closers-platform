# Hosted acquisition and Gemini release inputs

The release-owned API overlay now passes the exact native helper socket and
immutable image reference for measured guest uploads. It includes the explicitly
enabled acquisition settings, public challenge site key, policy revision and a
narrow challenge-only file mount. Provider identity mounts remain worker-only.
Gemini has its own provider-specific directory alongside ElevenLabs and Groq.

The installer clears ambient copies of every new input before selecting the
target release's descriptor. The validator binds API preflight to the worker's
native image, validates the public site key and revision, and continues rejecting
unapproved environment keys. The ordinary worker, migrator and frontend anchors
receive no additional credentials.

Validation: `tests/infra/test_sales_xray_hosted_lifecycle.py`: 21 passed and 16
explicit POSIX ownership/mode skips on Windows. New negative cases rehash the
descriptor after changing the native image or acquisition metadata, confirming
that the semantic binding is still checked. Required Linux ownership checks remain
part of the combined CI gate before deployment. This source change does not claim
that the public upload composition or a hosted report journey has been deployed.

Gemini configuration was separately prepared in Infisical `dev`, project
`b421c44e-4599-4394-8df6-758ed8aedfed`, path `/sales-xray-test/gemini`.
Its only secret is `GEMINI_API_KEY`, matching the already-tested key in the parent
testing folder. A read-only service identity for this exact folder is installed
at `/etc/authority-closers/secrets/sales-xray/identities/gemini/token`, UID10001,
mode0400, expiring 2026-09-20 22:53 UTC. Metadata and readback were checked without
printing secret values. No provider request or runtime activation occurred during
this scoped-identity preparation. An unused first token was revoked.

Private receipts outside Git:
- `D:/AC-authority-closers-release-audit/hosted-acquisition-mounts-20260914.junit.xml`
- `D:/AC-authority-closers-release-audit/gemini-scoped-key-20260914.json`
- `D:/AC-authority-closers-release-audit/gemini-scoped-identity-20260914.json`
