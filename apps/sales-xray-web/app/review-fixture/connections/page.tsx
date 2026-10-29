import { notFound } from "next/navigation";

import { ConnectionsPreview } from "./connections-preview";

/** Local visual review of Organisation → Connections with every part answered. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <ConnectionsPreview />;
}
