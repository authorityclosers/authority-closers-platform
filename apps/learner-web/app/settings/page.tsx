import { SettingsRuntime } from "../components/settings-runtime";
import { LearnerShell } from "../components/site-shell";

export default function SettingsPage() {
  return (
    <LearnerShell current="settings">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container settings-page">
          <SettingsRuntime />
        </div>
      </main>
    </LearnerShell>
  );
}
