import { notFound } from "next/navigation";

import { HomePreview } from "./home-preview";

/** Local visual review of Home in an organisation with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <HomePreview />;
}
