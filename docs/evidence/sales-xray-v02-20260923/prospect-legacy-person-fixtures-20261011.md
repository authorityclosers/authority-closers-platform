# Populated Prospect upgrades (AUT-1677)

Strike E's username-account CI at `39668703` exposed two B-owned historical
fixture failures. The 0076/0077 population reused today's Person model, whose
new username columns are absent in those actual historical tables.

Population now uses a reflected old Person mapping in a scoped test context.
Only fixture seed, setup, processing principal and call-admission bindings use
that mapping. It declares the honest pre-username defaults: no username,
verification or temporary expiry, and no required password change. All model
bindings are restored before the real migration and current metadata comparison.
The 0077 test resolves the actual repository head instead of hardcoding 0080.
There is no production missing-column fallback or admission change.

The two focused real PostgreSQL populated-upgrade cases pass in 46.48 seconds;
identities, memberships, tags and audit IDs/hashes remain preserved and final
metadata drift is empty. Changed-file Ruff/format and diff checks pass. The
local Company prototype is included only in this disposable schema's head;
it is not published. The inspected E source pin confirms the four historical
defaults cover its admission fields; E must rerun its exact candidate CI after
adopting this fixture change. No live login/deployment verification is claimed.
