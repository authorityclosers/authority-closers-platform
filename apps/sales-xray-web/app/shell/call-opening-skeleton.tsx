"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { PageSkeleton } from "./page-skeleton";
import styles from "./page-skeleton.module.css";

/**
 * A saved call while its route or session loads. The studio shows the same
 * outline, in the same wrapper, while it opens the call ("opening").
 */
export function CallOpeningSkeletonContent() {
  return (
    <div
      className={`xray-app simple-app ${styles.frame}`}
      data-stage="opening"
      aria-busy="true"
    >
      <div className={`studio-main ${styles.frame}`}>
        <p className="visually-hidden" role="status" aria-live="polite">
          Opening your saved call
        </p>
        <PageSkeleton variant="report" />
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
      pageName="Report"
      mobileFit
    >
      <CallOpeningSkeletonContent />
    </AcquisitionShell>
  );
}
