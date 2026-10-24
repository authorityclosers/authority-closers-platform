import { notFound } from "next/navigation";

import {
  ACTION_WORDS,
  KEY_ACTIONS,
  devicesQuery,
  normalizeComparison,
  normalizeDevices,
  normalizeFixNext,
} from "../../telemetry/loop-data";
import {
  DevicesView,
  FixNextView,
  LoopTabs,
  ReleasesView,
} from "../../telemetry/loop-view";
import { Page, PageHeader, QueryTabs } from "../../ui/kit";
import { compareFixture, devicesFixture, fixNextFixture } from "./loop-fixture";

const BASE = "/review-fixture/telemetry-loop";
const HREFS = {
  overview: "/review-fixture/telemetry",
  devices: BASE,
  releases: `${BASE}?view=releases`,
  fix: `${BASE}?view=fix`,
};

/**
 * Local review of Devices, Releases and Fix next with fictional numbers (no API, no
 * account). Never in a production build.
 */
export default async function TelemetryLoopFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; state?: string; action?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const params = await searchParams;
  const now = new Date();
  const state = params.state === "empty" ? "empty" : "live";
  const view =
    params.view === "releases" || params.view === "fix"
      ? params.view
      : "devices";
  const { action } = devicesQuery({ action: params.action });
  return (
    <Page wide>
      <PageHeader
        title={
          view === "fix"
            ? "Fix next"
            : view === "releases"
              ? "Releases"
              : "Devices"
        }
        context={["Fixture: fictional numbers"]}
      />
      <LoopTabs current={view} hrefs={HREFS} />
      {view === "devices" ? (
        <DevicesView
          devices={normalizeDevices(devicesFixture(now, state))}
          action={action}
          actionTabs={
            <QueryTabs
              base={BASE}
              param="action"
              items={KEY_ACTIONS.map((key) => ({
                key,
                label: ACTION_WORDS[key],
              }))}
              current={action}
            />
          }
        />
      ) : view === "releases" ? (
        <ReleasesView comparison={normalizeComparison(compareFixture(now))} />
      ) : (
        <FixNextView fixNext={normalizeFixNext(fixNextFixture(now, state))} />
      )}
    </Page>
  );
}
