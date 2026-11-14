import { notFound } from "next/navigation";
import { Suspense } from "react";

import { AskDipakFixture } from "./preview";

/**
 * Local and dev visual review of Ask Dipak (wb-ci --visual). Never in a
 * production build. The screen is in the query, as on /ask-dipak
 * (?lesson=PB03, ?view=topics …); &pick=1 picks option B and opens the Deep
 * lesson, for the feedback and lesson shots.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { pick, lesson } = await searchParams;
  return (
    <Suspense>
      <AskDipakFixture
        pick={pick === "1" && typeof lesson === "string" ? lesson : null}
      />
    </Suspense>
  );
}
