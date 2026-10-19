import { ClipboardCheck } from "lucide-react";
import Link from "next/link";

import { when } from "@/app/calls/call-data";
import { normalizeReviewQueue, queueHref } from "@/app/calls/review-queue-data";
import styles from "@/app/calls/calls.module.css";
import { adminRead } from "@/app/lib/server-api";
import { KIND_BADGE, KIND_TONE } from "@/app/lib/workspaces";
import {
  Badge,
  Empty,
  Meter,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Analysis review (Review 2.0, owner 19 Oct: "reviewers judge the
 * underlying analysis, not the report"): the calls the pipeline samples,
 * newest first, with your progress. Each opens on the call's Analysis tab,
 * where every fact takes a one-tap verdict.
 */
export default async function AnalysisReviewPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const options = { sandbox: query.sandbox === "1", done: query.done === "1" };
  const params = new URLSearchParams({ pipeline: "analysis-sales" });
  if (options.sandbox) params.set("sandbox", "true");
  if (options.done) params.set("done", "true");
  const result = await adminRead(
    `/v1/admin/conversation/review/queue?${params.toString()}`,
    normalizeReviewQueue,
  );
  if (!result.ok)
    return (
      <Page>
        <PageHeader title="Analysis review" />
        <Unavailable title="Analysis review" reason={result.error} />
      </Page>
    );
  const queue = result.data;
  const left = queue.items.reduce(
    (sum, item) => sum + Math.max(0, item.items - item.answered),
    0,
  );
  return (
    <Page wide>
      <PageHeader
        title="Analysis review"
        context={[
          `${queue.pipeline.title} · version ${queue.pipeline.version}`,
          `${queue.items.length} calls · ${left} items to judge`,
          "Judges the analysis, never the report layout",
        ]}
        actions={
          <span className={styles.hint}>
            <Link
              href={queueHref(options, "sandbox")}
              className={kitStyles.button}
              aria-pressed={options.sandbox}
            >
              {options.sandbox ? "Hide sandbox" : "Include sandbox"}
            </Link>{" "}
            <Link
              href={queueHref(options, "done")}
              className={kitStyles.button}
              aria-pressed={options.done}
            >
              {options.done ? "Hide finished" : "Show finished"}
            </Link>
          </span>
        }
      />
      <Panel
        title="Calls to review"
        sub="Newest analysis first · open a call, then Right, Wrong or Unsure on each fact"
      >
        {queue.items.length ? (
          <Table label="Calls to review">
            <thead>
              <tr>
                <th scope="col">Call</th>
                <th scope="col">Analysed</th>
                <th scope="col">Your progress</th>
                <th scope="col" data-num="">
                  Others
                </th>
                <th scope="col">
                  <span className={styles.srOnly}>Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {queue.items.map((item) => (
                <tr key={item.recordingId} className={styles.callRow}>
                  <th scope="row" className={styles.callCell}>
                    <Link
                      href={`/calls/${item.recordingId}?tab=analysis`}
                      className={styles.rowLink}
                      data-call-link=""
                    >
                      {item.organisation.name}
                    </Link>{" "}
                    <Badge tone={KIND_TONE[item.organisation.kind]}>
                      {KIND_BADGE[item.organisation.kind]}
                    </Badge>
                    <span className={styles.sub}>
                      Uploaded {item.uploadedAt ? when(item.uploadedAt) : "—"}
                    </span>
                  </th>
                  <td>{item.analysedAt ? when(item.analysedAt) : "—"}</td>
                  <td>
                    <Meter
                      value={item.answered}
                      max={Math.max(1, item.items)}
                      label={`${item.answered} of ${item.items} judged`}
                    />
                    <span className={styles.sub}>
                      {item.answered} of {item.items} judged
                    </span>
                  </td>
                  <td data-num="">
                    {item.others || <span className={kitStyles.muted}>—</span>}
                  </td>
                  <td>
                    <Link
                      href={`/calls/${item.recordingId}?tab=analysis`}
                      className={styles.mapLink}
                    >
                      Review
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty
            icon={ClipboardCheck}
            title="Nothing waiting"
            text="Every sampled call is judged. Show finished calls or include the sandbox to see more."
          />
        )}
      </Panel>
    </Page>
  );
}
