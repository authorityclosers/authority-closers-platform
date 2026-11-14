"use client";

/**
 * Results, /reports: every kind of report in one place (reports-hub.tsx).
 * Named Results so the app has one "Reports", the Reports tab's page
 * (Orchestrator, 14 Nov 2026: the palette listed two).
 */

import { AcquisitionShell } from "../acquisition-shell";
import { useSalesRole } from "../dashboard/dashboard-body";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../ui/kit";
import { RecordingLine } from "../capture-setup/recording-check";
import { useWorkspaceAccess } from "../workspace-access";
import { ReportsHub, useReportsData } from "./reports-hub";

export function ReportsSkeleton() {
  return (
    <AcquisitionShell
      authenticated={false}
      loading
      active="dashboard"
      pageName="Results"
    >
      <PageHeader title="Results" titleInBar />
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
        pageName="Results"
      >
        <SignedOutWelcome
          title="Sign in to see your reports"
          text="Call reports, coaching and your pipeline's numbers, in one place."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="dashboard" pageName="Results">
      <PageHeader title="Results" titleInBar />
      <RecordingLine
        key={`line:${access.context?.personId}:${access.context?.tenantId}`}
      />
      <Hub key={`${access.context?.personId}:${access.context?.tenantId}`} />
    </AcquisitionShell>
  );
}
