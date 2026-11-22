"use client";

/** /outreach (v1.95, owner 22 Nov 2026): "what the owner sent", in the app frame. */

import { AcquisitionShell } from "../acquisition-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader, Skeleton } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { OutreachView } from "./outreach-view";
import styles from "./outreach.module.css";

const TITLE = "Outreach";

/** The page's own shape while it opens, so nothing moves when it arrives. */
export function OutreachSkeleton() {
  return (
    <AcquisitionShell
      authenticated={false}
      loading
      active="leads"
      pageName={TITLE}
    >
      {/* The laptop's top bar names the page; the heading is for phones. */}
      <div className={styles.pageTitle}>
        <PageHeader title={TITLE} titleInBar />
      </div>
      <div
        className={styles.page}
        aria-busy="true"
        aria-label="Loading outreach"
      >
        <Skeleton height={140} />
        <Skeleton height={48} />
        <Skeleton height={320} />
      </div>
    </AcquisitionShell>
  );
}

export function OutreachRoute() {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <OutreachSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
        pageName={TITLE}
      >
        <SignedOutWelcome
          title="Sign in to see outreach"
          text="Every message sent to your leads, and who sent it."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="leads" pageName={TITLE}>
      {/* The laptop's top bar names the page; the heading is for phones. */}
      <div className={styles.pageTitle}>
        <PageHeader title={TITLE} titleInBar />
      </div>
      <OutreachView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
      />
    </AcquisitionShell>
  );
}
