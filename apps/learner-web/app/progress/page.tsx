import { ProgressRuntime } from "../components/progress-runtime";
import { LearnerShell } from "../components/site-shell";

export default function ProgressPage() {
  return (
    <LearnerShell current="progress">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container progress-page">
          <ProgressRuntime />
        </div>
      </main>
    </LearnerShell>
  );
}
