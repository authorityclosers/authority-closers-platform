# Media safety socket-root normalization — 2026-09-13

The fixed ClamAV socket root is `/srv/authority-closers/volumes/media-safety-socket`.
Its canonical host identity is UID/GID `100:100` and mode `0755`; the root is
non-writable by the scanner group and other users. A parent setgid directory can
leave this root at mode `2755`, which is safe for traversal but fails the
application release installer’s exact mode gate.

The source-owned application installer clears only the setgid bit when the root
is already a real `100:100` directory at mode `2755`, then requires the exact
`100:100:755` result. The media-safety controller applies the same bounded
normalization independently and rejects ownership, type, writable-bit, or base
mode drift. It never broadens a non-canonical base permission mode.

Focused proof:

```text
pytest -q tests/infra/test_media_safety.py -k socket_root_clears_parent_setgid
```

The test uses a disposable directory with mode `2755`, mocks only the privileged
ownership observation, and verifies that the resulting mode is exactly `0755`.
No host socket, container, database, or deployment state is used.
