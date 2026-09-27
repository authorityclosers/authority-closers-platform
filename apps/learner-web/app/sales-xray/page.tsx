import { AcquisitionStudio } from "../../../sales-xray-web/app/acquisition-studio";
import {
  requestedExistingCallId,
  type SalesXraySearchParams,
} from "../../../sales-xray-web/app/existing-call-entry";
import { SalesXrayShell } from "./sales-xray-shell";

export default async function SalesXrayPage({
  searchParams,
}: {
  searchParams: Promise<SalesXraySearchParams>;
}) {
  const requestedCallId = requestedExistingCallId(await searchParams);
  return (
    <SalesXrayShell
      current="analyse"
      openingExistingCall={requestedCallId !== null}
    >
      <AcquisitionStudio
        homeHref="/home"
        variant="embedded"
        requestedCallId={requestedCallId}
      />
    </SalesXrayShell>
  );
}
