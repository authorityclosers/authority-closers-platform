"use client";

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { useWorkspaceAccess } from "../../workspace-access";
import type { Filters } from "./insights-data";
import {
  InsightsSkeleton,
  InsightsView,
  type InsightsSeed,
} from "./insights-view";

/** The shell around Insights; a workspace switch reads the new organisation. */
export function InsightsPage({
  filters,
  initial,
  initialCalls,
}: {
  filters: Filters;
  initial: InsightsSeed;
  initialCalls: InsightsSeed;
}) {
  const access = useWorkspaceAccess();
  const tenantId = access?.context?.tenantId ?? null;
  // The server's reads belong to the workspace selected when the page loaded.
  const [first, setFirst] = useState<string | null>(null);
  if (first === null && tenantId) setFirst(tenantId);
  const seeded = tenantId !== null && (first === null || tenantId === first);
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      homeHref="/"
      active="insights"
      mobileFit={false}
    >
      {tenantId ? (
        <InsightsView
          key={tenantId}
          filters={filters}
          initial={seeded ? initial : null}
          initialCalls={seeded ? initialCalls : null}
        />
      ) : access?.authenticated === false ? (
        <InsightsView
          key="signed-out"
          filters={filters}
          initial={{ status: 401, body: null }}
        />
      ) : (
        <InsightsSkeleton />
      )}
    </AcquisitionShell>
  );
}
