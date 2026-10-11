# AUT-1801: committed stage handoffs

The hosted service now uses two bounded consumers: one for local inspection and
retention, and one for accepted plan advancement and provider work. Another
recording's C1 no longer occupies the provider consumer. Each consumer stays
serial; this step does not increase simultaneous native or provider executions.

C1 and validated C2/C4/C5 completions make matching active plans immediately due
in the same publication transaction. When C1 returns after commit, an in-process
event wakes the coordinator. The provider consumer immediately checks durable
work again after each completed stage. Original source/generation binding,
consent, budget, quotes, task deduplication and provider dispatch fences remain
the admission authority. No held or uncertain provider job is replayed.

Shutdown stops new admissions and drains both accepted calls. An unexpected
consumer error stops its sibling and drains the accepted work before engine
disposal. Recovery admission retains its bounded backoff. Tests exercise a
blocked local worker while provider work proceeds, an idle handoff with a
five-second fallback completing within one second, sibling failure, cancellation
and a real PostgreSQL C2-to-C6 pipeline with next-check clocks set one minute in
the future before each provider completion.

Validation: 29 focused runner/service tests passed; the real PostgreSQL handoff
case passed. Ruff and strict mypy passed on the five changed runtime modules.
No hosted database, provider or deployment was used for those checks.

## Live measurement

Owner-supplied staging baseline, 11 October, 16:00 IST:

| Call prefix | Audio s | Upload-to-report s | Before C2 s | C2 s | C4 s | C5 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 6bbfdec8 | 1254 | 105 | 4 | unknown | 34 | 31 |
| ab9f120c | 674 | 154 | 49 | 27 | 16 | 43 |
| cbb050b1 | 1514 | 197 | 39 | 41 | 51 | 33 |
| da2d85c5 | 504 | 121 | 54 | 20 | 6 | 23 |
| e94ef127 | 25 | C1 failed | unknown | unknown | unknown | unknown |

These are the supplied baseline observations, not an independently re-read
snapshot. Deployment and a new source-bound timing export are needed for the
after table. The 60-second p50 / 90-second p95 target is not yet verified.
Local concurrency tests establish scheduling behavior, not provider latency.

Remaining work: bounded independent C4 execution, live timing verification and
the exact short-file failure diagnosis. Companion changes add partial retained
transcript/fact projection and truthful C2 operator reconciliation. C3 requires a complete validated C2
checkpoint; C5 currently authorizes one whole-call response, and C6 validates that
whole response. Streaming or splitting those paid inputs needs an explicit
versioned prompt/profile and its existing Root activation path.

## Cross-process handoff

The hosted worker listens on one PostgreSQL connection for
`ac_conversation_work_v1`. New local jobs, accepted processing plans and
completed stages publish an empty notification in their existing transaction.
Delivery occurs after commit, and wakes both consumers without sharing their
clearable events. The listener performs an initial rescan after connection and
reconnection. Durable periodic scans remain a recovery fallback if a hint is
lost; notifications never advance state or authorize a provider send.

The listener closes on shutdown, uses no new dependency or migration, and logs
only a fixed unavailable code on connection failure. Database tests distinguish
an uncommitted notification, a rolled-back notification and a committed one.

The original root storage fence was another serialization point. Processing
now takes a shared fence on Linux; deletion and retained-result recovery keep
the default exclusive fence. All fences still precede database locks, and
immutable run/object keys and durable job claims retain write ownership. The
actual-fence test holds two processing readers at once and proves deletion
waits for both. Windows retains conservative exclusive admission.

Follow-up validation: 20 runner/service/PostgreSQL tests passed, including
commit-versus-rollback notification delivery; the actual shared/exclusive fence
test passed, and both database deletion/revocation race cases passed. Strict
mypy passed for the listener and the worker modules; its URL input now accepts
the existing SQLAlchemy URL object.
