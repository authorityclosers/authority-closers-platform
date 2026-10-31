"use client";

/** Performance, /performance, and My Growth, /growth (its Analytics; Dipak's
 *  tab bar, 31 Oct 2026): the same engine view under each title. */

import { AcquisitionShell } from "../acquisition-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./performance.module.css";
import { PerformanceView } from "./performance-view";

export function PerformanceSkeleton({
  title = "Performance",
}: {
  title?: string;
}) {
  return (
    <AcquisitionShell
      authenticated={false}
      loading
      active="dashboard"
      pageName={title}
    >
      <PageHeader title={title} titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

export function PerformanceRoute({
  title = "Performance",
  section,
}: {
  title?: string;
  /** A heading over the view: "Analytics" on My Growth. */
  section?: string;
}) {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <PerformanceSkeleton title={title} />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="dashboard"
        pageName={title}
      >
        <SignedOutWelcome
          title="Sign in to see performance"
          text="Calls, talk time and breaks, with Inbound and Cold leads apart."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="dashboard" pageName={title}>
      <PageHeader title={title} titleInBar />
      {section ? <h2 className={styles.section}>{section}</h2> : null}
      <PerformanceView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
      />
    </AcquisitionShell>
  );
}
