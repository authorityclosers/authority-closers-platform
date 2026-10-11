import Link from "next/link";
import { ShieldCheck } from "lucide-react";

import { when } from "@/app/calls/call-data";
import { adminRead } from "@/app/lib/server-api";
import { MarkSegments, ReleaseMark } from "@/app/safety/safety-actions";
import {
  activeMarks,
  categoryLabel,
  normalizeMarks,
} from "@/app/safety/safety-data";
import styles from "@/app/safety/safety.module.css";
import {
  Badge,
  Empty,
  Page,
  PageHeader,
  Panel,
  Table,
  Unavailable,
  Why,
  kitStyles,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Withhold sensitive passages of a call from every reader, by segment id (ADR 0051). */
export default async function SafetyPage({
  searchParams,
}: {
  searchParams: Promise<{ recording?: string }>;
}) {
  const { recording } = await searchParams;
  const recordingId =
    recording && UUID.test(recording) ? recording.toLowerCase() : null;
  const result = recordingId
    ? await adminRead(
        `/v1/platform/sensitive-segments/recordings/${recordingId}`,
        normalizeMarks,
      )
    : null;
  const data = result?.ok ? result.data : null;
  const active = data ? activeMarks(data.marks) : [];
  return (
    <Page>
      <PageHeader
        title="Safety"
        context={[
          "Withhold sensitive passages from transcripts, reports and exports",
        ]}
        actions={
          <Why detail="A withheld passage is replaced by a marker for every reader: the rep, managers, reviewers and Admin. Marks never store the passage text; releasing one is a new, audited record." />
        }
      />
      <form
        method="get"
        action="/safety"
        className={styles.lookup}
        role="search"
      >
        <input
          name="recording"
          aria-label="Call id"
          placeholder="Call id (from the call's review screen)"
          defaultValue={recording ?? ""}
        />
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
        >
          Open
        </button>
      </form>
      {recording && !recordingId ? (
        <Unavailable title="That call id" reason="It isn't a valid call id." />
      ) : null}
      {result && !result.ok ? (
        <Unavailable title="This call's marks" reason={result.error} />
      ) : null}
      {!recording ? (
        <Panel title="Open a call">
          <Empty
            icon={ShieldCheck}
            title="Choose a call to review its sensitive passages"
            text="Open a call from Calls and use its Safety link, or paste its id above."
            action={{ href: "/calls", label: "Go to Calls" }}
          />
        </Panel>
      ) : null}
      {data ? (
        <>
          <Panel
            title="Withheld now"
            sub={`${active.length} passage${active.length === 1 ? "" : "s"}`}
            action={{
              href: `/calls/${data.recordingId}`,
              label: "Open the call",
            }}
          >
            {active.length ? (
              <Table label="Withheld passages">
                <thead>
                  <tr>
                    <th scope="col">Segment</th>
                    <th scope="col">Category</th>
                    <th scope="col">Reference</th>
                    <th scope="col">Since</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {active.map((mark) => (
                    <tr key={mark.id}>
                      <th scope="row" className={styles.mono}>
                        {mark.segmentId}
                      </th>
                      <td>
                        <Badge tone="warn">
                          {categoryLabel(mark.category)}
                        </Badge>
                      </td>
                      <td>{mark.reason}</td>
                      <td>{when(mark.createdAt)}</td>
                      <td>
                        <ReleaseMark markId={mark.id} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Empty
                icon={ShieldCheck}
                title="Nothing is withheld in this call"
              />
            )}
          </Panel>
          <Panel title="Withhold passages">
            {data.revisions.length ? (
              <MarkSegments
                recordingId={data.recordingId}
                revisions={data.revisions.map((item) => item.revision)}
              />
            ) : (
              <Empty
                icon={ShieldCheck}
                title="This call has no transcript yet"
              />
            )}
          </Panel>
          <Panel title="History" sub={`${data.marks.length} records`}>
            {data.marks.length ? (
              <Table label="Mark history">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Change</th>
                    <th scope="col">Segment</th>
                    <th scope="col">Reference</th>
                    <th scope="col">By</th>
                  </tr>
                </thead>
                <tbody>
                  {data.marks.map((mark) => (
                    <tr key={mark.id}>
                      <td>{when(mark.createdAt)}</td>
                      <td>
                        {mark.action === "mark"
                          ? `Withheld · ${categoryLabel(mark.category)}`
                          : "Released"}
                      </td>
                      <td className={styles.mono}>{mark.segmentId}</td>
                      <td>{mark.reason}</td>
                      <td>
                        {mark.source === "generation" ? "Analysis" : "Operator"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className={kitStyles.muted} style={{ margin: 0, padding: 14 }}>
                No marks have been recorded for this call.
              </p>
            )}
          </Panel>
          <p className={kitStyles.muted}>
            <Link href={`/calls/${data.recordingId}`}>Back to the call</Link>
          </p>
        </>
      ) : null}
    </Page>
  );
}
