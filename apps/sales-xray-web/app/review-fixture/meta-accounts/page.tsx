import { notFound } from "next/navigation";

import { MetaAccountsPreview } from "./meta-accounts-preview";

/** Local visual review of Facebook & Instagram by account, with fictional accounts and Pages. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <MetaAccountsPreview />;
}
