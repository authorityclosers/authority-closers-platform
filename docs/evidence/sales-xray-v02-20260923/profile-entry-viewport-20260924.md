# Account entry and profile viewport, 2026-09-24

The selected-call account access form now offers a show/hide password control with a 44px target, changing only the existing input's type. The password remains in that input and is cleared after submission. The control exposes its current state through its label and `aria-pressed`.

The profile form defaults new phone entry to India (+91). A ten-digit Indian entry is normalized to E.164 before the existing profile update request. Other selected regions require an explicit international number; spacing and common punctuation are removed before validation. A stored non-Indian number requires an explicit region selection rather than assuming it is Indian. The request still sends only canonical `phone_number_e164` and does not claim phone verification. The profile panel is bounded to the available viewport with internal vertical scrolling so its actions remain reachable at narrow widths.

Verification: focused account-auth, account-profile, and account-profile-client Vitest suites passed (3 files, 27 tests); Sales Xray TypeScript and scoped Prettier checks passed. The local `profile.required` browser fixture did not open because this worktree's `/__review` route returned 404, so 320/390px visual behavior has not been confirmed here. Tests used synthetic account data and made no real account update or audio upload.
