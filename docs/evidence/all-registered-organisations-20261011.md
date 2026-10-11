# AUT-1694: Sales Xray serves all active registered organisations

Owner order: 11 October 2026, 15:40 IST, recorded in Strike E's inbox.
Source baseline: `59c2fc6c` (main, including the bulk/sandbox import and review labels).
The urgent change excludes the preserved username candidate; its full source and
proof remain at `10bdc475` and in the strike's durable deferred patch.

Workspace availability now comes from `organisations` joined to active `tenants`,
plus configured Personal, excluding operations. It is resolved in each request's
existing authentication transaction, so new organisations and suspension take
effect without restarting the API. The directory no longer uses the pinned
provider-policy tenant list as its availability flag. Profile, acquisition,
library/submission, Admin and legacy workspace reads use the same rule. Existing
session, verification, membership, ownership and private-source fences remain.

An explicit exact-tenant policy wins. Otherwise the runtime derives a policy from
the first sealed organisation template (AC in the existing approvals), or the
sealed Personal pattern when no organisation template exists. It retains source
and storage caps, expiry, finite configurations, stage profiles and provider gates;
the recording count is 2000. A canonical existing non-login processing identity is retained. New identities
use a stable UUID5 distinct per organisation and survive resealing. Derivation changes no approval JSON bytes,
digest, project budget or root storage cap. The default is requested only after
live registry and processing-lease admission; direct operator lookup stays exact.

The first admitted account upload reuses `GuestOwnership.provision` inside its
existing tenant-serialized transaction. It creates the same non-login person,
processing membership, empty minute ledger and append-only audit event as the
existing composition command. Replay creates nothing; revoked or conflicting
principals are refused. Acquisition minutes still belong to the actual account.
Organisations receive no automatic trial or minute grant.

The separately owned prospect route file is unchanged. Its synchronous scope port
is adapted in submission composition with request-local context, after live
selected-workspace admission, including its read-only authentication dependency.
The Admin call-review installer gains an optional live-scope callback while keeping
its existing tuple-based callers supported. There is no process-wide tenant cache.

Validation uses only fictional calls and a disposable loopback PostgreSQL schema.
The focused suite covers unchanged approval bytes, explicit-policy precedence,
distinct and stable principals, all four storage/count caps, live registration and
suspension, inactive membership and operations exclusion, Personal/organisation
source isolation, and create → invite → accept → concurrent first uploads.
A failed first upload rolls back the principal and its audit event. The original
combined run passed 83 unit/HTTP cases before a transient native-preflight rejection;
standalone measurement and the isolated full upload/read/isolation journey passed.
Final command results are recorded in Strike E's NOTES.md.

Additional provider-boundary proof covers all three default C2/C4/C5 stage
bindings and rejects a different processing person or tenant. A fictional C2
child dispatch succeeds once with the exact signed permission, then refuses a
borrowed other-organisation permission before another child call. The original published change passed 98 focused cases. The additional
existing-principal correction checks live registry/principal admission and
retains exact sealed principal precedence. A sealed principal cannot be borrowed
by another tenant. PostgreSQL proof includes concurrent first uploads with an
already provisioned principal and verifies that neither it nor its audit event
is replaced. Command-specific final results are recorded in Strike E NOTES.md.

A live startup compatibility repair retains the synchronous two-argument
`sales_xray_served_tenant_ids` composition snapshot for existing installers. All
E request paths supply the database and resolve live registry scope; the explicit
`sales_xray_active_tenant_ids(settings, database)` async equivalent is available.
Strike G owns converting Insights to request-time scope. The compatibility
snapshot is not proof of complete Insights availability. Before committing,
the source candidate is merged with a pinned dev/live tree in an ephemeral Git
object/source export, imported, and the real application is constructed. This
changes no checkout, branch, deployment, service or live database. The newest
DEV-FIRST order freezes staging/production and makes authenticated committed
dev/live acceptance the delivery target.

No live approval, staging/production data, host service, provider credential,
manual merge or deployment was changed. No UI file changed or screenshot build ran.
