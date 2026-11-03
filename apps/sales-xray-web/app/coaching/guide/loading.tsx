"use client";

import { AcquisitionShell } from "../../acquisition-shell";
import { PageHeader } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { GUIDE, GuideSkeleton } from "./guide-view";
import styles from "./guide.module.css";

/** The guide's own outline while it opens, not Coaching's. */
export default function Loading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      active="coaching"
    >
      <div className={styles.root}>
        <PageHeader
          title={GUIDE.title}
          back={{ href: "/coaching", label: GUIDE.back }}
        />
        <GuideSkeleton />
      </div>
    </AcquisitionShell>
  );
}
