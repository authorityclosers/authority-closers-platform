import { notFound } from "next/navigation";

import { LeadDeletePreview } from "./lead-delete-preview";

/** Local visual review of deleting leads with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LeadDeletePreview />;
}
