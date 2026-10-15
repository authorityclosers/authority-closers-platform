"use client";

import { DashboardBody, useDashboardTeam } from "./dashboard-body";

/** The dashboard while its route loads: the page's own skeleton, line for line. */
export function DashboardSkeleton() {
  const team = useDashboardTeam();
  return <DashboardBody team={team} skeleton />;
}
