import { StudioProgramList } from "@ac/operations-web/studio";
export default function Courses() {
  return (
    <>
      <div className="coach-page-heading">
        <p className="section-eyebrow">Your academy</p>
        <h1>A great course starts here.</h1>
        <p>
          Shape your lessons, review what learners will see, and publish when
          you’re ready.
        </p>
      </div>
      <StudioProgramList />
    </>
  );
}
