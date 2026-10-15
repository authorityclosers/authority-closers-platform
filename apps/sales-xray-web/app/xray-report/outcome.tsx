"use client";

import {
  ArrowRight,
  CalendarClock,
  CalendarDays,
  Check,
  CircleAlert,
  CircleCheck,
  FilePen,
  Hourglass,
  Info,
  Lightbulb,
  MessageCircleMore,
  ThumbsDown,
  ThumbsUp,
  Trophy,
  X,
  type LucideIcon,
} from "lucide-react";

import type { CSSProperties } from "react";

import { BIG_PICTURE } from "../report-copy";
import { useCallOutcome } from "../report-outcome-context";
import type { Line } from "../report-story-model";
import type { Select } from "../report-visuals/visuals";
import { MoneyBag } from "./icons";
import type { OutcomeKind, XrayView } from "./model";
import { formatMoney, LineWithClip } from "./overview";
import styles from "./xray.module.css";

type Scenario = {
  word: string;
  tone: string;
  icon: LucideIcon;
  status: string;
  valueLabel: string;
  dateLabel: string;
  datePill: string;
  dateTone: string;
  end: string;
  endState: string;
  endIcon: LucideIcon;
  /** The last stretch of the stage track: solid, or dashed while still open. */
  tail: "solid" | "dashed";
  reasons: string;
  objections: string;
};

/** Images 2, 4, 1 and 11 of the doc, one scenario each. */
const SCENARIOS: Record<OutcomeKind, Scenario> = {
  won: {
    word: "Won",
    tone: styles.green,
    icon: Trophy,
    status: "Deal Closed",
    valueLabel: "Closed Deal Value",
    dateLabel: "Closed Date",
    datePill: "Deal Successfully Closed",
    dateTone: styles.green,
    end: "Closed Won",
    endState: "Completed",
    endIcon: Trophy,
    tail: "solid",
    reasons: "Key Reasons for Winning",
    objections: "Objections Handled",
  },
  lost: {
    word: "Lost",
    tone: styles.red,
    icon: X,
    status: "Deal Closed (Lost)",
    valueLabel: "Lost Deal Value",
    dateLabel: "Closed-Lost Date",
    datePill: "Deal Closed as Lost",
    dateTone: styles.red,
    end: "Closed Lost",
    endState: "Completed",
    endIcon: X,
    tail: "solid",
    reasons: "Key Reasons for Loss",
    objections: "Key Objections Raised",
  },
  follow_up: {
    word: "Follow-up Set",
    tone: styles.blue,
    icon: CalendarClock,
    status: "In Progress",
    valueLabel: "Potential Deal Value",
    dateLabel: "Next Follow-up Date",
    datePill: "Follow-up Scheduled",
    dateTone: styles.purple,
    end: "Follow-up Set",
    endState: "Next Call Scheduled",
    endIcon: CalendarDays,
    tail: "dashed",
    reasons: "Key Reasons for Follow-up",
    objections: "Key Objections Raised",
  },
  decision_pending: {
    word: "Decision Pending",
    tone: styles.amber,
    icon: Hourglass,
    status: "Pending",
    valueLabel: "Potential Deal Value",
    dateLabel: "Expected Decision Date",
    datePill: "Awaiting Decision",
    dateTone: styles.purple,
    end: "Decision Pending",
    endState: "Awaiting Prospect’s Decision",
    endIcon: Hourglass,
    tail: "dashed",
    reasons: "Key Reasons for Decision Pending",
    objections: "Key Objections / Concerns",
  },
};

const TAIL_COLOUR: Record<OutcomeKind, string> = {
  won: "var(--xr-green-mark)",
  lost: "var(--xr-red-mark)",
  follow_up: "var(--xr-purple-mark)",
  decision_pending: "var(--xr-muted)",
};

function Checks({
  lines,
  tone,
  ranked = false,
  onSelect,
  title,
}: {
  lines: Array<Line & { handled?: boolean }>;
  tone: string;
  ranked?: boolean;
  onSelect?: Select;
  title: string;
}) {
  return (
    <ul className={`${styles.checks} ${tone}`}>
      {lines.map((line, index) => (
        <li key={`${index}-${line.text}`}>
          {ranked ? (
            <span className={styles.rank} aria-hidden="true">
              {index + 1}
            </span>
          ) : line.handled === false ? (
            // A concern the call left open is not a tick.
            <CircleAlert
              className={`${styles.checkMark} ${styles.amber}`}
              aria-label="Still open"
            />
          ) : (
            <CircleCheck className={styles.checkMark} aria-hidden="true" />
          )}
          <span>
            <LineWithClip line={line} title={title} onSelect={onSelect} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Suggested({ text }: { text: string }) {
  return (
    <div className={styles.suggested}>
      <Lightbulb aria-hidden="true" />
      <div>
        <div className={styles.suggestedTitle}>Suggested Next Action</div>
        <div className={styles.suggestedText}>{text}</div>
      </div>
      <ArrowRight aria-hidden="true" />
    </div>
  );
}

function formatDay(iso: string) {
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      }).format(date)
    : iso;
}

/** 3. Final Call Outcome (images 2, 4, 1 and 11). */
export function FinalOutcome({
  view,
  onSelect,
}: {
  view: XrayView;
  onSelect?: Select;
}) {
  const { state } = useCallOutcome();
  const record = state.status === "ready" ? state.record.value : null;
  const canRecord = state.status === "ready" && state.record.can_edit;
  // A person's record outranks the example and the analysis.
  const recordedKind: OutcomeKind | null = record
    ? record.outcome === "no_decision"
      ? "decision_pending"
      : record.outcome
    : null;
  const outcome = view.outcome;
  const kind = recordedKind ?? outcome.kind;
  const scenario = kind ? SCENARIOS[kind] : null;
  const value = record?.deal_value
    ? {
        amount: formatMoney(record.deal_value),
        note:
          kind === "won" || kind === "lost"
            ? "(Contract value)"
            : "(Entered by you)",
      }
    : outcome.value;
  const date =
    record?.follow_up_on && kind === "follow_up"
      ? formatDay(record.follow_up_on)
      : outcome.date;
  const detail =
    record?.lost_reason && kind === "lost"
      ? { text: record.lost_reason, sources: [] }
      : outcome.detail;
  const stages = outcome.stages;
  const Icon = scenario?.icon ?? Info;
  const EndIcon = scenario?.endIcon ?? Info;
  const tone = scenario?.tone ?? styles.neutral;
  const suggestedInSteps = kind === "lost" || outcome.nextSteps.length === 0;
  // Won and Lost only ever come from a person; the analysis' reading says so.
  const origin = view.illustrative
    ? null
    : record
      ? BIG_PICTURE.outcomeByPerson
      : outcome.origin === "call" && (kind || outcome.label)
        ? BIG_PICTURE.outcomeFromCall
        : null;
  return (
    <div
      className={styles.xr}
      data-xray-part="outcome"
      data-outcome={kind ?? "none"}
    >
      <div className={styles.outcomeTop}>
        <div
          className={`${styles.card} ${styles.tinted} ${styles.outcomeCard} ${tone}`}
        >
          <span className={`${styles.disc} ${styles.discLg}`}>
            <Icon />
          </span>
          <div className={styles.outcomeBody}>
            <span className={styles.outcomeLabel}>
              Deal Outcome
              {origin ? <span className={styles.origin}>{origin}</span> : null}
            </span>
            <span className={styles.outcomeHeadline}>
              <span className={styles.outcomeWord}>
                {scenario?.word ??
                  outcome.label ??
                  (canRecord ? "Not set yet" : "No outcome yet")}
              </span>
              {scenario ? (
                <span className={styles.pill}>{scenario.status}</span>
              ) : null}
            </span>
            {detail ? (
              <p className={styles.body}>
                <LineWithClip
                  line={detail}
                  title="Deal outcome"
                  onSelect={onSelect}
                />
              </p>
            ) : (
              <p className={styles.body}>
                {canRecord
                  ? "Set the outcome above when you know it. Won and Lost always come from you, never from the analysis."
                  : "The call does not settle the outcome."}
              </p>
            )}
          </div>
        </div>
        <div className={`${styles.card} ${styles.outcomeCard}`}>
          <span className={`${styles.disc} ${styles.discLg} ${styles.blue}`}>
            <MoneyBag />
          </span>
          <div className={styles.outcomeBody}>
            <span className={styles.outcomeLabel}>
              {scenario?.valueLabel ?? "Deal Value"}
            </span>
            <span className={styles.outcomeBig}>
              {value?.amount ?? (canRecord ? "Not set yet" : "Not recorded")}
            </span>
            <span className={styles.outcomeNote}>
              {value?.note ??
                (canRecord
                  ? "Add it with the pencil in Deal Outcome."
                  : "No deal value was recorded.")}
            </span>
          </div>
        </div>
        <div className={`${styles.card} ${styles.outcomeCard}`}>
          <span
            className={`${styles.disc} ${styles.discLg} ${
              kind === "won" || kind === "lost" ? styles.blue : styles.purple
            }`}
          >
            <CalendarDays />
          </span>
          <div className={styles.outcomeBody}>
            <span className={styles.outcomeLabel}>
              {scenario?.dateLabel ?? "Next Date"}
            </span>
            <span className={styles.outcomeBig}>{date ?? "No date yet"}</span>
            {scenario && date ? (
              <span
                className={`${styles.pill} ${styles.solid} ${scenario.dateTone}`}
              >
                {scenario.datePill}
              </span>
            ) : (
              <span className={styles.outcomeNote}>
                No date was agreed on the call.
              </span>
            )}
          </div>
        </div>
      </div>

      <section
        className={`${styles.card} ${styles.stages}`}
        aria-label="Sales process stage"
      >
        <h3 className={styles.cardTitle}>Sales Process Stage</h3>
        {stages.length ? (
          <ol
            className={styles.track}
            style={{ listStyle: "none", margin: "14px 0 0", padding: 0 }}
          >
            {stages.map((stage, index) => (
              <li key={`${index}-${stage}`} className={styles.step}>
                <span className={styles.stepDot}>
                  <Check aria-hidden="true" />
                </span>
                <span className={styles.stepName}>{stage}</span>
                <span className={styles.stepState}>Completed</span>
              </li>
            ))}
            {scenario && kind ? (
              <li
                className={`${styles.step} ${styles.stepEndItem} ${scenario.tail === "dashed" ? styles.stepDashed : ""} ${tone}`}
                style={{ "--step-tail": TAIL_COLOUR[kind] } as CSSProperties}
              >
                <span className={styles.stepEnd}>
                  <EndIcon aria-hidden="true" />
                </span>
                <span className={styles.stepName}>{scenario.end}</span>
                <span className={styles.stepState}>{scenario.endState}</span>
              </li>
            ) : null}
          </ol>
        ) : (
          <p className={styles.gap} style={{ marginTop: 8 }}>
            This report does not name the call&rsquo;s stages.
          </p>
        )}
      </section>

      <div className={styles.grid2}>
        <section className={`${styles.card} ${styles.listCard}`}>
          <span
            className={`${styles.disc} ${kind === "lost" ? styles.red : styles.green}`}
          >
            {kind === "lost" ? <ThumbsDown /> : <ThumbsUp />}
          </span>
          <div className={styles.blockText}>
            <h3 className={styles.cardTitle}>
              {scenario?.reasons ?? "Where the Deal Stands"}
            </h3>
            {outcome.reasons.length ? (
              <Checks
                lines={outcome.reasons}
                tone={kind === "lost" ? styles.red : styles.green}
                ranked={kind === "lost"}
                onSelect={onSelect}
                title="Reason"
              />
            ) : (
              <p className={styles.gap}>The call does not say why.</p>
            )}
          </div>
        </section>
        <section className={`${styles.card} ${styles.listCard}`}>
          <span className={`${styles.disc} ${styles.blue}`}>
            <MessageCircleMore />
          </span>
          <div className={styles.blockText}>
            <h3 className={styles.cardTitle}>
              {scenario?.objections ?? "Key Objections Raised"}
            </h3>
            {outcome.objections.length ? (
              <Checks
                lines={outcome.objections}
                tone={kind === "lost" ? styles.red : styles.green}
                onSelect={onSelect}
                title="Objection"
              />
            ) : (
              <p className={styles.gap}>No objection was raised on the call.</p>
            )}
          </div>
        </section>
        <section className={`${styles.card} ${styles.listCard}`}>
          <span className={`${styles.disc} ${styles.purple}`}>
            <CalendarDays />
          </span>
          <div className={styles.blockText}>
            <h3 className={styles.cardTitle}>Next Steps</h3>
            {outcome.nextSteps.length ? (
              <ol className={styles.steps}>
                {outcome.nextSteps.map((step, index) => (
                  <li key={`${index}-${step.text}`} className={styles.stepRow}>
                    <span className={styles.stepNo}>{index + 1}</span>
                    <span className={styles.stepText}>{step.text}</span>
                    {step.date ? (
                      <span className={styles.date}>{step.date}</span>
                    ) : (
                      <span />
                    )}
                    {step.owner ? (
                      <span
                        className={`${styles.owner} ${
                          step.owner === "you"
                            ? styles.ownerYou
                            : styles.ownerProspect
                        }`}
                      >
                        {step.owner === "you" ? "You" : "Prospect"}
                      </span>
                    ) : (
                      <span />
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <div className={styles.noAction}>
                <Info aria-hidden="true" />
                No further action agreed upon during this call.
              </div>
            )}
            {suggestedInSteps && outcome.suggested ? (
              <Suggested text={outcome.suggested} />
            ) : null}
          </div>
        </section>
        <section className={`${styles.card} ${styles.listCard}`}>
          <span className={`${styles.disc} ${styles.amber}`}>
            <FilePen />
          </span>
          <div className={styles.blockText}>
            <h3 className={styles.cardTitle}>Additional Notes</h3>
            {outcome.notes.length ? (
              <ul className={styles.dots}>
                {outcome.notes.map((note, index) => (
                  <li key={`${index}-${note.text}`}>
                    <LineWithClip
                      line={note}
                      title="Note"
                      onSelect={onSelect}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.gap}>Nothing else to note from this call.</p>
            )}
            {!suggestedInSteps && outcome.suggested ? (
              <Suggested text={outcome.suggested} />
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
