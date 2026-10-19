import { notFound } from "next/navigation";

import { CallFactsFixture } from "./call-facts-fixture";

/** Local review of the lead screen's "From the calls" card. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CallFactsFixture />;
}
