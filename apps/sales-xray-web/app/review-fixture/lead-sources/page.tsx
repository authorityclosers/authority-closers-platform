import { notFound } from "next/navigation";

import { LeadSourcesPreview } from "./lead-sources-preview";

/** Local visual review of Leads setup → Sources with fictional Pages. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LeadSourcesPreview />;
}
