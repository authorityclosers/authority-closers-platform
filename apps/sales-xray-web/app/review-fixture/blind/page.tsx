import { notFound } from "next/navigation";

import { BlindPreview } from "./preview";

/**
 * Local visual review of the blind Brain 4.0 rating in /review with a fictional
 * call. `?phase=rate` opens a started call, `?phase=reveal` the comparison after
 * all 18 ratings; otherwise the first screen. Never in a production build.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { phase } = await searchParams;
  const shown = phase === "rate" || phase === "reveal" ? phase : "intro";
  return <BlindPreview key={shown} phase={shown} />;
}
