"use client";

import {
  CheckSquare,
  Dumbbell,
  Flag,
  ListChecks,
  Play,
  ShieldCheck,
  Square,
  Target,
  Users,
} from "lucide-react";
import { useMemo } from "react";

import { promiseId, togglePromiseDone, usePromisesDone } from "./call-signals";
import { formatClock } from "./lightbox/time";
import { OUTCOME } from "./overview-hook";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { RichText } from "./report-entities";
import {
  Card,
  Clip,
  Empty,
  IconBadge,
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
 * The next-call plan as numbered steps, in the order people act on feedback:
 * one move to carry into the next call, what to keep, what to change first
 * (with words to try), how the call closed, the promises to keep, and what
 * to handle with care. Everything comes from this report; gaps say so.
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
  const clip = (evidence: ReportEvidence | undefined, title: string) =>
    evidence ? (
      <Clip
        evidence={evidence}
        title={title}
        onPlay={onSelectEvidence}
        person={people.speakerOf(evidence)}
      />
    ) : null;
  const outcomeStyle = outcome ? OUTCOME[outcome.kind] : null;
  let step = 0;

  return (
    <div className={styles.plan} aria-label="Next-call plan">
      {outcome && outcomeStyle ? (
        <aside className={styles.outcome} aria-label="Call outcome">
          <IconBadge
            icon={outcomeStyle.Icon}
            tone={
              outcomeStyle.tone === "bad"
                ? "objection"
                : outcomeStyle.tone === "warn"
                  ? "change"
                  : "teal"
            }
            size={30}
          />
          <p className={styles.outcomeText}>
            <b>Where the call ended: {outcomeStyle.label}.</b>{" "}
            <span>
              <RichText text={outcome.text} />
            </span>
          </p>
          {outcome.evidence[0] ? (
            <button
              type="button"
              className={styles.outcomePlay}
              aria-label={`Listen to call outcome at ${formatClock(outcome.evidence[0].start_ms)}`}
              onClick={() =>
                onSelectEvidence(outcome.evidence[0], "Call outcome")
              }
            >
              <Play size={10} fill="currentColor" aria-hidden="true" />
              {formatClock(outcome.evidence[0].start_ms)}
            </button>
          ) : null}
        </aside>
      ) : null}

      <section
        className={styles.move}
        aria-label="Your one move for the next call"
      >
        <div className={styles.moveMain}>
          <span className={styles.moveLabel}>
            <Target size={14} aria-hidden="true" />
            Your one move for the next call
          </span>
          <p className={styles.moveText}>
            {focus ? (
              <RichText text={focus.behavior} />
            ) : changes[0] ? (
              <RichText text={changes[0].finding.title} />
            ) : (
              "This report did not set a next-call focus."
            )}
          </p>
          {focus ? (
            <p className={styles.target}>
              <b>You’ll know it worked when:</b>{" "}
              <span>
                <RichText text={focus.target} />
              </span>
            </p>
          ) : null}
        </div>
        {practice ? (
          <div className={styles.practice}>
            <span className={styles.practiceHead}>
              <Dumbbell size={14} aria-hidden="true" />
              Practise it once before the call
            </span>
            <p>
              <RichText text={practice.instructions} />
            </p>
            <p className={styles.doneWhen}>
              <b>Done when:</b>{" "}
              <span>
                <RichText text={practice.success_condition} />
              </span>
            </p>
          </div>
        ) : null}
      </section>

      <KitSection
        step={++step}
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
                  <Note label="Why it works:" muted>
                    <RichText text={whyKept(index) ?? ""} />
                  </Note>
                ) : null}
                {clip(finding.evidence[0], finding.title)}
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
        step={++step}
        tone="change"
        title="Change first"
        hint="One change at a time. Start at the top."
        count={report.improvements.length}
        index={2}
      >
        {changes.length ? (
          <div className={styles.changes}>
            {changes.map(({ finding, index }, order) => {
              const detail = detailOf(index);
              const said =
                detail?.what_happened.evidence[0] ?? finding.evidence[0];
              const missing =
                detail?.business_impact.status === "insufficient_data"
                  ? detail.business_impact.missing_inputs
                  : [];
              return (
                <Card key={index} tone="change" index={order}>
                  <div className={styles.changeHead}>
                    <Tag tone="change">
                      {order ? "Also worth changing" : "Change first"}
                    </Tag>
                    <h4>
                      <RichText text={finding.title} />
                    </h4>
                  </div>
                  <div className={styles.changeBody}>
                    <div className={styles.side}>
                      <Note label="What happened:">
                        <RichText
                          text={
                            detail?.what_happened.text ?? finding.explanation
                          }
                        />
                      </Note>
                      {clip(said, finding.title)}
                    </div>
                    <div className={styles.side}>
                      {detail?.replacement_behavior ? (
                        <Script
                          label="Try this instead"
                          text={detail.replacement_behavior}
                        />
                      ) : null}
                      {detail?.why_it_matters ? (
                        <Note label="Why it matters:" muted>
                          <RichText text={detail.why_it_matters} />
                        </Note>
                      ) : null}
                    </div>
                  </div>
                  {missing.length ? (
                    <p className={styles.impact}>
                      We can’t tell what this cost yet. We would need:{" "}
                      {missing.join(", ")}.
                    </p>
                  ) : null}
                </Card>
              );
            })}
          </div>
        ) : (
          <Empty>No change was suggested for this call.</Empty>
        )}
        <Locked
          count={hidden("improvements")}
          noun="changes"
          onUnlock={onUnlock}
        />
      </KitSection>

      {report.closing_analysis.length || hidden("closing_analysis") ? (
        <KitSection
          step={++step}
          tone="closing"
          title="How the call closed"
          hint="How the next step was asked for and agreed."
          count={report.closing_analysis.length}
          index={3}
        >
          <div className={styles.grid}>
            {report.closing_analysis.map((finding, index) => (
              <Card key={index} tone="closing" index={index}>
                <Tag tone="closing" icon={Flag}>
                  Closing
                </Tag>
                <h4>
                  <RichText text={finding.title} />
                </h4>
                <p>
                  <RichText text={finding.explanation} />
                </p>
                {clip(finding.evidence[0], finding.title)}
              </Card>
            ))}
          </div>
          <Locked
            count={hidden("closing_analysis")}
            noun="closing notes"
            onUnlock={onUnlock}
          />
        </KitSection>
      ) : null}

      <KitSection
        step={++step}
        tone="info"
        title="Keep your promises"
        hint="Things you said you would do. Tick them off before the next call."
        count={people.roles ? promised.length : undefined}
        index={4}
      >
        {!people.roles ? (
          <Empty icon={Users}>
            Mark who the salesperson is on the call map to list the promises.
          </Empty>
        ) : promised.length ? (
          <ul className={styles.promises}>
            {promised.map((item) => {
              const id = promiseId(item);
              const ticked = done.has(id);
              const evidence = {
                segment_id: item.segment.id,
                quote: item.text,
                start_ms: item.segment.start_ms,
                end_ms: item.segment.end_ms,
              };
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
                    evidence={evidence}
                    title="Promise"
                    onPlay={onSelectEvidence}
                    person={people.speakerOf(evidence)}
                  />
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty icon={ListChecks}>
            No promise was found in the salesperson’s words.
          </Empty>
        )}
      </KitSection>

      {overview?.ethics_notes.length || hidden("ethics_notes") ? (
        <KitSection
          icon={ShieldCheck}
          tone="hypothesis"
          title="Handle with care"
          hint="Keep the conversation fair and honest."
          index={5}
        >
          <div className={styles.grid}>
            {overview?.ethics_notes.map((note, index) => (
              <Card key={index} tone="hypothesis" index={index}>
                <p>
                  <RichText text={note.text} />
                </p>
                {clip(note.evidence[0], "Handle with care")}
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
