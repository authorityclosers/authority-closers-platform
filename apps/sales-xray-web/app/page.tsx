import { AcquisitionStudio } from "./acquisition-studio";
import {
  requestedExistingCallId,
  type SalesXraySearchParams,
} from "./existing-call-entry";
import { StandaloneStudio } from "./standalone-studio";

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
    <StandaloneStudio openingExistingCall={requestedCallId != null}>
      <AcquisitionStudio
        requestedCallId={requestedCallId}
        deferRouteSelection={staticPreview}
      />
    </StandaloneStudio>
  );
}
