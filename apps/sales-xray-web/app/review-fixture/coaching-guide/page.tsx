import { notFound } from "next/navigation";

import { CoachingGuideFixture } from "./preview";

/** Local and dev visual review of Dipak's answers with EXAMPLE rows. Never in a production build. */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { part } = await searchParams;
  return (
    <CoachingGuideFixture part={typeof part === "string" ? part : undefined} />
  );
}
