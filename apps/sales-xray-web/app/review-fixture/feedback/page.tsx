import { notFound } from "next/navigation";

import { FeedbackPreview } from "./feedback-preview";

/** Local visual review of the feedback prompts with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <FeedbackPreview />;
}
