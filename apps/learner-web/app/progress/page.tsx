import { ProgressRuntime } from "../components/progress-runtime";
import { LearnerShell } from "../components/site-shell";

export default function ProgressPage() {
  return (
    <LearnerShell current="progress">
      <main id="main-content" className="learner-main">
        <div className="page-container progress-page">
          <ProgressRuntime />
        </div>
      </main>
    </LearnerShell>
  );
}
