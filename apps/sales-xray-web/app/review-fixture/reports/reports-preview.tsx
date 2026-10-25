"use client";

/**
 * Reports with fictional numbers, for the visual matrix: an owner (default),
 * `?role=seller` (no team reports), `?quiet=1` (a new account: nothing stands
 * out, plain lines), `?loading=1` (every line still loading).
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { ReportsHub } from "../../reports/reports-hub";
import { REPORTS_FIXTURE } from "../../reports/reports-fixture";

function Preview() {
  const params = useSearchParams();
  const manager = params.get("role") !== "seller";
  const data =
    params.get("loading") === "1"
      ? {}
      : params.get("quiet") === "1"
        ? { calls: null, pipeline: null, performance: null, sla: null }
        : REPORTS_FIXTURE;
  return (
    <main style={{ padding: 16, maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ margin: "0 0 16px" }}>Reports</h1>
      <ReportsHub manager={manager} data={data} />
    </main>
  );
}

export function ReportsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
