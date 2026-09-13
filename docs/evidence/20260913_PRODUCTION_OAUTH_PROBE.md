# Production OAuth deployment probe correction

`Assert-GoogleOAuthStart` always requested the staging learner hostname and
checked for its staging callback, even during a production deployment. A passing
production controller run therefore did not establish the production Google
start boundary.

The probe now uses the controller's selected `$learnerHost` for both the request
and expected callback. Existing provider-origin/path, host-cookie, signed-value,
one-time state and no-store checks remain in place. No OAuth configuration or
running deployment was changed by this source patch.

All 19 controller tests passed in 8.64 seconds. Four executable PowerShell cases
exercise staging and production, require a request to the selected environment,
accept its matching callback and reject the other environment's callback.
These fixtures make no network calls and use synthetic cookie values.

Receipt: `D:/AC-authority-closers-release-audit/v02-oauth-controller-01.xml`.
The deployment owner was asked to verify the actual production OAuth endpoint
separately after the already-running 69 deployment; this local test does not
claim that live verification happened.
