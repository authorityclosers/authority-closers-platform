import { notFound } from "next/navigation";

import { CaptureSetupPreview } from "./preview";

/** Local visual review of call capture setup with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CaptureSetupPreview />;
}
