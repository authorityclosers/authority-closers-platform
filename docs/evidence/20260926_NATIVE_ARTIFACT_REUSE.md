# Reuse a verified native artifact without relabeling its source

The hosted deployment guide already treats the API and native runtime as
separate immutable artifacts. The offline preparation command nevertheless
required the native source commit to equal every later API release. A change to
the API or interface therefore demanded a redundant native image build even
when every native input was unchanged.

The default remains exact-source admission. Optional `--native-reuse-proof`,
`--native-reuse-proof-sha256`, and `--source-repository` arguments enable an
offline comparison against the original CI bundle. They must be supplied
together. This is a compatibility check, not an override flag.

The verifier checks the original source tree, all 14 reviewed Docker recipe,
workflow, kernel and helper inputs at both full commits, including file modes.
It reads Git objects with replacement refs disabled. Dirty worktree files are
not evidence. An unfamiliar Dockerfile recipe is refused until its dependencies
are reviewed. The three host-helper recipes also have explicit reviewed hashes;
an unfamiliar helper import closure is refused even if source and target match.
Reuse retains the existing image's package versions; it does not
claim to refresh operating-system packages or replace vulnerability review.

An operator must capture the original GitHub workflow run and artifact metadata
through authenticated `gh api`, independently review them, and pin their exact
SHA-256 hashes in the proof. Local JSON alone is not proof of a GitHub response.
The run must be a successful manual native workflow for the original source and
repository. The artifact must belong to that run, repository and source. The
retained ZIP must match GitHub's size and SHA-256. Its six-file inventory and all
payload checksums are checked without extraction. Helper archive entries must
be regular, bounded, unique and byte-identical to the original Git source.
The existing native-manifest parser still checks the runtime platform, doctor
result, schema and immutable image/config pair. The canonical installer remains
responsible for image loading, installed helper identities, sandbox and health.

The proof schema `ac.sales-xray.native-reuse-input/1` contains:

- `repository`, `native_source_commit`, and `target_release_id`;
- `artifact_metadata` and `workflow_run`, each with an absolute `path` and `sha256`;
- the absolute retained `archive_path`.

The original native manifest is never edited. A separate compatibility receipt
records both commits, both trees, per-input hashes/modes/sizes, CI and archive
identity, image/config identity, and the prepared activation digest. Hosted
activation schema `/1` remains unchanged. Provider approval and credential
scope validation remain independent; compatibility grants no provider calls.

## Verification

The initial final run passed 47 tests in 101.45 seconds. Independent Opus review
requested helper dependency-closure evidence, additional negative tests and
sanitized corrupt-compression errors. After addressing those findings, 61 tests
passed in 155.13 seconds. Coverage includes preparation through the real parser
and verifier without monkeypatching, partial-argument rejection, bounded
archives, Git replacement refs, mode-only changes, artifact/run/fork binding,
same-size ZIP tampering, proof scope and corrupt gzip/deflate. These are not
production verification. Ruff passed; strict mypy passed for both scripts.

The reviewed runtime and helper import stdlib plus the packaged signal parser.
The smoke harness's optional `acquisition_source` import is guarded by
`ImportError`; the minimal bundle explicitly reports that upload preflight
measurement is unavailable. This optional full-application measurement is not
claimed as a minimal-bundle result. The retained six-file helper was extracted
only after verification and imported with `python -I -S`, without the repository
or site packages on its import path. Runtime, helper and smoke imports passed;
the optional full-app class was absent as designed. No socket, Docker process
or provider was invoked.

The canonical installer's `load_native_artifact_binding` independently checks
the supplied native manifest digest, canonical original-source helper path,
helper archive digest and installed helper bytes against that archive. It does
not relabel the helper as the API target. The release operator must still pass
that same reviewed manifest digest; the compatibility receipt is evidence, not
a new installer authorization path.

The retained native bundle for source
`1ee6a6d893b7a432fa187e3b9b56f6b49cc9dccd` was independently checked against
API candidate `01743f580e3583821521fe62d1649f7c1a3aaf9b`. All 14 inputs matched.
Original CI run `36137006219`, artifact `10865472476`, ZIP SHA-256
`2e764a8d526cbf58d80ce518db351c6fc0bafaaf604b6671c3a7acc6ab6b982d`,
and native manifest SHA-256
`99e5239b8938b820c8b3c8148ff29fd6dc79cf8a88f0b1b829dbccc24c495b71`
matched. The actual retained-artifact check invoked `verify_reuse`; the full
`prepare()` integration uses a synthetic, complete-shape manifest in tests.
No provider call or activation was performed. A different final API commit
requires a new target-bound proof.

```powershell
uv run pytest tests/unit/test_native_artifact_compatibility.py tests/unit/test_prepare_sales_xray_native_activation.py -q
uv run ruff check infra/application/scripts/native_artifact_compatibility.py infra/application/scripts/prepare-sales-xray-native-activation.py
uv run mypy --follow-imports=silent infra/application/scripts/native_artifact_compatibility.py infra/application/scripts/prepare-sales-xray-native-activation.py
```
