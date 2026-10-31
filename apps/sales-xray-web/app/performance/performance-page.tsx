"use client";

/** Performance, /performance: Home's Performance button (performance-view.tsx). */

import { AcquisitionShell } from "../acquisition-shell";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { PerformanceView } from "./performance-view";

export function PerformanceSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="dashboard">
      <PageHeader title="Performance" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

export function PerformanceRoute() {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <PerformanceSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="dashboard"
      >
        <SignedOutWelcome
          title="Sign in to see performance"
          text="Calls, talk time and breaks, with Inbound and Cold leads apart."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="dashboard">
      <PageHeader title="Performance" titleInBar />
      <PerformanceView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
      />
    </AcquisitionShell>
  );
}
