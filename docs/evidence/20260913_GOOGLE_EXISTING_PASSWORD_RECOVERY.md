# Existing password account recovery after unlinked Google sign-in

The `registration_required` callback now offers **Sign in with password**, with
the existing validated course/activity context. It explains that Google can be
connected from account settings after sign-in. The UI does not infer account
existence from email and does not change identity-linking, consent, membership,
or enrollment behavior.

This fixes the release owner's reproduced production path where an existing
password user saw only Create free account after selecting unlinked Google.
The independent navigation review identified no conflict with this bounded
recovery path. Main reviewed the two-file diff and ran the actual callback
component suite under Node 24: **15 passed**. The added mounted regression checks
the password link, exact preserved context, and settings guidance.

Receipt: recovery packet `google-existing-account-recovery-tests.log`.
This source-only handoff is independently cherry-pickable from the separate
email outbox changes. Exact deployed Google acceptance stays with the release owner.
