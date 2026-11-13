/**
 * Back to the page that opened a lead (Redmi QA R2, 10 Nov 2026: a call opened
 * from Calls, and the lead's Back landed on Leads). That page handed the lead
 * over and moved to Leads, so the step before Leads is that page. Once the
 * lead's own step has gone (the arrow pops it; the phone's Back already has),
 * and Leads shows no lead, one more step back. `onStay`: told when it doesn't
 * step (the seller is somewhere else by then).
 */
export function backToOpener(
  leadsPath = "/leads",
  // Long enough for a slow phone's own step back to land first.
  wait = 1_500,
  onStay?: () => void,
) {
  let done = false;
  const onLeads = () =>
    window.location.pathname === leadsPath &&
    !new URLSearchParams(window.location.search).has("lead");
  const finish = () => {
    if (done) return;
    done = true;
    window.removeEventListener("popstate", popped);
    window.clearTimeout(timer);
    if (onLeads()) window.history.back();
    else onStay?.();
  };
  // Back from the lead by the arrow: its step goes, then this.
  const popped = () => window.setTimeout(finish, 0);
  window.addEventListener("popstate", popped);
  const timer = window.setTimeout(finish, wait);
  // Back by the phone: its step has already gone.
  window.setTimeout(() => {
    if (onLeads()) finish();
  }, 0);
}
