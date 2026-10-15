"use client";

import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  CircleCheck,
  CircleHelp,
  CircleMinus,
  CirclePlay,
  Clock3,
  Lightbulb,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { PlayChip, type Select } from "../report-visuals/visuals";
import {
  QuoteMark,
  StatusAlert,
  StatusCheck,
  StatusGauge,
  StatusMinus,
  StatusQuestion,
} from "./icons";
import {
  clock,
  isScored,
  type Pointer,
  type PointerStatus,
  type UnscoredStatus,
} from "./model";
import { AiDraft, Illustrative, LineWithClip } from "./overview";
import styles from "./xray.module.css";

const STATUS: Record<
  PointerStatus,
  { label: string; tone: string; icon: ReactNode }
> = {
  excellent: { label: "Excellent", tone: styles.green, icon: <StatusCheck /> },
  good: { label: "Good", tone: styles.green, icon: <StatusCheck /> },
  average: { label: "Average", tone: styles.amber, icon: <StatusGauge /> },
  needs_improvement: {
    label: "Needs Improvement",
    tone: styles.red,
    icon: <StatusAlert />,
  },
  not_observed: { label: "Not observed", tone: styles.amber, icon: <Clock3 /> },
  not_applicable: {
    label: "Not applicable",
    tone: styles.blue,
    icon: <StatusMinus />,
  },
  insufficient_evidence: {
    label: "Insufficient evidence",
    tone: styles.purple,
    icon: <StatusQuestion />,
  },
};

const UNSCORED: Array<{
  status: UnscoredStatus | "evaluated";
  label: string;
  text: string;
  tone: string;
  icon: ReactNode;
}> = [
  {
    status: "evaluated",
    label: "Evaluated",
    text: "Assessed with score and detailed feedback.",
    tone: styles.green,
    icon: <CircleCheck />,
  },
  {
    status: "not_observed",
    label: "Not observed",
    text: "This topic did not come up during the call.",
    tone: styles.amber,
    icon: <Clock3 />,
  },
  {
    status: "not_applicable",
    label: "Not applicable",
    text: "Not relevant for this type or stage of call.",
    tone: styles.blue,
    icon: <CircleMinus />,
  },
  {
    status: "insufficient_evidence",
    label: "Insufficient evidence",
    text: "Some conversation, but not enough to judge reliably.",
    tone: styles.purple,
    icon: <CircleHelp />,
  },
];

type Filter =
  | "all"
  | "excellent"
  | "good"
  | "average"
  | "needs_improvement"
  | "evaluated"
  | UnscoredStatus;

const FILTERS: Array<[Filter, string]> = [
  ["all", "All"],
  ["excellent", "Excellent"],
  ["good", "Good"],
  ["average", "Average"],
  ["needs_improvement", "Needs improvement"],
];

function matches(pointer: Pointer, filter: Filter) {
  if (filter === "all") return true;
  if (filter === "evaluated") return isScored(pointer.status);
  return pointer.status === filter;
}

/** Evaluated pointers out of all of them, for the part's head (image6). */
export function PointerProgress({ pointers }: { pointers: Pointer[] }) {
  const done = pointers.filter((pointer) => isScored(pointer.status)).length;
  const total = pointers.length;
  return (
    <div className={styles.progress}>
      <strong>
        {done} / {total}
      </strong>
      <span
        className={styles.progressTrack}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label="Pointers evaluated"
      >
        <span
          className={styles.progressFill}
          style={{ width: `${total ? (done / total) * 100 : 0}%` }}
        />
      </span>
      <span>Pointers evaluated</span>
    </div>
  );
}

function StatusChip({ status }: { status: PointerStatus | null }) {
  if (!status)
    return (
      <span className={`${styles.status} ${styles.neutral}`}>
        <Clock3 aria-hidden="true" />
        Not scored yet
      </span>
    );
  const item = STATUS[status];
  return (
    <span className={`${styles.status} ${item.tone}`}>
      <span aria-hidden="true" style={{ display: "contents" }}>
        {item.icon}
      </span>
      {item.label}
    </span>
  );
}

function Detail({
  pointer,
  onSelect,
  illustrative,
}: {
  pointer: Pointer;
  onSelect?: Select;
  illustrative: boolean;
}) {
  if (!isScored(pointer.status)) {
    const item = pointer.status
      ? UNSCORED.find((row) => row.status === pointer.status)
      : null;
    return (
      <div className={styles.detail}>
        <div className={`${styles.card} ${styles.block}`}>
          <span className={`${styles.disc} ${item?.tone ?? styles.neutral}`}>
            {item?.icon ?? <Clock3 />}
          </span>
          <div className={styles.blockText}>
            <h4 className={styles.blockTitle}>
              {item ? item.label : "Not scored yet"}
            </h4>
            <p className={styles.body}>
              {item
                ? `${item.text} No score is given for this pointer.`
                : "This call was analysed before pointer scores existed. Its next analysis scores this pointer."}
            </p>
          </div>
        </div>
        {pointer.related.length ? (
          <div className={`${styles.card} ${styles.block}`}>
            <span className={`${styles.disc} ${styles.purple}`}>
              <BookOpen />
            </span>
            <div className={styles.blockText}>
              <h4 className={styles.blockTitle}>What the analysis saw</h4>
              <ul className={styles.bullets}>
                {pointer.related.map((line, index) => (
                  <li key={`${index}-${line.text}`}>
                    <LineWithClip
                      line={line}
                      title={pointer.name}
                      onSelect={onSelect}
                    />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className={styles.detail}>
      <div className={styles.detailTop}>
        <div className={`${styles.card} ${styles.block}`}>
          <span className={`${styles.disc} ${styles.blue}`}>
            <CircleCheck />
          </span>
          <div className={styles.blockText}>
            <h4 className={styles.blockTitle}>What Happened?</h4>
            <p className={styles.body}>
              {pointer.whatHappened ?? "Not stated in this report."}
            </p>
          </div>
        </div>
        <div
          className={`${styles.card} ${styles.block} ${styles.why} ${styles.red}`}
        >
          <span className={styles.disc}>
            <TriangleAlert />
          </span>
          <div className={styles.blockText}>
            <h4 className={`${styles.blockTitle} ${styles.toneTitle}`}>
              Why It Matters?
            </h4>
            <p className={styles.body}>
              {pointer.whyItMatters ?? "Not stated in this report."}
            </p>
          </div>
        </div>
      </div>
      <div className={`${styles.card} ${styles.block}`}>
        <span className={`${styles.disc} ${styles.purple}`}>
          <BookOpen />
        </span>
        <div className={styles.blockText}>
          <h4 className={styles.blockTitle}>Evidence from the Call</h4>
          {pointer.evidence.length ? (
            <div className={styles.quotes}>
              {pointer.evidence.map((quote, index) => (
                <figure
                  key={`${quote.at_ms}-${index}`}
                  className={`${styles.quote} ${quote.who === "you" ? styles.green : styles.blue}`}
                  style={{ margin: 0 }}
                >
                  <QuoteMark className={styles.quoteMark} />
                  <div>
                    <figcaption className={styles.quoteWho}>
                      {quote.name ??
                        (quote.who === "you"
                          ? "You"
                          : quote.who === "prospect"
                            ? "Prospect"
                            : "Speaker")}{" "}
                      {quote.source ? (
                        <PlayChip
                          source={quote.source}
                          title={pointer.name}
                          onSelect={onSelect}
                        />
                      ) : (
                        `(${clock(quote.at_ms)})`
                      )}
                    </figcaption>
                    <blockquote
                      className={styles.quoteText}
                      style={{ margin: "2px 0 0" }}
                    >
                      &ldquo;{quote.text}&rdquo;
                    </blockquote>
                  </div>
                </figure>
              ))}
            </div>
          ) : (
            <p className={styles.gap}>
              No quote from the call for this pointer.
            </p>
          )}
        </div>
      </div>
      <div
        className={`${styles.card} ${styles.block} ${styles.improve} ${styles.purple}`}
      >
        <span className={styles.disc}>
          <Lightbulb />
        </span>
        <div className={styles.improveRow}>
          <div className={styles.blockText}>
            <h4 className={`${styles.blockTitle} ${styles.toneTitle}`}>
              How to Improve?
            </h4>
            {pointer.howToImprove.length ? (
              <ul className={styles.bullets}>
                {pointer.howToImprove.map((tip) => (
                  <li key={tip}>{tip}</li>
                ))}
              </ul>
            ) : (
              <p className={styles.gap}>Nothing to change here.</p>
            )}
          </div>
          {pointer.training ? (
            <div className={styles.trainingWrap}>
              <button
                type="button"
                className={styles.training}
                onClick={() => {
                  if (pointer.training?.href) {
                    window.open(pointer.training.href, "_blank", "noopener");
                    return;
                  }
                  notify({
                    id: "xray-training-video",
                    tone: "info",
                    title: "Training videos are on the way",
                    message: illustrative
                      ? "This is the illustrative example; its videos are not linked yet."
                      : "This lesson isn't linked to a video yet.",
                    timeout: 5000,
                  });
                }}
              >
                <CirclePlay aria-hidden="true" />
                Watch Training Video
                <ArrowRight aria-hidden="true" />
              </button>
              <span className={styles.trainingName}>
                {pointer.training.title}
                {pointer.training.minutes
                  ? ` (${pointer.training.minutes} min)`
                  : ""}
              </span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** 2. Detailed Call Analysis (images 6, 8, 9 and 10). */
export function CallAnalysis({
  pointers,
  illustrative,
  aiDraft = false,
  onSelect,
}: {
  pointers: Pointer[];
  illustrative: boolean;
  aiDraft?: boolean;
  onSelect?: Select;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const counts = useMemo(() => {
    const count = (f: Filter) => pointers.filter((p) => matches(p, f)).length;
    return Object.fromEntries(
      (
        [
          "all",
          "excellent",
          "good",
          "average",
          "needs_improvement",
          "evaluated",
          "not_observed",
          "not_applicable",
          "insufficient_evidence",
        ] as Filter[]
      ).map((f) => [f, count(f)]),
    ) as Record<Filter, number>;
  }, [pointers]);
  const shown = pointers.filter((pointer) => matches(pointer, filter));
  const anyEvaluated = pointers.some((pointer) => pointer.status !== null);
  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div className={styles.xr} data-xray-part="analysis">
      {anyEvaluated ? (
        <div className={styles.counts}>
          {UNSCORED.map((item) => (
            <button
              key={item.status}
              type="button"
              className={`${styles.countCard} ${item.tone}`}
              aria-pressed={filter === item.status}
              onClick={() =>
                setFilter(filter === item.status ? "all" : item.status)
              }
            >
              <span className={styles.disc}>{item.icon}</span>
              <span className={styles.countTop}>
                <span className={styles.countNumber}>
                  {counts[item.status]}
                </span>
                <span className={styles.countLabel}>{item.label}</span>
              </span>
              <span className={styles.countText}>{item.text}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className={`${styles.card} ${styles.empty}`}>
          This call was analysed before pointer scores existed, so none of the
          27 is scored yet. Open any pointer to see what the analysis saw.
        </p>
      )}
      <div className={styles.filters} role="group" aria-label="Show pointers">
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={styles.filter}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {label}
            <span>{counts[value]}</span>
          </button>
        ))}
        {illustrative ? <Illustrative /> : aiDraft ? <AiDraft /> : null}
      </div>
      <div className={`${styles.card} ${styles.table}`}>
        <div className={styles.tableHead} aria-hidden="true">
          <span>#</span>
          <span>Sales Conversation Pointer</span>
          <span>What This Evaluates</span>
          <span>Status</span>
          <span>Score</span>
          <span />
        </div>
        {shown.length ? (
          <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {shown.map((pointer) => {
              const isOpen = open.has(pointer.id);
              const tone = pointer.status
                ? STATUS[pointer.status].tone
                : styles.neutral;
              return (
                <li
                  key={pointer.id}
                  className={styles.row}
                  data-open={isOpen ? "" : undefined}
                  data-pointer={pointer.id}
                >
                  <button
                    type="button"
                    className={styles.rowButton}
                    aria-expanded={isOpen}
                    aria-controls={`xray-pointer-${pointer.id}`}
                    aria-label={`${pointer.number}. ${pointer.name}: ${
                      pointer.status
                        ? STATUS[pointer.status].label
                        : "not evaluated yet"
                    }${pointer.score !== null ? `, ${pointer.score} out of 100` : ""}. ${
                      isOpen ? "Hide details" : "View more"
                    }`}
                    onClick={() => toggle(pointer.id)}
                  >
                    <span
                      className={`${styles.number} ${isScored(pointer.status) ? tone : styles.neutral}`}
                    >
                      {pointer.number}
                    </span>
                    <span className={styles.name}>{pointer.name}</span>
                    <span className={styles.evaluates}>
                      {pointer.evaluates}
                    </span>
                    <StatusChip status={pointer.status} />
                    {pointer.score !== null ? (
                      <span className={`${styles.points} ${tone}`}>
                        <strong>{pointer.score}</strong>
                        <span>/ 100</span>
                      </span>
                    ) : (
                      <span className={styles.noScore}>No score</span>
                    )}
                    <ChevronDown
                      className={styles.chevron}
                      aria-hidden="true"
                    />
                  </button>
                  {isOpen ? (
                    <div id={`xray-pointer-${pointer.id}`}>
                      <Detail
                        pointer={pointer}
                        onSelect={onSelect}
                        illustrative={illustrative}
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className={styles.empty}>No pointers match this filter.</p>
        )}
      </div>
    </div>
  );
}
