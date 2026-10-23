import { notFound } from "next/navigation";

import { HubPreview } from "./hub-preview";

/** Local visual review of the organisation hub with a fictional organisation. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <HubPreview />;
}
