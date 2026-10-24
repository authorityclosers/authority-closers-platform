import { notFound } from "next/navigation";

import { LeadPipelinePreview } from "./lead-pipeline-preview";

/** Local visual review of the Lead OS pipeline with fictional leads. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LeadPipelinePreview />;
}
