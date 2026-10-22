import { notFound } from "next/navigation";

import { SettingsPreview } from "./settings-preview";

/** Local visual review of Settings with a fictional organisation. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SettingsPreview />;
}
