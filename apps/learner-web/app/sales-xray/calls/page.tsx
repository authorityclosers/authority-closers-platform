import { CallsLibrary } from "../../../../sales-xray-web/app/calls-library";
import { SalesXrayShell } from "../sales-xray-shell";

export default function SalesXrayCallsPage() {
  return (
    <SalesXrayShell current="calls">
      <CallsLibrary variant="embedded" studioHref="/sales-xray" />
    </SalesXrayShell>
  );
}
