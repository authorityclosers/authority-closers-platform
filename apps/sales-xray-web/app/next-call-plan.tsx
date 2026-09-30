"use client";

import { CheckSquare, Square } from "lucide-react";
import { useMemo } from "react";

import { promiseId, togglePromiseDone, usePromisesDone } from "./call-signals";
import { Emote } from "./emote";
import { formatClock } from "./lightbox/time";
import { OUTCOME } from "./overview-hook";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { RichText } from "./report-entities";
import {
  Card,
  Clip,
  Empty,
  KitSection,
  Locked,
  Note,
  Script,
  Tag,
  useReportPeople,
} from "./report-kit";
import { promises } from "./sales-signals";
import styles from "./next-call-plan.module.css";

const EMPTY_TRANSCRIPT: Transcript = {
  source_sha256: "",
  revision: "",
  timebase_id: "1ms",
  duration_ms: 0,
  segments: [],
};

/**
 * The next-call plan, in the order people act on feedback: one clear move
 * for the next call, what to keep, what to change first (with words to try),
 * how the call closed, the promises made, and what to handle with care.
 * Everything shown comes from this report; missing parts say so plainly.
 */
export function NextCallPlan({
  report,
  onSelectEvidence,
  onUnlock,
  callId = null,
  transcript = EMPTY_TRANSCRIPT,
}: {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
  callId?: string | null;
  transcript?: Transcript;
}) {
  const overview = report.overview;
  const focus = overview?.next_call_focus ?? null;
  const outcome = overview?.outcome ?? null;
  const practice = overview?.practice ?? null;
  const people = useReportPeople(callId, transcript);
  const done = usePromisesDone(callId);
  const promised = useMemo(
    () => (people.roles ? promises(transcript, people.roles) : []),
    // roles comes from saved profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, people.roles?.seller, people.roles?.prospect],
  );
  const hidden = (
    section: keyof NonNullable<SalesReport["preview"]>["sections"],
  ) => report.preview?.sections[section].hidden_count ?? 0;

  // The focus improvement leads; the rest follow in report order.
  const first = focus ? focus.improvement_index : 0;
  const changes = report.improvements
    .map((finding, index) => ({ finding, index }))
    .sort((a, b) => Number(b.index === first) - Number(a.index === first));
  const detailOf = (index: number) =>
    overview?.improvement_details.find((d) => d.finding_index === index);
  const whyKept = (index: number) =>
    overview?.strength_details.find((d) => d.finding_index === index)
      ?.why_it_matters;

  const clips = (evidence: ReportEvidence[], title: string, max = 1) =>
    evidence
      .slice(0, max)
      .map((item) => (
        <Clip
          key={`${item.segment_id}-${item.start_ms}`}
          evidence={item}
          title={title}
          onPlay={onSelectEvidence}
          person={people.speakerOf(item)}
        />
      ));

  const findingCard = (
    finding: Finding,
    index: number,
    tone: "closing",
    emote: "chequered-flag",
    label: string,
  ) => (
    <Card key={index} tone={tone} index={index}>
      <Tag tone={tone} emote={emote}>
        {label}
      </Tag>
      <h4>
        <RichText text={finding.title} />
      </h4>
      <p>
        <RichText text={finding.explanation} />
      </p>
      {clips(finding.evidence, finding.title)}
    </Card>
  );

  return (
    <div className={styles.plan} aria-label="Next-call plan">
      {outcome ? (
        <aside className={styles.outcome} aria-label="Call outcome">
          <Emote name={OUTCOME[outcome.kind].emote} size={22} />
          <span className={styles.outcomeText}>
            <small>Where the call ended · {OUTCOME[outcome.kind].label}</small>
            <RichText text={outcome.text} />
          </span>
          {outcome.evidence[0] ? (
            <button
              type="button"
              className={styles.outcomePlay}
              aria-label={`Listen to call outcome at ${formatClock(outcome.evidence[0].start_ms)}`}
              onClick={() =>
                onSelectEvidence(outcome.evidence[0], "Call outcome")
              }
            >
              ▶ {formatClock(outcome.evidence[0].start_ms)}
            </button>
          ) : null}
        </aside>
      ) : null}
      <section
        className={styles.move}
        aria-label="Your one move for the next call"
      >
        <span className={styles.moveEmote}>
          <Emote name="bullseye" size={30} />
        </span>
        <div className={styles.moveBody}>
          <small>Your one move for the next call</small>
          {focus ? (
            <>
              <p className={styles.moveText}>
                <RichText text={focus.behavior} />
              </p>
              <p className={styles.target}>
                <b>You’ll know it worked when</b>{" "}
                <RichText text={focus.target} />
              </p>
            </>
          ) : changes[0] ? (
            <p className={styles.moveText}>
              <RichText text={changes[0].finding.title} />
            </p>
          ) : (
            <p className={styles.moveText}>
              This report did not set a next-call focus.
            </p>
          )}
        </div>
        {practice ? (
          <div className={styles.practice}>
            <span className={styles.practiceHead}>
              <Emote name="flexed-biceps" size={18} />
              Practise it once before the call
            </span>
            <p>
              <RichText text={practice.instructions} />
            </p>
            <p className={styles.doneWhen}>
              <b>Done when</b> <RichText text={practice.success_condition} />
            </p>
          </div>
        ) : null}
      </section>

      <KitSection
        emote="clapping-hands"
        tone="strength"
        title="Keep doing"
        hint="What worked on this call. Do it again."
        count={report.strengths.length}
        index={1}
      >
        {report.strengths.length ? (
          <div className={styles.grid}>
            {report.strengths.map((finding, index) => (
              <Card key={index} tone="strength" index={index}>
                <h4>
                  <RichText text={finding.title} />
                </h4>
                <p>
                  <RichText text={finding.explanation} />
                </p>
                {whyKept(index) ? (
                  <Note label="Why it works:">
                    <RichText text={whyKept(index) ?? ""} />
                  </Note>
                ) : null}
                {clips(finding.evidence, finding.title)}
              </Card>
            ))}
          </div>
        ) : (
          <Empty>No strength was recorded for this call.</Empty>
        )}
        <Locked
          count={hidden("strengths")}
          noun="strengths"
          onUnlock={onUnlock}
        />
      </KitSection>

      <KitSection
        emote="light-bulb"
        tone="change"
        title="Change first"
        hint="One change at a time. Start with the first."
        count={report.improvements.length}
        index={2}
      >
        {changes.length ? (
          <div className={styles.changes}>
            {changes.map(({ finding, index }, order) => {
              const detail = detailOf(index);
              const said = detail?.what_happened.evidence.length
                ? detail.what_happened.evidence
                : finding.evidence;
              return (
                <Card
                  key={index}
                  tone="change"
                  index={order}
                  className={styles.change}
                >
                  <Tag tone="change" emote={order ? "pushpin" : "light-bulb"}>
                    {order ? "Also worth changing" : "Change first"}
                  </Tag>
                  <h4>
                    <RichText text={finding.title} />
                  </h4>
                  <div className={styles.changeBody}>
                    <div className={styles.changeSide}>
                      <Note label="What happened:">
                        <RichText
                          text={
                            detail?.what_happened.text ?? finding.explanation
                          }
                        />
                      </Note>
                      {clips(said, finding.title)}
                    </div>
                    <div className={styles.changeSide}>
                      {detail?.why_it_matters ? (
                        <Note label="Why it matters:">
                          <RichText text={detail.why_it_matters} />
                        </Note>
                      ) : null}
                      {detail?.replacement_behavior ? (
                        <Script
                          label="Try this instead"
                          text={detail.replacement_behavior}
                        />
                      ) : null}
                      {detail?.business_impact.status === "insufficient_data" &&
                      detail.business_impact.missing_inputs.length ? (
                        <p className={styles.impact}>
                          To size what this cost, the report needs:{" "}
                          {detail.business_impact.missing_inputs.join(", ")}.
                        </p>
                      ) : null}
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        ) : (
          <Empty emote="sparkles">No change was suggested for this call.</Empty>
        )}
        <Locked
          count={hidden("improvements")}
          noun="changes"
          onUnlock={onUnlock}
        />
      </KitSection>

      {report.closing_analysis.length || hidden("closing_analysis") ? (
        <KitSection
          emote="chequered-flag"
          tone="closing"
          title="How the call closed"
          hint="The ask, the commitment and the next step."
          count={report.closing_analysis.length}
          index={3}
        >
          <div className={styles.grid}>
            {report.closing_analysis.map((finding, index) =>
              findingCard(
                finding,
                index,
                "closing",
                "chequered-flag",
                "Closing",
              ),
            )}
          </div>
          <Locked
            count={hidden("closing_analysis")}
            noun="closing notes"
            onUnlock={onUnlock}
          />
        </KitSection>
      ) : null}

      <KitSection
        emote="handshake"
        tone="info"
        title="Promises you made"
        hint="Keep them before the next call. Found by words, so listen to check."
        count={people.roles ? promised.length : undefined}
        index={4}
      >
        {!people.roles ? (
          <Empty emote="busts-in-silhouette">
            Mark who is the salesperson on the call map to list the promises.
          </Empty>
        ) : promised.length ? (
          <ul className={styles.promises}>
            {promised.map((item) => {
              const id = promiseId(item);
              const ticked = done.has(id);
              return (
                <li key={id} data-done={ticked ? "" : undefined}>
                  <button
                    type="button"
                    className={styles.tick}
                    aria-pressed={ticked}
                    disabled={!callId}
                    onClick={() => callId && togglePromiseDone(callId, id)}
                    aria-label={ticked ? "Mark as not done" : "Mark as done"}
                  >
                    {ticked ? <CheckSquare size={17} /> : <Square size={17} />}
                  </button>
                  <Clip
                    evidence={{
                      segment_id: item.segment.id,
                      quote: item.text,
                      start_ms: item.segment.start_ms,
                      end_ms: item.segment.end_ms,
                    }}
                    title="Promise"
                    onPlay={onSelectEvidence}
                    person={people.speakerOf({
                      segment_id: item.segment.id,
                      quote: item.text,
                      start_ms: item.segment.start_ms,
                      end_ms: item.segment.end_ms,
                    })}
                  />
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty emote="memo">
            No promise was found in the salesperson’s words.
          </Empty>
        )}
      </KitSection>

      {overview?.ethics_notes.length || hidden("ethics_notes") ? (
        <KitSection
          emote="raised-hand"
          tone="hypothesis"
          title="Handle with care"
          hint="Points to keep the conversation fair and honest."
          index={5}
        >
          <div className={styles.grid}>
            {overview?.ethics_notes.map((note, index) => (
              <Card key={index} tone="hypothesis" index={index}>
                <p>
                  <RichText text={note.text} />
                </p>
                {clips(note.evidence, "Handle with care")}
              </Card>
            ))}
          </div>
          <Locked
            count={hidden("ethics_notes")}
            noun="notes"
            onUnlock={onUnlock}
          />
        </KitSection>
      ) : null}
    </div>
  );
}
