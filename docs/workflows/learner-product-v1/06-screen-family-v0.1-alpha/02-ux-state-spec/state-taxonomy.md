# State taxonomy and transition rules

## Three layers

Every matrix row identifies all three layers even when the UI renders them in
one card:

1. **Presentation layer** — `ready`, `loading`, `empty`, `validation_error`,
   `retryable_error`, `terminal_error`, `offline_or_stale`,
   `unauthorized_or_expired`, `permission_denied`, `locked`, `partial`,
   `processing`, or `success`.
2. **Canonical domain layer** — the server-owned identity, profile, catalog,
   enrollment, pinned content version, activity evidence/draft, progress,
   plan projection, notification/read state, session, or certificate state.
3. **Recovery/ownership layer** — learner self-recovery, scoped support, domain
   operator, technical operator, or governance decision. A routine case must
   close below founder level when policy is already defined.

## Allowed state semantics

| State | User meaning | Safe actions | Prohibited implication |
| --- | --- | --- | --- |
| `ready` | authoritative data and allowed actions are available | perform the primary action, navigate, edit permitted fields | does not imply completion or mastery |
| `loading` | the request is in flight | wait, use safe navigation | not zero, empty, or success |
| `empty` | the authorized result set has no items | browse, start configured path, create safe draft, or continue | not “no progress” unless canonical data says so |
| `validation_error` | supplied input needs correction | fix the associated field and retry | no silent discard |
| `retryable_error` | transient request/provider/network failure | retry same safe intent, preserve input, seek help | no duplicate mutation or fallback authority |
| `terminal_error` | action cannot complete under current policy/token/resource | return, use named recovery, contact support | no internal provider/database detail |
| `offline_or_stale` | network unavailable or cached display is old | view safe cache, edit supported local draft, reconnect | no protected mutation, entitlement, official score, or canonical completion claim |
| `unauthorized_or_expired` | session is absent/expired | reauthenticate and return to intended route | no loss of supported draft or account enumeration |
| `permission_denied` | authenticated actor cannot access action/resource | return to safe surface or request support | do not reveal protected payload |
| `locked` | resource is known but prerequisite/policy blocks it | open exact prerequisite or help | not an API error and not a hint of hidden content |
| `partial` | primary data is available but a secondary panel is missing/stale | use available core, retry secondary panel | missing panel is not zero |
| `processing` | durable asynchronous work is pending | wait, leave and return, refresh boundedly | do not claim final success or repeat submission |
| `success` | server-confirmed result is available | continue, review, or undo only where policy permits | no auto-advance that hides confirmation |

## Cross-cutting transitions

- `loading → ready|empty|partial|retryable_error|terminal_error` only after a
  response is classified; never render a false empty state during a request.
- `dirty → saving → saved|retryable_error|conflict|offline_or_stale` preserves
  the safe input until the learner confirms the result or intentionally leaves.
- `processing → success|retryable_error|terminal_error` is a named domain
  transition; refreshing does not create a second command.
- `ready → unauthorized_or_expired` retains a return intent and any supported
  local draft; reauthentication returns to the exact route/step.
- `ready → offline_or_stale` is allowed for safe reads only; money, access,
  official score, deletion, certificate, and official evidence mutations are
  blocked until online and authorized.
- `ready → locked|permission_denied` must be a server-authorized decision, not
  a client heuristic based on a hidden or missing card.
- `success → ready` is used for “saved” or “read” outcomes; canonical history
  is superseded/append-safe, never silently overwritten.

## Analytics boundary

Analytics events such as `screen_viewed`, `plan_horizon_opened`,
`activity_started`, `notification_opened`, and `theme_changed` are useful for
measurement only. They are not a substitute for canonical progress,
enrollment, access, certificate, notification, or evidence state.
