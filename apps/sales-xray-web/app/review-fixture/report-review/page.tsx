import { notFound } from "next/navigation";

import { ReportPreview } from "./preview";

/**
 * Local visual review of the Report review in /review with a fictional call.
 * `?phase=fix` opens a started call with Fix chosen on a skill, `?phase=text` Fix on
 * a written item, `?phase=done` the end; otherwise the first item. Never in a
 * production build.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { phase } = await searchParams;
  const shown =
    phase === "fix" || phase === "text" || phase === "done" ? phase : "start";
  return <ReportPreview key={shown} phase={shown} />;
}
