"use client";

import { NewAnalysisSkeleton } from "./analysis/new/new-analysis-skeleton";

/** Shown by Next.js while the root (studio) page suspends. */
export default function Loading() {
  return <NewAnalysisSkeleton />;
}
