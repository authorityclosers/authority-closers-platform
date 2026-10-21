import { notFound } from "next/navigation";

import { CallAiPreview } from "./call-ai-preview";

/** Local visual review of AI on calls with fictional people. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CallAiPreview />;
}
