import { notFound } from "next/navigation";

import { FullShellPreview } from "./full-shell-preview";

/** Local visual review of the full shell. Never available in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <FullShellPreview />;
}
