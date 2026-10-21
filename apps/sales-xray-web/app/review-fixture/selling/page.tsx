import { notFound } from "next/navigation";

import { SellingPreview } from "./selling-preview";

/** Local visual review of Settings → Selling with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SellingPreview />;
}
