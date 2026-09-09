# Staging release — Alpha foundation and presentation

## Verified deployment

Release `851ebc828c756c6ce42bf041a3f7c1d95183e5f9` was installed on staging
at **2026-09-07T13:57:30Z** by the repository's checksum-verified
`scripts/Deploy-Staging.ps1` controller, which exited 0. VPS `current` resolves to
`/srv/authority-closers/application/releases/851ebc828c756c6ce42bf041a3f7c1d95183e5f9`.
This is a released foundation slice, not whole-Alpha acceptance or production.

- [Merged PR39](https://github.com/authorityclosers/authority-closers-platform/pull/39).
- [Exact main validation](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34127970592).
- [Successful release packaging](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34128026742).
- Artifact ID `10021455273`, `ac-application-851ebc828c756c6ce42bf041a3f7c1d95183e5f9`:
  176,678,143 bytes, SHA-256
  `8a3b809cdc0814367e8f584d1704997858239ba45206a5f90a8ed14424ade8c4`.
- Previous retained release: `31aee3ce5915e476c08a722f8b28768b49b514cf`.

Controller smoke checks passed learner root, health, public assets and service
worker; API live/ready/program catalog; disabled docs/OpenAPI; admin's exact
Cloudflare Access boundary; Google OAuth callback/cookie safety; and unchanged
WordPress apex/www. Learner, admin, API and PostgreSQL were healthy; worker up.
The release used normal immutable installation, not manual SQL edits.

Pre-migration dump:
`/srv/authority-closers/backups/application/staging/20260907T135649Z-pre-851ebc828c756c6ce42bf041a3f7c1d95183e5f9.dump`.
Dump creation and `pg_restore --list` passed. This is not a full restore drill.
Migration head remained `20260904_0018`. Deployment record:
`/srv/authority-closers/application/deployments/staging/20260907T135730Z-851ebc828c756c6ce42bf041a3f7c1d95183e5f9.env`.
No secret values are included in this evidence.

## Included and excluded

Included: supplied-kit company/academy/platform presentation and selected
runtime artwork, existing verified founder portrait, theme and navigation
foundation, optional-plan dashboard loading, editorial Home, Discover and
My Learning refinements, and tested media fixture preparation foundations.
See [presentation pass2](20260907_ALPHA_PRESENTATION_PASS2.md) and
[foundation integration](20260907_ALPHA_FOUNDATION_INTEGRATION.md).

Not included: subsequent front-facing portrait replacement, compact Settings
and Notifications, floating Help removal, new Profile/player polish, actual
VPS film mounting/import/delivery, new Studio authoring, usernames, quizzes,
streaks or leaderboards. PR40's later signed-delivery code is not part of this SHA.
Production is unchanged; independent environment/recovery prerequisites remain.

## Verified Drive evidence

- [Release folder](https://drive.google.com/drive/folders/1iDalvKbVbS2xP-xyBkuHGtLv163gwemo),
  exact name `2026-09-07 — 851ebc8 — Alpha foundation and presentation`, under
  existing Staging parent `1vSzm8VNdw__rP4yN-S-vWulK93Y_mpCx`.
- [Preserved BEFORE captures](https://drive.google.com/drive/folders/1v2yXtK0rBC0PlfIzqSWQF1-4H_66aUGA):
  anonymous staging31aee3c/local previews, never relabeled as the new release.
- [LOCAL fixture QA](https://drive.google.com/drive/folders/1d6RIX_kCVvFwuNTlLtvLg0LO8djTY7gD):
  synthetic learner data and route screenshots, explicitly not live learner evidence.
- [STAGING LIVE captures](https://drive.google.com/drive/folders/17Wwu4W3KENlvITsnZbfyFx8QRwjBCunu):
  eight anonymous public Home/login PNGs plus capture manifest. Two routes ×
  1440×900/390×844 × light/dark; Chrome152.0.7977.82; HTTP200/no redirects.
  All nine file metadata readbacks matched ID, name, byte count, MIME and parent;
  per-file capture hashes are in the register. No user profile or cookies were
  loaded, and no login/signup form was submitted.

The previous September5 release folder was not moved, renamed or overwritten.
Authenticated learner/admin changed-route live screenshots are still separate
acceptance work; anonymous captures do not establish those journeys.

### Native ledger follow-up

The [existing native release ledger](https://docs.google.com/document/d/1BvucZXG8_toHMSw6lunuPonvWxO6HqxO5JKrmepIymE/edit)
now contains the `851ebc8` staging entry, a native deployment-date chip and verified
release/live/BEFORE/snapshot links. Revision-locked append and readback succeeded.
All historical elements ending at or before index5388 were byte-for-byte equal
as structured content; existing embedded image `kix.5vlhurfdtni6` was preserved.

The trusted-read bridge captured immutable raw, normalized and control metadata,
then its Windows receiver failed committing the text artifact. We used the
already-produced normalized outline/control inventory, verified the unchanged
revision with a narrow read, and appended without touching earlier content.
No opaque controls were present. The first Drive Markdown snapshot correctly
records the ledger as pending at that snapshot; this follow-up supersedes it.
