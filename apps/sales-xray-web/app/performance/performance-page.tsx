"use client";

/** Performance, /performance, and My Growth, /growth (its Analytics; Dipak's
 *  tab bar, 31 Oct 2026): the same engine view under each title. */

import { AcquisitionShell } from "../acquisition-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./performance.module.css";
import { PerformanceLoading, PerformanceView } from "./performance-view";

/** The page's own shape while it opens: the heading, then the view's own
 *  loading card, so nothing moves when the page arrives (robot 2ac64000). */
export function PerformanceSkeleton({
  title = "Performance",
  section,
}: {
  title?: string;
  section?: string;
}) {
  return (
    <AcquisitionShell
      authenticated={false}
      loading
      active="dashboard"
      pageName={title}
    >
      <PageHeader title={title} titleInBar />
      {section ? <h2 className={styles.section}>{section}</h2> : null}
      <PerformanceLoading withPeriod />
    </AcquisitionShell>
  );
}

export function PerformanceRoute({
  title = "Performance",
  section,
  visual = false,
}: {
  title?: string;
  /** Growth's tiles and day rhythm instead of the tables. */
  visual?: boolean;
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
        visual={visual}
      />
    </AcquisitionShell>
  );
}
