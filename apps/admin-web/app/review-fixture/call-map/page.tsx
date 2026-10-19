import { notFound } from "next/navigation";

import { CallMapFixture } from "./call-map-fixture";

/** Local review of a call's pipeline map and engine objects. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CallMapFixture />;
}
