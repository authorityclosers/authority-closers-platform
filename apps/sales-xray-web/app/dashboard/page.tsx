import { serverDashboard } from "./dashboard-server";
import { DashboardView } from "./dashboard-view";

/**
 * Dashboard: where this server can read the API (dev), the page's data is
 * read here, with the session, and the page arrives whole (owner, 11 Oct:
 * "server-side data like Pulse"); elsewhere the browser reads it.
 */
export default async function DashboardPage() {
  return <DashboardView initial={await serverDashboard()} />;
}
