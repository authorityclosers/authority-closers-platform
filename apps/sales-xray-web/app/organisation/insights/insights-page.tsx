"use client";

import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { useWorkspaceAccess } from "../../workspace-access";
import { filtersFrom, type Filters, type View } from "./insights-data";
import {
  InsightsSkeleton,
  InsightsView,
  type InsightsSeed,
} from "./insights-view";

function searchParamsOf(search: string): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(search));
}

/** The shell around Insights; a workspace switch reads the new organisation. */
export function InsightsPage({
  filters,
  view,
  initial,
  initialCalls,
}: {
  filters: Filters;
  view: View;
  initial: InsightsSeed;
  initialCalls: InsightsSeed;
}) {
  const access = useWorkspaceAccess();
  const tenantId = access?.context?.tenantId ?? null;
  // The server's reads belong to the workspace selected when the page loaded,
  // and only to the first view of it: after a switch every view reads fresh,
  // keeps the address's period and outcome, and drops person and team (they
  // belong to the other organisation).
  const [first, setFirst] = useState<string | null>(null);
  const [switched, setSwitched] = useState(false);
  if (first === null && tenantId) setFirst(tenantId);
  if (first !== null && tenantId !== null && tenantId !== first && !switched)
    setSwitched(true);
  const seeded =
    !switched && tenantId !== null && (first === null || tenantId === first);
  const current = switched
    ? {
        ...filtersFrom(searchParamsOf(window.location.search)),
        person: null,
        team: null,
      }
    : filters;
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
          filters={current}
          view={view}
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
