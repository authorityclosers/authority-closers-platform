"use client";

import {
  DashboardBody,
  useDashboardTeam,
  useHomeOutline,
} from "./dashboard-body";
import { HomeOutline } from "./home-outline";

/**
 * The dashboard while its route loads: the page's own skeleton, line for line.
 * In an organisation that is Home's own outline (home-outline.tsx), for the
 * role this device saw last, a seller's until it has seen one.
 */
export function DashboardSkeleton() {
  const team = useDashboardTeam();
  const outline = useHomeOutline();
  return (
    <DashboardBody
      team={team}
      skeleton
      sales={outline ? <HomeOutline manager={outline === "manager"} /> : null}
      salesRole={outline}
    />
  );
}
