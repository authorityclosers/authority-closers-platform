import { notFound } from "next/navigation";

import { AiAppsPreview } from "./ai-apps-preview";

/** Local visual review of Settings → AI apps with fictional connections. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <AiAppsPreview />;
}
