# App compatibility switches

`GET /v1/app/config` is public and contains no personal data. Responses cache for
60 seconds. Web refreshes once a minute and on window focus. Settings take effect
on API restart through the normal release/config process; never edit production
by hand. Defaults block no version and switch no features off.

Settings (all prefixed `AC_`):

- `APP_MIN_ANDROID_VERSION`, `APP_MIN_IOS_VERSION`, `APP_MIN_DESKTOP_VERSION`
- `APP_RECOMMENDED_ANDROID_VERSION`, `APP_RECOMMENDED_IOS_VERSION`, `APP_RECOMMENDED_DESKTOP_VERSION`
- `APP_FEATURES_OFF`: comma-separated registered keys, currently `clarity` (the
  existing Clarity consent and environment checks still apply when enabled).
- `APP_UPDATE_MESSAGE`: optional plain text, at most 280 characters.

Versions are three numeric parts, e.g. `1.10.2`, no leading zeroes, suffixes or
prefixes; each part is at most six digits. Default is `0.0.0`. Invalid versions
fall back individually to `0.0.0`. Unknown feature keys invalidate the whole off
list; it falls back to empty. Invalid messages are omitted. Warnings name settings
only. Config fetch/validation failure leaves the app usable.

Raise the recommended Android version first. Raise the minimum only after that
build has been live on Play for **at least three days**, rollout is complete for
all affected users, and the operator has verified installation and the update
link. Keep minimum at or below recommended. The existing download-link app uses
a different signing key: confirm affected users can move to Play before blocking
it. Roll back a mistaken minimum to `0.0.0` through the normal configuration path.

The web client recognises `SalesXrayApp/<major.minor.patch>` in the installed
Android app's user agent. Browsers are unaffected. Required updates cannot be
dismissed; recommendations can be held for three days on that device. The button
opens the Play listing. The current SXPhone bridge has no in-app update method.
iOS and desktop values are published for future clients; this web guard only
recognises the existing Android marker.

API changes only add: keep old fields, routes and meanings working for installed
clients. This guard is a user-experience switch, not authorization and not a reason
to break the API. A feature off-switch applies only where `useFeatureEnabled` (or
`FeatureGate`) is wired; register and test each new key at both ends before use.
Do not switch on a provider or bypass consent through this config.
