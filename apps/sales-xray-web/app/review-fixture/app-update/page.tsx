import { notFound } from "next/navigation";

import { AppUpdatePreview } from "./app-update-preview";

/** Local visual review of the app update card. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <AppUpdatePreview />;
}
