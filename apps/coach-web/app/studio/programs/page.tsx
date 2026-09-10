import { StudioProgramList } from "@ac/operations-web/studio";
import { CoachShell } from "../../components/coach-shell";
export default function Courses() {
  return (
    <CoachShell>
      <div className="coach-page-heading">
        <p className="section-eyebrow">Your academy</p>
        <h1>A great course starts here.</h1>
        <p>
          Shape your lessons, review what learners will see, and publish when
          you’re ready.
        </p>
      </div>
      <StudioProgramList />
    </CoachShell>
  );
}
