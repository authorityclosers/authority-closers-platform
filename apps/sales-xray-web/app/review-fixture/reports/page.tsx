import { notFound } from "next/navigation";

import { ReportsPreview } from "./reports-preview";

/** Local visual review of Reports with fictional numbers. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <ReportsPreview />;
}
