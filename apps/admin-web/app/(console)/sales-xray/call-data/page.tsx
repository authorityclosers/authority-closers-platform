import { Database } from "lucide-react";
import Link from "next/link";

import { when } from "@/app/calls/call-data";
import { duration, rupees } from "@/app/calls/call-map-data";
import { adminRead } from "@/app/lib/server-api";
import { normalizeCallData } from "@/app/sales-xray/call-data-model";
import { CallDataSettingsForm } from "@/app/sales-xray/call-data-settings";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const STATE_TONE: Record<string, "good" | "bad" | "neutral"> = {
  succeeded: "good",
  failed: "bad",
  skipped: "neutral",
};

/**
 * Admin → Call data (call data engine, owner 19 Oct): the model, switch and
 * daily cap for each pipeline, today's spend and the latest runs, each linked
 * to its call's pipeline map.
 */
export default async function CallDataPage() {
  const result = await adminRead("/v1/admin/call-data", normalizeCallData);
  if (!result.ok)
    return (
      <Page>
        <PageHeader title="Call data" />
        <Unavailable title="Call data settings" reason={result.error} />
      </Page>
    );
  const data = result.data;
  const fastCap = data.config.fast.dailyCapInr;
  return (
    <Page>
      <PageHeader
        title="Call data"
        context={[
          `Fast pipeline today ${rupees(data.spentToday.fast) || "₹0.00"} of ₹${fastCap}`,
          data.revision
            ? `Settings revision ${data.revision}`
            : "Default settings",
        ]}
      />
      <Panel
        title="Pipelines"
        sub="Every call becomes typed facts. Keys stay in Infisical."
      >
        <CallDataSettingsForm settings={data} />
      </Panel>
      <Panel title="Latest runs" sub={`${data.recent.length} shown`}>
        {data.recent.length ? (
          <Table label="Latest runs">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Workspace</th>
                <th scope="col">Pipeline</th>
                <th scope="col">Result</th>
                <th scope="col">Facts</th>
                <th scope="col">Time</th>
                <th scope="col">Cost</th>
                <th scope="col">Map</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((run) => (
                <tr key={`${run.recordingId}-${run.at}`}>
                  <th scope="row">{when(run.at)}</th>
                  <td>{run.workspace}</td>
                  <td>{run.pipeline}</td>
                  <td>
                    <Badge tone={STATE_TONE[run.state] ?? "neutral"}>
                      {run.reason ? `${run.state}: ${run.reason}` : run.state}
                    </Badge>
                  </td>
                  <td>{run.facts ?? "—"}</td>
                  <td>{duration(run.durationMs) || "—"}</td>
                  <td>{rupees(run.costInr) || "—"}</td>
                  <td>
                    <Link href={`/calls/${run.recordingId}/map`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty
            icon={Database}
            title="No runs yet"
            text="The fast pipeline reads each new call's transcript."
          />
        )}
      </Panel>
    </Page>
  );
}
