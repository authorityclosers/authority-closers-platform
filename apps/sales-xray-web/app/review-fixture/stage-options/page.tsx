import { notFound } from "next/navigation";

import { StageOptionsPreview } from "./stage-options-preview";

/** Local visual review of lead stage options for the owner. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <StageOptionsPreview />;
}
