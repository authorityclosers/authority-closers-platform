import type { Metadata } from "next";
import { Suspense } from "react";

import { AskDipakRoute, AskDipakSkeleton } from "./ask-dipak-page";

export const metadata: Metadata = { title: "Ask Dipak" };

/** Ask Dipak's library; its screens are in the query (?lesson=PB03), read under Suspense. */
export default function Page() {
  return (
    <Suspense fallback={<AskDipakSkeleton />}>
      <AskDipakRoute />
    </Suspense>
  );
}
