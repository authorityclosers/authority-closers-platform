import DashboardClient from "../../dashboard/route-view";
import { DashboardWidgets } from "../../dashboard/dashboard-widgets";
import { DashboardRetry } from "../../dashboard/dashboard-retry";
import { readSessionSeed, readDashboardSnapshot } from "../../session-server";
import { LightboxShell } from "../../shell/lightbox-shell";
import { WorkspaceNoAccess } from "../../workspace-no-access";
export default async function DashboardPage() {
  const seed = await readSessionSeed();
  const snapshot = await readDashboardSnapshot(seed);
  if (!snapshot) return <DashboardClient />;
  const states = [
    snapshot.summary,
    snapshot.activity,
    snapshot.allowance,
    snapshot.recent,
  ];
  const forbidden = states.some(
    (state) => state.status === "error" && state.forbidden,
  );
  const failed = states.some(
    (state) => state.status === "error" && !state.forbidden,
  );
  return (
    <LightboxShell
      active="dashboard"
      authenticated
      homeHref="/dashboard"
      allowance={
        snapshot.allowance.status === "ready" ? snapshot.allowance.value : null
      }
    >
      {forbidden ? (
        <WorkspaceNoAccess workspace={null} />
      ) : (
        <>
          <DashboardWidgets {...snapshot} />
          {failed ? <DashboardRetry /> : null}
        </>
      )}
    </LightboxShell>
  );
}
