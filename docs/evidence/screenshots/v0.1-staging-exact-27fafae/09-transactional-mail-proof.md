# Transactional mail proof

Observed on 2026-09-01 after deploying exact release
`27fafaea1e5de41ae6a830746b1d832b42c7d444`.

- Recovery was requested through the live staging `/forgot-password` form for
  `admin+alpha-learner@authorityclosers.com`.
- The UI returned its non-enumerating `Check your inbox` confirmation.
- The staging worker reports:
  - environment: `staging`
  - release: `27fafaea1e5de41ae6a830746b1d832b42c7d444`
  - provider: `resend`
  - external-side-effect hold: `false`
  - sender: configured (value redacted)
- Resend then showed the newest row as:
  - recipient: `admin+alpha-learner@authorityclosers.com`
  - status: `delivered`
  - subject: `Reset your password — Authority Closers`
  - sent: `just now`

No message body, reset URL, token, provider credential, or session value was
opened or recorded.
