import { CallStudio } from "../../../sales-xray-web/app/call-studio";
import { LearnerShell } from "../components/site-shell";

export default function SalesXrayPage() {
  return (
    <LearnerShell current="sales-xray">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <CallStudio homeHref="/home" />
      </main>
    </LearnerShell>
  );
}
