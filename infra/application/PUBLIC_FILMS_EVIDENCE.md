# Immutable public-film deployment wiring — 2026-09-08

Status: implemented offline; staging and production release policies remain disabled.

The separate `public-films.json` policy selects an API-only override for the target
immutable release, including rollback. The legacy staging policy, manifest and
overlay remain unchanged and cannot be combined with the new delivery mode.
Enabled policy requires the exact environment and learner origin in that release.
No ambient environment flag or caller-selected destination activates this package.

The archive includes a byte-identical copy of the API's demonstration manifest:
`dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42`.
It pins 30 files / 54,274,209 bytes: two licensed 12-second technical excerpts,
not full films or Dipak instruction. No source URL is fetched.

The reviewed release helper's `install RELEASE ENVIRONMENT SOURCE_DIRECTORY`
command verifies the exact commit marker, complete inventory, lengths, hashes,
file identity and absence of links before copying inert bytes. Its fixed VPS
destination is `/srv/authority-closers/application/media-public-films/` followed
by the manifest digest. Installation uses an exclusive lock, atomic rename,
root ownership and exact file/directory modes 0444/0555; existing drift is denied,
not repaired. Only the API can receive the read-only `/run/ac-public-films` mount,
with `create_host_path: false`. Worker and migrator remain disabled with no root.

The ordinary installer preflights candidate and rollback packages before stopping
writers and strips the two new ambient settings before Compose invocation.
Archive validation requires the new policy, helper, overlay and manifest. Catalog
publication, media import/binding, learner authorization and runtime activation
are separate application gates; this wiring does not supply those authorities.

Offline validation:

- New deployment tests plus archive and legacy staging regressions: 137 passed,
  7 POSIX-only tests skipped on Windows, 1 Docker Compose test deliberately excluded.
- Ruff check and format check passed for the four scoped Python files.
- Thin/API manifest hashes match exactly; both policies remain false.
- Dispatch tests use test-owned no-op shell doubles, not Docker or real services.

Not executed: Linux atomic installation/mode tests, Docker/Compose, VPS rollout,
database import, network acquisition or production playback. These remain release
acceptance gates; no deployment or activation is claimed.
