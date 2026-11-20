import { notFound } from "next/navigation";

import { OldCallsPreview } from "./old-calls-preview";

/** Local visual review of Find my old calls, with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <OldCallsPreview />;
}
