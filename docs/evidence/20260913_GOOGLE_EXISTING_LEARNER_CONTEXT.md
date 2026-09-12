# Existing learner context after Google authentication

Production and staging run the accepted UI release `f0a80f2`. During the staging
Chrome sign-in check, Google's linked admin identity authenticated successfully
but `/home` reported that learner membership was unavailable. A read-only
database check found both an active operations owner membership and an active
public learner membership. Neither membership was missing.

The generic identity service deliberately leaves sessions unscoped when more
than one tenant is available. Password login already selects the configured
public learner membership; the learner Google authentication callback now does
the same. It only selects an existing active membership with the exact learner
role for the authenticated person and configured public tenant. Normal tenant
selection revalidates lifecycle state. No membership, consent or provider link
is created by this fix, and Admin/Coach authentication selection is unchanged.

Validation: all 81 HTTP authentication route tests passed, including six cases
for present/absent existing membership across learner, Admin and Coach surfaces.
These exercise signed OAuth transactions, callbacks and issued cookies. Ruff
and diff checks passed. The successful pre-fix Chrome login and membership
diagnosis establish the original failure; post-deployment Chrome acceptance is
still required before claiming this fix is live.
