import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ReturnFixture } from "../plans-fixture";

/** Local visual review only. The route is never available in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Suspense fallback={null}>
      <ReturnFixture />
    </Suspense>
  );
}
