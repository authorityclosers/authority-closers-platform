import { notFound } from "next/navigation";

import { MetaSourcesPreview } from "./meta-sources-preview";

/** Local visual review of Facebook lead sources with fictional accounts and Pages. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <MetaSourcesPreview />;
}
