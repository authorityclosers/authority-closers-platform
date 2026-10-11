import { FlaskConical } from "lucide-react";
import { notFound } from "next/navigation";

import { clock, languageLabel } from "@/app/calls/call-data";
import { DEVANAGARI } from "@/app/calls/transcript-pane";
import { adminRead } from "@/app/lib/server-api";
import { AnswerTree } from "@/app/synthetic/answer-tree";
import {
  humanKey,
  normalizeSyntheticCall,
} from "@/app/synthetic/synthetic-data";
import styles from "@/app/synthetic/synthetic.module.css";
import { Badge, Page, PageHeader, Panel, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const CALL_ID = /^syn-[A-Za-z0-9-]{3,120}$/;
const PILLARS = [
  "the_big_picture",
  "how_the_call_played_out",
  "what_worked_and_what_didnt",
  "moments_that_mattered",
  "your_skills_on_this_call",
  "where_the_deal_stands",
];

export default async function SyntheticCallPage({
  params,
}: {
  params: Promise<{ callId: string }>;
}) {
  const { callId } = await params;
  if (!CALL_ID.test(callId)) notFound();
  const result = await adminRead(
    `/v1/admin/conversation/synthetic/${callId}`,
    normalizeSyntheticCall,
  );
  if (!result.ok)
    return (
      <Page>
        <PageHeader
          title={callId}
          back={{ href: "/synthetic", label: "Synthetic data" }}
        />
        <Unavailable title="This synthetic call" reason={result.error} />
      </Page>
    );
  const { call, lines, participants, answerKey, label } = result.data;
  const names = Object.fromEntries(
    participants.map((person) => [person.role, person.name]),
  );
  const report =
    answerKey && typeof answerKey.report === "object"
      ? (answerKey.report as Record<string, unknown>)
      : null;
  const rest = answerKey
    ? Object.fromEntries(
        Object.entries(answerKey).filter(
          ([key]) => !["report", "synthetic", "schema_version"].includes(key),
        ),
      )
    : null;
  return (
    <Page wide>
      <PageHeader
        title={call.callId}
        back={{ href: "/synthetic", label: "Synthetic data" }}
        context={[
          call.businessId,
          call.at?.slice(0, 10),
          languageLabel(call.language),
          clock(call.durationMs),
          call.outcome,
        ]}
        actions={<Badge tone="warn">Synthetic</Badge>}
      />
      <p className={styles.banner}>
        <FlaskConical size={16} aria-hidden="true" />
        {label}
      </p>
      <div className={styles.grid}>
        <Panel title="Transcript" sub={`${lines.length} lines`}>
          <ol className={styles.lines}>
            {lines.map((line) => (
              <li key={line.id} data-speaker={line.speaker}>
                <span>
                  <strong>
                    {names[line.speaker] ?? humanKey(line.speaker)}
                  </strong>
                  <small>{clock(line.startMs)}</small>
                </span>
                <span
                  data-script={DEVANAGARI.test(line.text) ? "deva" : undefined}
                >
                  {line.text}
                </span>
              </li>
            ))}
          </ol>
        </Panel>
        <Panel title="Answer key" sub="what a correct report would say">
          <div className={styles.key}>
            {report
              ? PILLARS.filter((key) => key in report).map((key, index) => (
                  <section key={key} aria-label={humanKey(key)}>
                    <h3>
                      {index + 1}. {humanKey(key)}
                    </h3>
                    <AnswerTree value={report[key]} />
                  </section>
                ))
              : null}
            {rest ? (
              <AnswerTree value={rest} />
            ) : (
              <p className={styles.none}>This call has no answer key.</p>
            )}
          </div>
        </Panel>
      </div>
    </Page>
  );
}
