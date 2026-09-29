"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { PageSkeleton } from "../shell/page-skeleton";
import { useWorkspaceAccess } from "../workspace-access";

export default function DashboardLoading() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="dashboard"
    >
      <PageSkeleton variant="dashboard" />
    </AcquisitionShell>
  );
}
