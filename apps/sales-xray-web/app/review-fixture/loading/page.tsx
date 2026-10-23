import { notFound } from "next/navigation";

import { LoadingPreview } from "./loading-preview";

/** Local visual review of each screen's loading outline. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <LoadingPreview />;
}
