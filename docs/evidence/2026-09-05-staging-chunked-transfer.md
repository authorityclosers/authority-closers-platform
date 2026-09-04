# Staging chunked-transfer controller evidence

**Status:** implementation and test evidence; staging promotion is not claimed by this record.

## Problem

The exact-release staging controller could package the reviewed application
release, but the single 169 MiB image-bundle SCP transfer repeatedly dropped
through the Cloudflare Access SSH path. A failed remote-directory lookup could
also be masked by calling `Trim()` on missing stdout. The installer never ran
during those failed attempts, and the staging release pointer remained on the
previous healthy release.

## Implemented boundary

`scripts/Deploy-Staging.ps1` now:

- invokes native SSH/SCP processes with captured, bounded, secret-redacted
  diagnostics;
- preserves the generic retry policy for SSH exit `255` while limiting the
  image-part transaction to transport/checksum exits `1` and `255`;
- writes a deterministic LF-only, UTF-8/no-BOM part manifest on Windows;
- splits only `application-images.tar.gz` into ordered 16 MiB parts;
- uploads each part to a remote `.partial` path, verifies exact size and
  SHA-256, and atomically publishes it before advancing;
- safely recovers when the remote rename completed but the client lost the
  acknowledgement;
- rejects malformed, missing, reordered, extra, linked, oversized, or corrupt
  parts before reassembly;
- verifies the reassembled archive against the already API-digest-verified
  `SHA256SUMS` file, then reruns strict whole-bundle verification before the
  installer;
- attempts remote and local private-stage cleanup independently while
  preserving the original deployment failure as the primary error.

No production endpoint, database, provider, DNS record, or external side
effect is enabled by this change.

## Executable validation

The focused controller suite includes PowerShell/Bash behavior coverage for:

- raw LF-only manifest bytes and deterministic multi-part reconstruction;
- exit `1` and `255` transfer/verification retry paths;
- an uncertain disconnect after atomic rename;
- corrupt partial recovery;
- Cloudflare query-string, labeled-secret, and bare-JWT redaction;
- remote-cleanup failure followed by attempted local cleanup.

Validated on the trusted Windows operator host with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/infra/test_staging_controller.py -q
.\.venv\Scripts\python.exe -m ruff check tests/infra/test_staging_controller.py
git diff --check
```

PowerShell AST parsing of `scripts/Deploy-Staging.ps1` also passed with zero
parse errors. The focused pytest result was `9 passed`.

## Release proof still required

This controller change is complete only after it is reviewed and merged. The
separate exact application release must then be promoted to staging and prove:

1. the server release pointer equals the requested 40-character SHA;
2. release files and running container image digests match that SHA;
3. learner, admin, API, OAuth, access, and boundary smoke checks pass; and
4. exact-release visual evidence is stored as real image files in the matching
   Drive release folder before any production promotion.
