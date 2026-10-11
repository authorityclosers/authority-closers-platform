"use client";

import { AcquisitionShell } from "../../../acquisition-shell";
import { useWorkspaceAccess } from "../../../workspace-access";
import { PersonSkeleton } from "../person-skeleton";
import styles from "../person.module.css";

/** The profile's own outline in the frame, so nothing moves when it loads. */
export default function Loading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref="/"
      active="organisation"
      mobileFit={false}
      loading={!access}
    >
      <div className={styles.page}>
        <PersonSkeleton />
      </div>
    </AcquisitionShell>
  );
}
