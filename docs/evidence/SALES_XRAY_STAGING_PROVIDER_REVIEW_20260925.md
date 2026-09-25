# Staging owner comparison controls

The existing acquisition C5 comparison endpoints had no browser control for the
signed-in owner to review and accept their exact quote. The staging-only
`/provider-review?call=<submission UUID>` route now uses the existing same-origin
client to read the saved call, confirm completed transcription and facts, request
one quote, and display the provider, model, recording binding, input fingerprint,
expiry, privacy notice and approved limits before explicit acceptance.

The server retains authority over account ownership, source identity, approvals,
entitlements and provider execution. The page does not expose this action in the
normal upload flow, change provider defaults, or include a particular customer's
identifiers. Other hosts and ambiguous call selectors return 404. The quote does
not disclose a numeric output-token limit; the UI says that the server-held
approval enforces it rather than inventing a value.

Quote and acceptance each use a separate stable idempotency key. Double clicks
cannot dispatch a second acceptance. An uncertain result stops further actions
and keeps the reference for investigation. This page never automatically retries
a provider request.

Validation: seven focused tests cover staging host and selector restrictions,
malformed/mismatched/expired/over-cap/incorrect-model quotes, saved-source
preconditions, explicit acceptance, duplicate clicks and uncertain outcomes.
Frontend type checking and lint passed locally. The exact committed candidate
must also pass release CI and deployed owner verification before claiming that a
comparison ran. These checks do not establish provider quality or cost.

The initial CI candidate exposed a static-export incompatibility: reading request
headers while building the offline preview caused its build to fail. The route
now returns 404 in static-preview mode before touching request headers. The
regression test asserts that neither headers nor the acquisition client are read.
