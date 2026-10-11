"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { PageSkeleton } from "./page-skeleton";

/**
 * A saved call while its route or session loads. The studio shows the same
 * outline, in the same wrapper, while it opens the call ("opening").
 */
export function CallOpeningSkeletonContent() {
  return (
    <div className="xray-app simple-app" data-stage="opening">
      <div className="studio-main">
        <p className="visually-hidden" role="status" aria-live="polite">
          Opening your saved call
        </p>
        <PageSkeleton variant="call" />
      </div>
    </div>
  );
}

export function CallOpeningSkeleton() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      active="calls"
      mobileFit
    >
      <CallOpeningSkeletonContent />
    </AcquisitionShell>
  );
}
