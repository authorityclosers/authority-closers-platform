import { notFound } from "next/navigation";

import { ColdCallingPreview } from "./cold-calling-preview";

/** Local visual review of the cold-calling mode proposal. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <ColdCallingPreview />;
}
