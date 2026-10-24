import { adminRead } from "@/app/lib/server-api";
import {
  ACTION_WORDS,
  KEY_ACTIONS,
  LOOP_WINDOWS,
  devicesQuery,
  normalizeDevices,
} from "@/app/telemetry/loop-data";
import { DevicesView, LOOP_HREFS, LoopTabs } from "@/app/telemetry/loop-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const WINDOW_WORDS: Record<string, string> = {
  "7d": "7 days",
  "24h": "24 hours",
  "30d": "30 days",
};
const APP_WORDS: Record<string, string> = {
  all: "All",
  android: "Android app",
  web: "Web",
};

/**
 * Admin → Product telemetry → Devices (owner, 24 Oct 2026: "where is the telemetry data of
 * each device"): every phone model and device kind with its versions and tiers, speed on
 * the key actions, issues, and the slowest 10% of devices.
 */
export default async function TelemetryDevicesPage({
  searchParams,
}: {
  searchParams: Promise<{ window?: string; app?: string; action?: string }>;
}) {
  const query = devicesQuery(await searchParams);
  const result = await adminRead(query.path, normalizeDevices);
  const keep = (skip: "window" | "app" | "action") =>
    [
      skip !== "window" && query.window !== "7d"
        ? `window=${query.window}`
        : "",
      skip !== "app" && query.app !== "all" ? `app=${query.app}` : "",
      skip !== "action" && query.action !== "lead_open"
        ? `action=${query.action}`
        : "",
    ]
      .filter(Boolean)
      .join("&");
  return (
    <Page wide>
      <PageHeader
        title="Devices"
        context={[
          "Every phone model and device kind using Sales X-Ray here: versions, tiers, speed on key actions and issues. Never a person's name.",
        ]}
      />
      <LoopTabs current="devices" hrefs={LOOP_HREFS} />
      <QueryTabs
        base="/telemetry/devices"
        param="window"
        items={LOOP_WINDOWS.map((key) => ({
          key,
          label: WINDOW_WORDS[key] ?? key,
        }))}
        current={query.window}
        keep={keep("window")}
      />
      <QueryTabs
        base="/telemetry/devices"
        param="app"
        items={["all", "android", "web"].map((key) => ({
          key,
          label: APP_WORDS[key] ?? key,
        }))}
        current={query.app}
        keep={keep("app")}
      />
      {result.ok ? (
        <DevicesView
          devices={result.data}
          action={query.action}
          actionTabs={
            <QueryTabs
              base="/telemetry/devices"
              param="action"
              items={KEY_ACTIONS.map((key) => ({
                key,
                label: ACTION_WORDS[key],
              }))}
              current={query.action}
              keep={keep("action")}
            />
          }
        />
      ) : (
        <Unavailable title="Devices" reason={result.error} />
      )}
    </Page>
  );
}
