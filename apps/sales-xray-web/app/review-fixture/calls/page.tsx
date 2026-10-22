import { notFound } from "next/navigation";

import { CallsPreview } from "./calls-preview";

/** Local visual review of Calls with fictional calls. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CallsPreview />;
}
