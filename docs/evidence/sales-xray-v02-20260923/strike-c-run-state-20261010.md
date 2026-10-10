# AUT-1676: honest status and safe Try again

The existing small ProcessingStatusCopy consumes the server's canonical queued,
working, retrying, failed and done states. Superseded failed stage rows cannot
turn a confirmed successor into a paused status. Failed reads show released
minutes only when the journal confirms that outcome. Owner retry availability
is server-supplied, never inferred from analytics or provider payment status.

Try again coalesces double clicks and retains the source command key in session
storage across ambiguous responses. The server prepares the fresh bounded plan;
the component displays its allowance/provider/privacy terms before explicit
acceptance. Acceptance must return the exact displayed source, plan id and
fingerprint. Confirmed local retries need no external-provider consent. A 20s
network budget returns control to the user; errors go to existing corner cards.
The new button uses only existing --lx theme/teal/font tokens. The requested
app/ui/sx-tokens.css does not exist in this source; app/lightbox/tokens.css is
the existing layout-imported token source. No new raw colour values were added.

Validation: 77 focused Vitest checks; Sales Xray typecheck; changed-file ESLint
and Prettier. An isolated local Vite/Playwright harness in
/home/acdev/strikes/1676/status-browser imports the real status, call-processing
panel, existing styles/fonts and fictional plan. It passes all 20 combinations
of five states, 390/1440px and light/dark themes; expanded retry terms also fit.
Screenshots are in /home/acdev/strikes/1676/shots/status-* and retry-*. They are
explicit fictional component evidence, not authenticated deployed evidence.
Chromium used the already installed Playwright library directory; no host
package installation or service change was performed. All browser runs used
ac-heavy.

Remaining page integration belongs to Strike A: AcquisitionStudio currently
mounts the processing/status panel only for an absent plan or an accepted plan.
An expired unaccepted quote uses its separate consent panel and does not mount
this component. Render the status component for progress.run_state === "failed"
there, suppressing the stale unaccepted-plan consent panel. This strike leaves
the owned page/layout file untouched. The backend already expires/releases that
quote and exposes a safe owner retry; accepted-plan and pre-plan failures reach
the status component through the existing caller.

No merge, deployment, production/staging write or new paid credential was used.
