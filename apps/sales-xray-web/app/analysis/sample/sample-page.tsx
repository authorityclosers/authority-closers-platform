"use client";

import { useSyncExternalStore } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { sampleCall } from "./sample-call";
import { SampleBanner, SampleReportView } from "./sample-report-view";

const data = sampleCall();

/**
 * /analysis/sample: what a report shows, on a fictional call, for a new
 * workspace (Home's "Let's get you calling" links here). The real report and
 * call dock; the recording plays; nothing is read from the API.
 */
const never = () => () => {};

/** True in the browser, false while the server renders. */
const useInBrowser = () =>
  useSyncExternalStore(
    never,
    () => true,
    () => false,
  );

export function SamplePage() {
  // Drawn in the browser only, as every other report is: its dates read
  // relative to now, and the server's now is not the reader's (a review clock
  // set to another day showed it as a hydration error, 28 Oct 2026).
  if (!useInBrowser())
    return (
      <AcquisitionShell authenticated={false} loading active="analyse">
        {null}
      </AcquisitionShell>
    );
  return (
    <SampleReportView
      variant="sample"
      homeHref="/dashboard"
      banner={<SampleBanner />}
      data={data}
    />
  );
}
