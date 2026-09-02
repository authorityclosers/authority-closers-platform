# Slice release checklist

Candidate checkpoint: local implementation gates are complete. Exact-SHA CI,
packaging, staging deployment, and post-deploy authenticated browser proof stay
open until the immutable candidate exists.

- [x] Controlled-source changes and unresolved gaps are recorded.
- [x] Selected desktop/mobile reference and exact state are attached.
- [x] Route, ownership, API, authorization, privacy, and retention contracts exist.
- [x] Default, loading, empty, retryable error, terminal error, offline,
      permission, locked, partial, and success states are implemented as relevant.
- [x] Light-default behavior has no first-paint theme flash.
- [x] Navigation, avatar/account menu, keyboard focus, reduced motion, zoom,
      contrast, and target sizing pass.
- [x] Loading is route-shaped; shell chrome remains stable; duplicate requests are
      deduplicated where authorization permits.
- [x] Offline fallback is encrypted, owner-scoped, retained for no more than
      seven days, visibly stale, mutation-disabled, and never used for
      401/403/404/409 or canonical authority.
- [x] Logout, owner change, authorization loss, expiry, and tamper checks purge
      the bounded offline cache; cleanup failure is shown honestly.
- [x] Local VPS preview accepts only the exact staging API and anonymous catalog
      GETs; cookies/authorization are stripped and all private routes/mutations
      are rejected before the upstream request.
- [x] Unit, integration, contract, security, accessibility, and performance tests
      leave evidence.
- [x] Reference and implementation screenshots are compared together at matching
      desktop and mobile viewports.
- [ ] CI passes for the exact commit SHA.
- [ ] Staging reports the same exact SHA and smoke checks pass.
- [ ] Only then may the slice be described as deployed; never as the final app.
