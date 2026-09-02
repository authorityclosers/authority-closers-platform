import { SettingsRuntime } from "../components/settings-runtime";
import { SettingsSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type SettingsPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function SettingsPage({
  searchParams,
}: SettingsPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="settings">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container settings-page">
          {state === "LOADING" ? (
            <SettingsSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.settings}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <SettingsRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
