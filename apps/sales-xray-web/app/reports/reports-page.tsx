"use client";

/** Reports, /reports: every kind of report in one place (reports-hub.tsx). */

import { AcquisitionShell } from "../acquisition-shell";
import { useSalesRole } from "../dashboard/dashboard-body";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { ReportsHub, useReportsData } from "./reports-hub";

export function ReportsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="dashboard">
      <PageHeader title="Reports" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

function Hub() {
  const manager = useSalesRole() === "manager";
  const data = useReportsData(manager);
  return <ReportsHub manager={manager} data={data} />;
}

export function ReportsRoute() {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <ReportsSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="dashboard"
      >
        <SignedOutWelcome
          title="Sign in to see your reports"
          text="Call reports, coaching and your pipeline's numbers, in one place."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="dashboard">
      <PageHeader title="Reports" titleInBar />
      <Hub key={`${access.context?.personId}:${access.context?.tenantId}`} />
    </AcquisitionShell>
  );
}
