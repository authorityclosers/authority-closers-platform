import { notFound } from "next/navigation";

import { UUID } from "../../../acquisition-client";
import { AcquisitionStudio } from "../../../acquisition-studio";
import { ReportSettingsWarmUp } from "../../../report-settings-warm";

// The static preview build needs one concrete path; real calls render on
// demand and any other id is not found.
export function generateStaticParams() {
  return [{ callId: "preview" }];
}

export default async function CallAnalysisPage({
  params,
}: {
  params: Promise<{ callId: string }>;
}) {
  const { callId } = await params;
  if (!UUID.test(callId)) notFound();
  return (
    <>
      {/* The Report's settings version is read beside the call's reads. */}
      <ReportSettingsWarmUp />
      <AcquisitionStudio requestedCallId={callId} />
    </>
  );
}
