import { notFound } from "next/navigation";

import { BugReportPreview } from "./bug-report-preview";

/** Local visual review of Report a problem with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <BugReportPreview />;
}
