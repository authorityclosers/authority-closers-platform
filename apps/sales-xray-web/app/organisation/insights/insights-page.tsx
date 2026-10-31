"use client";

import { Lock } from "lucide-react";
import { useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { Empty } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { useCanHere } from "../../workspace-role";
import { OrgHubFrame } from "../org-hub";
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
  // Insights are the team's figures, for those who see the team (roles.ts
  // "team.view"): anyone else reads a calm line, and nothing is read.
  const canHere = useCanHere();
  const seesTeam = canHere("team.view") !== false;
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
      <OrgHubFrame current="insights">
        {!seesTeam ? (
          <Empty
            icon={Lock}
            title="Only owners and managers can see Insights"
            text="Your own calls and coaching stay in Calls and Coaching."
            action={{ label: "Back to Organisation", href: "/organisation" }}
          />
        ) : tenantId ? (
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
      </OrgHubFrame>
    </AcquisitionShell>
  );
}
