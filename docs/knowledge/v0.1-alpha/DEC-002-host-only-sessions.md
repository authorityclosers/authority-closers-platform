---
id: DEC-002
type: decision
title: Host-Only Same-Origin Browser Sessions
status: accepted
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/decision/security
---

# Host-only same-origin browser sessions

Learner and admin sessions are separate opaque Secure, HttpOnly, SameSite=Lax, host-only cookies. Browser API traffic stays on same-origin `/v1`; unsafe cookie-authenticated methods require an allowlisted Origin. Google uses server-side authorization code + PKCE with state, nonce, one-time transaction, surface binding, and exact callbacks.

The WordPress apex and unrelated subdomains are outside the session-cookie trust boundary. Browser-readable bearer tokens and parent-domain cookies are rejected.

- repository ADR: [ADR-027](../../adr/0027-use-host-only-same-origin-browser-sessions.md).
- controls: [[RT-001-public-auth]], [[API-001-identity-onboarding]], [[API-004-session-settings]].
- implements: [[IMP-001-learner-web]] and [[IMP-002-platform-api-domain]].
- evidenced-by: [[EVD-001-staging-27fafae]] and [[EVD-002-auth-81635d1]] only for the named releases.
