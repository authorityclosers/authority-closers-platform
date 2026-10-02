# Exact approved release artifact cleanup (AUT-773 for AUT-766)

`scripts/data-changes/prune-approved-release-artifacts.py` removes only the
installer bundles listed in one digest-pinned manifest, using the installed
release engine's own retention, locks, `_remove_unretained` and history. It
removes no images, `.prune-*` leftovers, native/web helpers or anything outside
`/srv/authority-closers/application/artifacts/<full sha>`. Merging this tool
authorizes no deletion.

## Pins

- Manifest: `artifact-only-cleanup-proposal.json` (AUT-773 attachment
  `eaffc3c4-6c5a-413f-a5af-2af20afaa808`), 57,174 bytes, SHA-256
  `940a1254d1d62fecf364c6171da3b8f520b330c56120e0b08e2f4221ae0d36b9`, 155 bundles.
- Engine: `/opt/ac-release/current/ac_release.py` (release
  `f051cb828dc0d19a2f09d7ce472a84a7e81a6d49`), SHA-256
  `835d83ebf6984fd716af35c90d1ef3df4beed1f340a561aa3b70d346c57ca53f`.

## Commands (Root, from a checkout of merged `main`)

Dry run (read-only; reads the root-only application tree, writes nothing):

```sh
python3 scripts/data-changes/prune-approved-release-artifacts.py \
  --manifest <run-scratch>/artifact-only-cleanup-proposal.json \
  --manifest-sha256 940a1254d1d62fecf364c6171da3b8f520b330c56120e0b08e2f4221ae0d36b9 \
  --engine-sha256 835d83ebf6984fd716af35c90d1ef3df4beed1f340a561aa3b70d346c57ca53f
```

Apply, only after the owner's exact `approve delete: <the 155-bundle list>,
VPS` is verified on the issue or in chat (the reference records it; it does
not grant it):

```sh
python3 scripts/data-changes/prune-approved-release-artifacts.py \
  --manifest <run-scratch>/artifact-only-cleanup-proposal.json \
  --manifest-sha256 940a1254d1d62fecf364c6171da3b8f520b330c56120e0b08e2f4221ae0d36b9 \
  --engine-sha256 835d83ebf6984fd716af35c90d1ef3df4beed1f340a561aa3b70d346c57ca53f \
  --apply --approval-ref '<issue/comment id of the owner approval>'
```

Exit 0 means `dry-run` or `applied` with no errors; anything else exits 1 and
prints the reason. Staging stays paused; the tool never changes pause flags.

## Behaviour

- The manifest and engine are read once, digest-checked, then parsed or
  executed from those same bytes. Unknown fields, non-empty `images` or
  `leftovers`, `keep_recent` other than 10, duplicate or non-full-SHA ids,
  paths other than the fixed root plus the id, and non-empty `keep` are refused.
- `--apply` requires root and an approval reference. Under the engine run lock
  and the installer deployment lock it re-runs `artifact_retention(10,
  images=False)`. If any approved bundle is now retained, changed logical size,
  is a symlink, or holds anything other than the three regular installer files
  (`SHA256SUMS`, `application-images.tar.gz`, `release-images.env`), nothing is
  removed and a `refused` history entry is written.
- Otherwise `_remove_unretained` gets only the still-unretained approved
  bundles, with no leftovers and no images (rename to `.prune-*`, then remove,
  errors collected as before). Unapproved bundles that are newly eligible stay
  and are counted. Already absent approved bundles are listed as `absent`, so a
  repeat run is safe.
- One `prune-approved-artifacts` history entry is appended under both locks
  with issue AUT-766, manifest and engine digests, approval reference, exact
  removed ids and count, freed bytes, absent, refused and errors. The run prints
  before/after free bytes. A refusal before the locks (digests, shape, root,
  another engine run or install) writes no history.

## Checks

- `tests/infra/test_approved_release_artifact_cleanup.py`: 29 fictional cases
  against the repository engine in `tmp_path` (dry run, approved-only apply with
  an unapproved eligible bundle kept, repeat run, newly retained bundle, 21
  tampering cases, root/approval requirement, both locks held during removal
  and history, running install refused, history write failure after removal reported as failed). Mutation checks: disabling the
  retained, size, path, bundle-shape, restricted-report or history-under-lock
  rule each fails at least one case.
- Read-only on the VPS as a non-root user: the reviewed manifest and installed
  engine pass both pins (155 entries, 49,271,489,830 logical bytes); the dry run
  then stops with `Permission denied` on the application tree, so Root runs it.
