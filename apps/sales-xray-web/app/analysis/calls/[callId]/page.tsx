import { notFound } from "next/navigation";

import { UUID } from "../../../acquisition-client";
import { AcquisitionStudio } from "../../../acquisition-studio";

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
  return <AcquisitionStudio requestedCallId={callId} />;
}
