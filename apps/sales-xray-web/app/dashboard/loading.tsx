"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { DashboardSkeleton } from "./dashboard-skeleton";

export default function DashboardLoading() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="dashboard"
    >
      <DashboardSkeleton />
    </AcquisitionShell>
  );
}
