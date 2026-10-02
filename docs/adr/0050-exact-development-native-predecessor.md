# ADR 0050: Exact development native predecessor

Date: 2026-10-02. Status: proposed for review under AUT-721; records the CTO
decision in AUT-718 and the [plan](/AUT/issues/AUT-720#document-plan).

## Context

The native installer re-checks the installed (previous) supervisor descriptor
before an upgrade. It maps a helper identity to the renderer path of its own
release. The development host runs helper `390b4285…` with image `sha256:a855e2…`,
whose descriptor names the renderer of release `fd385bb6…` instead. Every
upgrade therefore stops with `native_units_release_mismatch`, so dev cannot move
to the reviewed native artifact N (`1e784afa…`).

## Decision

`EXACT_PREDECESSORS` in `install-sales-xray-native.py` holds one immutable entry:
`(development, 390b428568b443ae6b748ccb11e7789574c8c926,
sha256:a855e207cd866e97ddf6f50d75e33b93680b6c74ec1aa6dd8f9b517f249c57ae,
/srv/authority-closers/application/releases/fd385bb607ae1967e630fe2c98e0685790346fe6/scripts/render-sales-xray-native.py,
88f6e50960566c61d780e9fc2370c61c2db17c818c7d2c5963a8974ef70eec76)`.

- It is selected only in `install()`'s previous-descriptor branch, when the
  environment, helper, image and supervisor path all match. The selected path is
  used both by `_validate_descriptor` and by the full `_rendered_descriptor`
  comparison.
- The renderer that runs is still the candidate N renderer. The historical
  renderer R is only checked, before any lock or mutation: regular file, not a
  symlink, root-owned non-writable parents and root:acops owner on the host, and
  this entry's own hash. The global `RENDERER_SHA256` is not a substitute.
- Candidate checks are unchanged: an artifact or descriptor that names R is
  refused (`native_units_release_mismatch`, `renderer_path_not_release_bound`).
- Installer source C is separate from renderer/artifact N. Root runs released C
  with `--renderer /srv/authority-closers/application/releases/<N>/scripts/render-sales-xray-native.py`.
- Docker check (corrected runbook assertion, code unchanged): `.Id` must be one
  of the pair `{manifest digest, config digest}` from the same checksummed
  artifact manifest; `--native-image-config-id` is still the config digest. See
  the [runbook correction](/AUT/issues/AUT-720#document-runbook-correction).

## Alternatives

- Global alias from helper to any release renderer: rejected, it weakens
  candidate provenance.
- CLI override of the predecessor renderer path: rejected, operator input would
  decide trust.
- Relaxed hash set (AUT-158's reviewed list): rejected for this path; the
  predecessor keeps its own exact pin.
- Hand-edit the installed units or descriptor on the host: rejected, unrecorded
  host state.

## Consequences

Dev can upgrade from the exact installed helper with full checksum, re-render,
installed-byte equality, stop-before-publish and byte/state rollback. Any other
tuple keeps failing closed. Staging and production are unaffected.

## Reversal cost

Low. After dev runs an artifact-bound helper, delete the entry and its tests.

## Evidence

`tests/infra/test_sales_xray_native_installer.py`: dry-run of exact, legacy and
new predecessors; upgrade drain and mount-before-service; changed
environment/helper/image/supervisor tuples; checksum, re-render and installed
drift; reference path, parents, owner and hash; candidate alias; failed stop;
failed start with mixed enabled states; `main()` exit codes and output.
Fixtures are fictional; no Docker, systemd or host calls.

## Owner

Dev Environment Engineer · Sol (source). Root Operator runs the dev transition
on AUT-119 after the AUT-717 handoff.

## Supersedes

Nothing. Corrects the AUT-155 runbook's Docker `.Id` assertion only.

## Trigger to revisit

Dev no longer runs helper `390b4285…`, or a new environment needs a predecessor
exception. Either one means this entry is removed or a new ADR is needed.
