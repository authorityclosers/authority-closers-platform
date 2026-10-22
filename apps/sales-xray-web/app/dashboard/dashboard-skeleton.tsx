"use client";

import {
  DashboardBody,
  useDashboardTeam,
  useSalesRole,
} from "./dashboard-body";
import { SalesHomeSkeleton } from "./sales-home-skeleton";

/**
 * The dashboard while its route loads: the page's own skeleton, line for line.
 * In an organisation that is Home's sales outline (owner or seller), as loaded.
 */
export function DashboardSkeleton() {
  const team = useDashboardTeam();
  const salesRole = useSalesRole();
  return (
    <DashboardBody
      team={team}
      skeleton
      sales={
        salesRole ? (
          <SalesHomeSkeleton manager={salesRole === "manager"} />
        ) : null
      }
      salesRole={salesRole}
    />
  );
}
