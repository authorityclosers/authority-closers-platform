import { notFound } from "next/navigation";

import { DeleteAccountPreview } from "./delete-account-preview";

/** Local visual review of Settings → Security → Delete account. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DeleteAccountPreview />;
}
