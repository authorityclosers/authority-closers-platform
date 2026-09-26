# Sales Xray approval readability recovery

The hosted API and dedicated worker run as UID/GID 10001. A newly prepared,
digest-pinned approval with mode 0440 and the operator group passed root release
validation but could not be read by either runtime. API composition consequently
disabled Sales Xray acquisition while generic API health remained healthy.

The existing explicit `--repair-worker-metadata` release operation now repairs
the non-secret approval as well as the worker manifest. After validating the
complete activation descriptor and its references, it checks the exact approval
bytes and repairs only its group to 10001 and mode to 0440. Root ownership,
approval contents, digest, expiry and provider limits remain unchanged. The
operation uses an open file descriptor and refuses untrusted paths, changed
digests, writable files, symlinks, hardlinks and non-root ownership. Ordinary
projection without the repair flag remains read-only.

Validation:

- Windows lifecycle tests: 37 passed; 23 POSIX cases explicitly skipped.
- Ruff lint and formatting passed for both changed Python files.
- A separate Linux root proof reproduced EACCES for an actual UID/GID 10001
  child, then verified exact bytes were readable after repair. Repeating the
  repair preserved bytes and metadata. Five invalid-input cases were refused
  without mutation: wrong digest, symlink, hardlink, non-root owner and writable
  approval. This proof used disposable synthetic files only, with no database,
  credentials, network providers or application-state changes.
- The full lifecycle test includes the same real UID/GID check in the existing
  required Linux root CI gate. Its run result must be checked before merging.

This fix does not establish report quality, authorize another provider request,
or prove a complete staging/production journey. Recovery must separately verify
Sales Xray composition as the runtime user and authenticated saved-call access;
generic API health alone is insufficient.
