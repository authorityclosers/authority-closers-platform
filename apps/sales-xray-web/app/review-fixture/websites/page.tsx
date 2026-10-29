import { notFound } from "next/navigation";

import { WebsitesPreview } from "./websites-preview";

/** Local visual review of Leads → Sources → Websites with fictional sites. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <WebsitesPreview />;
}
