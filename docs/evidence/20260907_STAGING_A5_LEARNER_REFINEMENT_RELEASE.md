# Staging learner refinement — a5eef0d

Status: **deployed staging slice, not completed Alpha or production release**.

## Exact deployment

- Application: `a5eef0df4b340070ac6e58f9912d73a3bf1d2f18`.
- Installed: **2026-09-07 15:43:47 UTC**, unchanged canonical staging installer.
- Exact packaging run `34137591803`; artifact `10025111244`, 178,752,696 bytes,
  SHA-256 `edbb76eb3285025e33b48054548ae8ece4d59bac498eb7771821f0f1313329d1`.
- Deployment record:
  `/srv/authority-closers/application/deployments/staging/20260907T154347Z-a5eef0df4b340070ac6e58f9912d73a3bf1d2f18.env`.
- Previous application `851ebc828c756c6ce42bf041a3f7c1d95183e5f9` retained for
  controlled rollback. A read-only live check confirmed `current-staging` still
  points at a5 during this evidence pass. No new production installation.

This slice includes the compact Profile, settings categories, simpler learner
notification/recovery copy, front-facing genuine Dipak portrait, cleaned lesson
presentation, removed floating Help button and native read-only progressive
player implementation. A player implementation is not a published media source.

## Authenticated live evidence

Existing authorized learner session; Chrome, Light theme. Five actual routes
(Home, Profile, Settings, Module 1 activity, Notifications) were captured in
settled states at **390×844 and 1440×900**, ten route/viewport combinations.
All final images are **viewport-only**: full-page attempts timed out. No
full-page coverage is claimed. Three older/loading captures are preserved and
explicitly excluded from settled coverage. No credentials or session state were
exported, and private screenshots are not committed to Git.

Observed checks: one H1 and no horizontal overflow for each tested viewport;
sidebar expand/collapse; Profile crop open/cancel without an upload; Settings
Appearance navigation with Light preserved. These do not prove actual avatar
persistence, every below-fold control, keyboard/reduced-motion/dark-mode behavior
or the full 320/768 Alpha matrix. Root separately inspected the settled Home,
mobile unavailable-video state and desktop Settings images.

The current activity correctly reports **video unavailable**. Notifications
also remain unavailable. Home still has an oversized empty plan panel. These
are unfinished product capabilities/polish, not passed full-journey acceptance.
No invented plan, completion or achievement data was introduced.

## Existing Drive release records

- [Version folder](https://drive.google.com/drive/folders/1TGqpOVkvkaaGNJDUsXHza8TdFl8lVZVI).
- [Before: ten authenticated captures and manifest](https://drive.google.com/drive/folders/1qlbfmERRmgs11B-dR2BDjcai4Xi2516_).
- [Staging live: ten settled, three preserved historical captures and manifest](https://drive.google.com/drive/folders/10s9JsIwrDSqIIVxwEATFXr0Sxd5l-Eao).
- [Live manifest](https://drive.google.com/file/d/18rY-8jEvmNUaLG9XggdvHpnWrwWbiAPj/view).

Before upload/readback completed 11/11; after upload/readback completed 14/14.
The capture agent verified each ID/name/MIME/byte count/parent against local
files, retaining local hashes in its private register. No sharing ACL changed.
This release note's upload is separately recorded after provider readback.
Appending the native Google Docs ledger remains pending: the required trusted-
read bridge rejected this Windows absolute workspace path before any write.
The existing ledger has not been flattened or overwritten.

## Infrastructure and remaining gates

Foundation `a6d8472a31bff67c9cfcfce886a80e606a34f88a` separately installed with
actual synthetic access/error-log redaction proof. Canonical a5 staging logical
backup plus off-site isolated restore passed; see
[foundation rollout and restore proof](20260907_FOUNDATION_REPAIR_ROLLOUT.md).
The test films are installed immutably but remain policy-off; see
[film deployment boundary](20260907_ALPHA_STAGING_FILM_DEPLOYMENT_BOUNDARY.md).

Next: explicit platform/Studio permissions preserving learner membership,
normal identity onboarding for the named operators, reviewed film-on release,
authorized publication and real playback/seek/captions/rendition/expiry/tenant-
negative evidence. Adaptive playback, profile persistence, quiz/competition
journeys, performance/PWA acceptance and independently configured production
remain open. The full Alpha goal is unchanged.
