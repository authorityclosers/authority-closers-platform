import { notFound } from "next/navigation";

import { WorkCallsPreview } from "./preview";

/** Local visual review of Leads' work-call logging card with a fictional phone. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <WorkCallsPreview />;
}
