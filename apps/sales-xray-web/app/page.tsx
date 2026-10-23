import { AcquisitionStudio } from "./acquisition-studio";
import { FirstRunGate } from "./welcome/first-run-gate";
import {
  requestedExistingCallId,
  type SalesXraySearchParams,
} from "./existing-call-entry";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<SalesXraySearchParams>;
}) {
  const staticPreview = process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1";
  const requestedCallId = staticPreview
    ? undefined
    : requestedExistingCallId(await searchParams);
  return (
    <>
      {/* A brand-new account goes to first-run setup once (welcome/). */}
      {requestedCallId ? null : <FirstRunGate />}
      <AcquisitionStudio
        requestedCallId={requestedCallId}
        deferRouteSelection={staticPreview}
      />
    </>
  );
}
