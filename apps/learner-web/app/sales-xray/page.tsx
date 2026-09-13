import { CallStudio } from "../../../sales-xray-web/app/call-studio";
import { LearnerShell } from "../components/site-shell";

export default function SalesXrayPage() {
  return (
    <LearnerShell current="sales-xray">
      <CallStudio homeHref="/home" />
    </LearnerShell>
  );
}
