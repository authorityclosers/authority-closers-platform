import { notFound } from "next/navigation";

import { GrowthPreview } from "./growth-preview";

/** Local visual review of Growth's tiles and hour bars with fictional numbers. Never in a production build. */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ quiet?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { quiet } = await searchParams;
  return <GrowthPreview quiet={quiet === "1"} />;
}
