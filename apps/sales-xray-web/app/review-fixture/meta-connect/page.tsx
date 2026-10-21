import { notFound } from "next/navigation";

import { MetaConnectPreview } from "./meta-connect-preview";

/** Local visual review of the guided lead ads setup with fictional Pages. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <MetaConnectPreview />;
}
