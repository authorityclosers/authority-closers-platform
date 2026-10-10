"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { CallsSkeleton } from "../calls-library";
import { useWorkspaceAccess } from "../workspace-access";

export default function CallsLoading() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="calls"
      mobileFit={false}
    >
      <CallsSkeleton />
    </AcquisitionShell>
  );
}
