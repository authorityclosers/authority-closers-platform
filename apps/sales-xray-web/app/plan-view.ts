import type { Progress } from "./acquisition-client";

/**
 * Which part of the call page a saved plan shows: the "Ready to continue"
 * consent, or the progress panel. An unaccepted quote that expired has
 * failed and released its minutes, so it shows the panel's Failed / Try
 * again instead of asking for consent again (Strike C, AUT-1676).
 */
export function planView(
  plan: { accepted: boolean } | null,
  progress: Pick<Progress, "run_state"> | null,
): { consent: boolean; showProgress: boolean } {
  const failed = progress?.run_state === "failed";
  return {
    consent: plan !== null && !plan.accepted && !failed,
    showProgress: !plan || plan.accepted || failed,
  };
}
