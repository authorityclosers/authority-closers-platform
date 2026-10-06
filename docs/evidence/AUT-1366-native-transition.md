# AUT-1366 governed native transition

Source checkpoint, 6 October 2026. This receipt does not authorize host changes.

The release engine prepares a staging-only exact-source native transition before
the automatic core deploy. It retains the existing approval, predecessor unit
descriptor, image/helper identities and application-only rollback source. The
native installer accepts a separately verified release renderer for an engine
transition that occurs before the target core source is installed.

Completed baseline verification: 271 existing tests passed across the release
engine, backup installation, native installer, activation preparer and native
compatibility suites (74 seconds). Ruff formatting and lint passed for the two
changed source files. Focused transition fault tests and the reviewed Root
bootstrap/recovery handoff are still required before opening the PR.

No staging, production, provider, database, engine installation or pause/resume
operation has been performed. All implementation work is in the platform lane.
