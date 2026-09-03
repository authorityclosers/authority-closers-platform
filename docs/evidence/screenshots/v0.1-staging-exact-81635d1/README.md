# Staging auth journey evidence — exact release `81635d1`

- Capture date: 2026-09-01
- Learner host: `https://staging.authorityclosers.com`
- Deployed release:
  `81635d18569c06962af37c1fa64d0d5814d0f2bf`
- Browser: selected Codex in-app browser

This pack records the public authentication and recovery family from the exact
deployed release. It contains no password, reset token, OAuth code, cookie, or
provider payload.

## Screens

| Journey state                              | Desktop                                         | Mobile                                       |
| ------------------------------------------ | ----------------------------------------------- | -------------------------------------------- |
| Sign in                                    | `login-desktop-1488x1058.jpg`                   | `login-mobile-390x844.jpg`                   |
| Registration and exact consent             | `register-desktop-1488x1058.jpg`                | `register-mobile-375x1125.jpg`               |
| Recognized Google identity missing consent | `google-consent-recovery-desktop-1488x1058.jpg` | `google-consent-recovery-mobile-390x844.jpg` |
| Password recovery request                  | `forgot-password-desktop-1488x1058.jpg`         | `forgot-password-mobile-390x844.jpg`         |
| Verification link missing token            | `verify-email-desktop-1488x1058.jpg`            | `verify-email-mobile-390x844.jpg`            |
| Reset link missing token                   | `reset-password-empty-desktop-1488x1058.jpg`    | `reset-password-empty-mobile-390x844.jpg`    |

The mobile registration capture is a full-page image at a configured `390px`
viewport. Its `375px` image width is the browser content box after the visible
vertical scrollbar is excluded.

## Measured checks

- Login at `390px`: client width `390`, scroll width `390`, one `h1`.
- Registration at `390px`: client/scroll width `375`, one `h1`, all text,
  email, telephone, and password inputs render at `16px`; Google is disabled
  until the exact learner-consent checkbox is checked.
- Google consent recovery at `390px`: client/scroll width `390`, one `h1`, no
  RFC 7807 payload or request ID, and `Review and continue` targets
  `/register`.
- Forgot-password, verification, and reset empty-token states at `390px`:
  no horizontal overflow and one primary `h1` each.
- Desktop captures at `1488 x 1058`: no horizontal overflow and one primary
  `h1` each.

## Runtime checks associated with this pack

- Immutable deployment controller proved the Git archive and running images
  match the exact release.
- Learner, API, worker, admin, and PostgreSQL containers became healthy.
- Learner/PWA assets, API live/ready/catalog, Cloudflare Access, WordPress
  boundary, and Google OAuth start/callback binding passed compact smoke.
- A fresh password-recovery request was accepted after cutover and Gmail
  received `Reset your password — Authority Closers` from
  `learn@authorityclosers.com` at `2026-09-01T02:23:32Z` for
  `admin@authorityclosers.com`.

The selected browser did not have an authenticated learner session after the
cutover, so this pack does not claim a current-release authenticated mobile
home/module capture. That remains a separate gate.
