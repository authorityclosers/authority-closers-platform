import { notFound } from "next/navigation";

import { RecordedCallsPreview } from "./recorded-calls-preview";

/** Local visual review of recorded dialer calls and Xiaomi's phone setup, with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <RecordedCallsPreview />;
}
