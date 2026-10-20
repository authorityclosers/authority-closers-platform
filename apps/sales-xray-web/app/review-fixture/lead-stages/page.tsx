import { notFound } from "next/navigation";

import { LeadStagesPreview } from "./lead-stages-preview";

/** Local visual review of Leads → Lead stages with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LeadStagesPreview />;
}
