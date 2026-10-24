"use client";

import { AcquisitionShell } from "../../acquisition-shell";
import { useWorkspaceAccess } from "../../workspace-access";
import { InsightsSkeleton } from "./insights-skeleton";

export default function InsightsLoading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      homeHref="/"
      active="insights"
      mobileFit={false}
    >
      <InsightsSkeleton />
    </AcquisitionShell>
  );
}
