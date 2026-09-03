import { ShieldAlert } from "lucide-react";

import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export function DevStagingBridgeNotice() {
  if (!isStagingAuthenticatedBridge(process.env, process.env.NODE_ENV)) {
    return null;
  }

  return (
    <details
      className="dev-staging-bridge-notice"
      aria-label="Development staging data notice"
    >
      <summary>
        <span className="dev-staging-bridge-notice__icon">
          <ShieldAlert size={15} aria-hidden="true" />
        </span>
        <strong>Dev · staging data</strong>
      </summary>
      <p>
        Signed-in reads and mutations use the real staging learner account. This
        local session expires when the dev server restarts or after 8 hours.
      </p>
    </details>
  );
}
