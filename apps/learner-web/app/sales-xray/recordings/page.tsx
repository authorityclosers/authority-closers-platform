import { CallStudio } from "../../../../sales-xray-web/app/call-studio";
import { SalesXrayShell } from "../sales-xray-shell";

export default function EarlierRecordingsPage() {
  return (
    <SalesXrayShell current="recordings">
      <CallStudio variant="embedded" homeHref="/home" />
    </SalesXrayShell>
  );
}
