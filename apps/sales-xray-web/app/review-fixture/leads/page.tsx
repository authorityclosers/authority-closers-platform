import { notFound } from "next/navigation";

import { LeadsPreview } from "./leads-preview";

/** Local visual review of the Leads page with fictional leads. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LeadsPreview />;
}
