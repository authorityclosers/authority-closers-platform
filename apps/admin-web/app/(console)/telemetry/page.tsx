import { adminRead } from "@/app/lib/server-api";
import {
  APPS,
  DEVICES,
  TIERS,
  WINDOWS,
  keepFilters,
  normalizeTelemetry,
  telemetryQuery,
} from "@/app/telemetry/telemetry-data";
import { TelemetryView } from "@/app/telemetry/telemetry-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const WINDOW_WORDS: Record<string, string> = {
  "7d": "7 days",
  "24h": "24 hours",
  "30d": "30 days",
};

const words = (value: string) =>
  value === "all" ? "All" : value.charAt(0).toUpperCase() + value.slice(1);

/**
 * Admin → Product telemetry (owner, 24 Oct 2026: "Build full performance and usage
 * telemetry with the Admin dashboard"): this environment's speed per action, Web Vitals,
 * screens, funnels, features, errors and releases, filtered by window, release, device,
 * app and device tier. Counts and timings only.
 */
export default async function ProductTelemetryPage({
  searchParams,
}: {
  searchParams: Promise<{
    window?: string;
    release?: string;
    device?: string;
    app?: string;
    tier?: string;
  }>;
}) {
  const query = telemetryQuery(await searchParams);
  const result = await adminRead(query.path, normalizeTelemetry);
  const releases = result.ok ? result.data.releases : [];
  return (
    <Page wide>
      <PageHeader
        title="Product telemetry"
        context={[
          "How Sales X-Ray is used and how fast it responds, from this environment's apps: on unless a person or workspace turned it off, never call content. Kept 180 days.",
        ]}
      />
      <QueryTabs
        base="/telemetry"
        param="window"
        items={WINDOWS.map((key) => ({ key, label: WINDOW_WORDS[key] ?? key }))}
        current={query.window}
        keep={keepFilters(query, "window")}
      />
      <QueryTabs
        base="/telemetry"
        param="device"
        items={DEVICES.map((key) => ({ key, label: words(key) }))}
        current={query.device}
        keep={keepFilters(query, "device")}
      />
      <QueryTabs
        base="/telemetry"
        param="tier"
        items={TIERS.map((key) => ({ key, label: words(key) }))}
        current={query.tier}
        keep={keepFilters(query, "tier")}
      />
      <QueryTabs
        base="/telemetry"
        param="app"
        items={APPS.map((key) => ({ key, label: words(key) }))}
        current={query.app}
        keep={keepFilters(query, "app")}
      />
      {releases.length > 1 || query.release ? (
        <QueryTabs
          base="/telemetry"
          param="release"
          items={[
            { key: "all", label: "All releases" },
            ...releases.map((key) => ({ key, label: key })),
          ]}
          current={query.release ?? "all"}
          keep={keepFilters(query, "release")}
        />
      ) : null}
      {result.ok ? (
        <TelemetryView telemetry={result.data} />
      ) : (
        <Unavailable title="Product telemetry" reason={result.error} />
      )}
    </Page>
  );
}
