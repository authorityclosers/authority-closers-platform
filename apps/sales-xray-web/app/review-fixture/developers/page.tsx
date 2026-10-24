import { notFound } from "next/navigation";

import { DevelopersPreview } from "./developers-preview";

/** Local visual review of the Developers screen with fictional keys and connections. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DevelopersPreview />;
}
