# Deterministic midstream video mutation test

Base: `d1f20ea75a7f36af7061d89f6ec303b8afc574e2`.

The full unit run intermittently failed
`test_read_detects_midstream_mutation`: after a same-length in-place rewrite,
the next 16-byte chunk did not always raise. A bounded local reproduction of
the unchanged fixture on Windows performed 200 writes. It detected 195 and
missed 5. All five misses had exactly equal before/after `fstat` identity
tuples; there were no misses when that tuple changed.

The production identity helper deliberately uses Windows birth time instead
of the differing legacy `lstat`/`fstat` ctime semantics. A rapid same-length
rewrite can therefore retain the entire observed tuple when mtime does not
advance. The fixture accidentally depended on the filesystem clock advancing
between two very close writes.

The test still performs the actual same-length payload overwrite after yielding
the first chunk. It now explicitly advances mtime by two seconds with `os.utime`,
asserts that size is unchanged and the timestamp differs, then requires the
next chunk to fail through the existing live identity check. No sleep, retry,
skip, production monkeypatch or relaxed assertion is added.

Production storage code is unchanged. `_inspect` still hashes the complete
object before range admission; the existing four
`test_same_stat_identity_cannot_hide_changed_bytes` cases continue to corrupt
real bytes while forcing equal identity tuples, and reject head, prefix, range
and immutable retry through checksum validation. Verification leases still
hold cooperating writer locks from full hashing through the short commit.
The documented dedicated, service-owned, immutable-directory requirement
remains necessary; this fixture does not claim protection against arbitrary
untrusted concurrent in-place writers.

Validation on the isolated worktree:

- `tests/unit/media/test_video_file_storage.py`: **74 passed** in 19.48 seconds.
- The changed midstream test: **200/200** additional consecutive invocations
  passed against distinct temporary filesystem objects.
- Ruff lint and format checks passed; Git whitespace checks passed.

Read review confirms that only the mutation fixture and this evidence change.
No full suite, browser, database, VPS, or upload was run for this repair.
