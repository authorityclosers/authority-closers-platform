import { FileQuestion } from "lucide-react";
import { notFound } from "next/navigation";

import {
  normalizeBundle,
  normalizeCall,
  normalizeQueue,
  pickRun,
  STATUS_LABEL,
  when,
} from "@/app/calls/call-data";
import { FailedSteps } from "@/app/calls/failed-steps";
import { queueApiPath, queueFilters } from "@/app/calls/queue-query";
import { startAt } from "@/app/calls/review-logic";
import { normalizeCallDetail } from "@/app/calls/call-detail-data";
import {
  normalizeCoachingPoints,
  normalizeReviewCall,
} from "@/app/calls/review-verdicts-data";
import { ReviewScreen } from "@/app/calls/review-screen";
import { normalizeLabels } from "@/app/calls/labels-data";
import { loadConsoleAccess } from "@/app/lib/console-access";
import { adminRead } from "@/app/lib/server-api";
import {
  Badge,
  Card,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const one = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value;

/** One call: everything the screen needs is read together, so it arrives whole. */
export default async function CallReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ recordingId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { recordingId } = await params;
  if (!UUID.test(recordingId)) notFound();
  const query = await searchParams;
  const back = one(query.back) ?? "";
  const wanted = one(query.run);
  const compareId = one(query.compare);
  const backFilters = queueFilters(
    Object.fromEntries(new URLSearchParams(back)),
  );
  delete backFilters.cursor;

  const call = await adminRead(
    `/v1/admin/conversation/calls/${recordingId}`,
    normalizeCall,
  );
  const backHref = back ? `/calls?${back}` : "/calls";
  if (!call.ok)
    return (
      <Page>
        <PageHeader title="Call" back={{ href: backHref, label: "Calls" }} />
        <Unavailable title="This call" reason={call.error} />
      </Page>
    );
  const run = pickRun(call.data, wanted);
  const compareRun = compareId
    ? call.data.runs.find((item) => item.id === compareId && item.reportId)
    : undefined;
  const [bundle, compared, queue, access, labels, analysis, review] =
    await Promise.all([
      run
        ? adminRead(
            `/v1/admin/conversation/runs/${run.id}/review`,
            normalizeBundle,
          )
        : null,
      compareRun && compareRun.id !== run?.id
        ? adminRead(
            `/v1/admin/conversation/runs/${compareRun.id}/review`,
            normalizeBundle,
          )
        : null,
      back ? adminRead(queueApiPath(backFilters, 100), normalizeQueue) : null,
      loadConsoleAccess(),
      adminRead(
        `/v1/admin/conversation/calls/${recordingId}/labels`,
        normalizeLabels,
      ),
      adminRead(
        `/v1/admin/call-data/calls/${recordingId}/detail`,
        normalizeCallDetail,
      ),
      // Review 2.0: answers for gold reviewers; anyone else gets a 403 and no chips.
      adminRead(
        `/v1/admin/conversation/review/calls/${recordingId}`,
        normalizeReviewCall,
      ),
    ]);

  if (!run || !bundle?.ok)
    return (
      <Page>
        <PageHeader
          title={call.data.rep.label}
          back={{ href: backHref, label: "Calls" }}
          context={[
            call.data.organisation.name,
            STATUS_LABEL[call.data.status],
          ]}
        />
        {bundle && !bundle.ok ? (
          <Unavailable title="This call's report" reason={bundle.error} />
        ) : null}
        {!run ? (
          <Panel title="Nothing to review yet">
            <Empty
              icon={FileQuestion}
              title={
                call.data.status === "analysing"
                  ? "The analysis is still running"
                  : call.data.status === "failed"
                    ? "The analysis failed"
                    : "This call has no report"
              }
              text="A call can be reviewed once one of its runs has a saved report."
            />
          </Panel>
        ) : null}
        {call.data.failedJobs.length ? (
          <Panel title="Failed steps" sub="Retry asks for a reason">
            <FailedSteps jobs={call.data.failedJobs} inset />
          </Panel>
        ) : null}
        {call.data.runs.length ? (
          <Panel title="Runs" sub={`${call.data.runs.length} on this call`}>
            <Table
              label="Runs"
              cards={call.data.runs.map((item) => (
                <Card key={item.id}>
                  <strong>{when(item.createdAt)}</strong>
                  <span>
                    {item.reportId ? "Report" : item.state} ·{" "}
                    {item.model ?? item.provider ?? "model not recorded"} ·{" "}
                    {item.promptRevision ?? "prompt not recorded"}
                  </span>
                </Card>
              ))}
            >
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">State</th>
                  <th scope="col">Model</th>
                  <th scope="col">Prompt</th>
                </tr>
              </thead>
              <tbody>
                {call.data.runs.map((item) => (
                  <tr key={item.id}>
                    <th scope="row">{when(item.createdAt)}</th>
                    <td>
                      <Badge
                        tone={
                          item.reportId
                            ? "good"
                            : item.state === "failed"
                              ? "bad"
                              : "neutral"
                        }
                      >
                        {item.reportId ? "Report" : item.state}
                      </Badge>
                    </td>
                    <td>{item.model ?? item.provider ?? "Not recorded"}</td>
                    <td>{item.promptRevision ?? "Not recorded"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
        ) : null}
      </Page>
    );

  // Review 2.0's coaching review: this run's coaching as points, for gold reviewers.
  const coaching = review.ok
    ? await adminRead(
        `/v1/admin/conversation/review/calls/${recordingId}/coaching?run=${run.id}`,
        normalizeCoachingPoints,
      )
    : null;
  const ids = queue?.ok ? queue.data.items.map((item) => item.recordingId) : [];
  const at = ids.indexOf(recordingId);
  return (
    <ReviewScreen
      // A new call or run starts fresh: position, marked line and audio state
      // never carry over from the call before (N / P reuse this page).
      key={`${recordingId}:${run.id}`}
      call={call.data}
      bundle={bundle.data}
      compare={compareRun && compareRun.id !== run.id ? compareRun.id : null}
      compareBundle={compared?.ok ? compared.data : null}
      back={back}
      safety={access.platform.includes("platform_content_safety_manage")}
      labels={labels.ok ? labels.data : null}
      analysis={analysis.ok ? analysis.data : null}
      review={review.ok ? review.data : null}
      coachingPoints={coaching?.ok ? coaching.data : null}
      startMs={startAt(one(query.at))}
      initialTab={one(query.tab) === "analysis" ? "analysis" : null}
      neighbours={{
        previous: at > 0 ? (ids[at - 1] ?? null) : null,
        next: at >= 0 ? (ids[at + 1] ?? null) : null,
      }}
    />
  );
}
