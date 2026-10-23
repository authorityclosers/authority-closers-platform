import { notFound } from "next/navigation";

import { SwitchesPreview } from "./switches-preview";

/** Local visual review of the switches that matter (owner, 23 Oct 2026). Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SwitchesPreview />;
}
