import { notFound } from "next/navigation";

import { AlertsPreview } from "./alerts-preview";

/** Local visual review of alerts by urgency with fictional work. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <AlertsPreview />;
}
