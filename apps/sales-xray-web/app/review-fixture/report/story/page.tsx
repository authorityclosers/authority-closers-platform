import { notFound } from "next/navigation";

import { EXAMPLE_KINDS } from "../../../xray-report/example";
import type { OutcomeKind } from "../../../xray-report/model";
import { StoryShellPreview } from "./preview";

/**
 * `?example=won|lost|follow_up|decision_pending` shows the 15 Oct doc's
 * illustrative example (default follow_up); `?example=none` shows the
 * fictional Amit call through the real data mapping, and `?example=api` the
 * same call with a saved AI pointer review, exactly as the API sends it.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { example } = await searchParams;
  if (example === "api") return <StoryShellPreview key="api" apiStructure />;
  const kind =
    example === "none"
      ? null
      : EXAMPLE_KINDS.includes(example as OutcomeKind)
        ? (example as OutcomeKind)
        : "follow_up";
  return <StoryShellPreview key={kind ?? "none"} example={kind} />;
}
