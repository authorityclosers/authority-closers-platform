import { ShieldAlert } from "lucide-react";

import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";

export function DevStagingBridgeNotice() {
  if (!isStagingAuthenticatedBridge(process.env, process.env.NODE_ENV)) {
    return null;
  }

  return (
    <aside
      className="dev-staging-bridge-notice"
      aria-label="Development staging data notice"
      role="status"
    >
      <div className="dev-staging-bridge-notice__icon">
        <ShieldAlert size={18} aria-hidden="true" />
      </div>
      <div>
        <strong>Development bridge · staging data</strong>
        <p>
          Signed-in reads and mutations use the real staging learner account.
          This local session expires when the dev server restarts or after 8
          hours.
        </p>
      </div>
    </aside>
  );
}
