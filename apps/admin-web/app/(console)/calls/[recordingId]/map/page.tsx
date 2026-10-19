import { notFound } from "next/navigation";

import { when } from "@/app/calls/call-data";
import { normalizeCallDetail, type Branch } from "@/app/calls/call-detail-data";
import styles from "@/app/calls/call-detail.module.css";
import { duration, rupees } from "@/app/calls/call-map-data";
import { EngineObjectsView } from "@/app/calls/engine-objects";
import { LiveRefresh } from "@/app/calls/live-refresh";
import { ObjectsTable } from "@/app/calls/objects-table";
import { PipelineGraph } from "@/app/calls/pipeline-graph";
import { adminRead } from "@/app/lib/server-api";
import { KIND_BADGE, KIND_TONE } from "@/app/lib/workspaces";
import {
  Badge,
  Kpi,
  Page,
  PageHeader,
  Panel,
  Table,
  Tiles,
  Unavailable,
  type Tone,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const BRANCH_LABEL: Record<Branch | "call", string> = {
  call: "Whole call",
  main: "Main",
  fast: "Fast read",
  deep: "Deep read",
  report: "Report",
};

const RUN_TONE: Record<string, Tone> = {
  succeeded: "good",
  done: "good",
  failed: "bad",
  uncertain: "warn",
  running: "accent",
};

const tokens = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);

/**
 * One call's analysis map (owner 19 Oct: "much, much denser"; "all data for
 * making it better has to be there"): the pipeline as a graph, cost and tokens
 * per branch, every object ever made, every engine run, then voice, timeline
 * and facts. One read: GET /v1/admin/call-data/calls/{id}/detail.
 */
export default async function CallMapPage({
  params,
}: {
  params: Promise<{ recordingId: string }>;
}) {
  const { recordingId } = await params;
  if (!UUID.test(recordingId)) notFound();
  const result = await adminRead(
    `/v1/admin/call-data/calls/${recordingId}/detail`,
    normalizeCallDetail,
  );
  const back = { href: `/calls/${recordingId}`, label: "Call" };
  if (!result.ok)
    return (
      <Page>
        <PageHeader title="Analysis map" back={back} />
        <Unavailable title="This call's analysis map" reason={result.error} />
      </Page>
    );
  const detail = result.data;
  const { call } = detail;
  const branches: (Branch | "call")[] = [
    "call",
    "fast",
    "deep",
    "report",
    "main",
  ];

  return (
    <Page>
      <PageHeader
        title="Analysis map"
        back={back}
        context={[
          <span key="org">
            {call.organisation.name}{" "}
            <Badge tone={KIND_TONE[call.organisation.kind]}>
              {KIND_BADGE[call.organisation.kind]}
            </Badge>
          </span>,
          call.rep.label,
          call.language,
          duration(call.mediaMs) || null,
          call.state,
          call.environment,
          detail.taxonomyVersion ? `taxonomy ${detail.taxonomyVersion}` : null,
          recordingId.slice(0, 8),
        ]}
      />
      <LiveRefresh
        active={detail.stages.some((stage) => stage.status === "running")}
      />
      <Tiles label="Cost and tokens by branch">
        {branches.map((key) => {
          const total = detail.totals[key];
          return (
            <Kpi
              key={key}
              label={BRANCH_LABEL[key]}
              value={rupees(total.costInr) || "₹0.00"}
              note={`${tokens(total.tokensIn)} in · ${tokens(total.tokensOut)} out tokens`}
            />
          );
        })}
      </Tiles>
      <Panel
        title="Pipeline"
        sub={`${detail.stages.filter((stage) => stage.status === "done").length} of ${detail.stages.length} stages done · hover a stage for model, tokens and attempts`}
      >
        <PipelineGraph stages={detail.stages} edges={detail.edges} />
      </Panel>
      <Panel
        title="Objects"
        sub={`${detail.objects.length} made · current, superseded, retracted and erased, with decisions`}
      >
        <ObjectsTable objects={detail.objects} />
      </Panel>
      <Panel
        title="Engine runs"
        sub={`${detail.runs.length} attempts, newest first · "uncertain" means a start with no recorded outcome`}
      >
        <Table label="Engine runs">
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Read</th>
              <th scope="col">State</th>
              <th scope="col">Model</th>
              <th scope="col">Prompt</th>
              <th scope="col" data-num="">
                Tokens in / out
              </th>
              <th scope="col" data-num="">
                Cost
              </th>
              <th scope="col" data-num="">
                Time
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.runs.map((run) => (
              <tr key={run.runId}>
                <th scope="row">{run.startedAt ? when(run.startedAt) : "—"}</th>
                <td>
                  {[run.pipeline, run.version].filter(Boolean).join(" · ")}
                  <small className={styles.sub}>
                    {[
                      run.trigger,
                      run.attempt ? `attempt ${run.attempt}` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </td>
                <td>
                  <Badge tone={RUN_TONE[run.state] ?? "neutral"}>
                    {run.state}
                  </Badge>
                  {run.reason ? (
                    <small className={styles.sub}>{run.reason}</small>
                  ) : null}
                </td>
                <td>
                  {[run.provider, run.model].filter(Boolean).join(" · ") || "—"}
                </td>
                <td className={styles.mono} title={run.promptSha ?? undefined}>
                  {run.promptSha ? run.promptSha.slice(0, 10) : "—"}
                </td>
                <td data-num="">
                  {run.tokensIn ?? "—"} / {run.tokensOut ?? "—"}
                </td>
                <td data-num="">{rupees(run.costInr) || "—"}</td>
                <td data-num="">{duration(run.durationMs) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
      <EngineObjectsView data={detail.engine} />
    </Page>
  );
}
