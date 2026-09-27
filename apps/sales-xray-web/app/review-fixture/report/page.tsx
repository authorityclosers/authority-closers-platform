import { notFound } from "next/navigation";

import { SyntheticReportPreview } from "./synthetic-report-preview";

/** Local visual review only. The route is never available in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SyntheticReportPreview />;
}
