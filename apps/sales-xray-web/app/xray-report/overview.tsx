"use client";

import {
  AudioLines,
  ChartPie,
  Check,
  CircleCheck,
  CircleHelp,
  FileText,
  Info,
  MessagesSquare,
  Pencil,
  TrendingUp,
  Trophy,
  X,
} from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";

import {
  parseHumanCallOutcome,
  type CallOutcomeKind,
  type HumanCallOutcome,
} from "../report-call-outcome-contract";
import { GUEST, OUTCOME_RECORD } from "../report-copy";
import { useReportLook } from "../report-settings";
import { UnlockButton } from "../report-sections/shared";
import { useCallOutcome } from "../report-outcome-context";
import type { Line } from "../report-story-model";
import { PlayChip, type Select } from "../report-visuals/visuals";
import { brain4Highlights, type Brain4View } from "./brain4";
import { MoneyBag, TargetArrow } from "./icons";
import {
  scoreBand,
  scoringNote,
  type OutcomeKind,
  type Stat,
  type XrayView,
} from "./model";
import styles from "./xray.module.css";

export const BAND_TONE = {
  excellent: styles.green,
  good: styles.green,
  average: styles.amber,
  needs_improvement: styles.red,
} as const;

export function Illustrative() {
  return <span className={styles.illustrative}>Illustrative example</span>;
}

/** Scores the analysis made, before Dipak reviews them (owner, 16 Oct). */
export function AiDraft() {
  return (
    <span className={`${styles.illustrative} ${styles.aiDraft}`}>
      AI draft &middot; not reviewed by Dipak
    </span>
  );
}

/** A calibrated one-pass score (owner, 21 Oct 2026): a beta, never official. */
export function BetaScore({ version }: { version: string }) {
  return (
    <span
      className={`${styles.illustrative} ${styles.beta}`}
      title={`Calibrated one-pass score${version ? ` (${version})` : ""}`}
    >
      Beta
    </span>
  );
}

/** Words with their first source as a small play chip, when it has one. */
export function LineWithClip({
  line,
  title,
  onSelect,
}: {
  line: Line;
  title: string;
  onSelect?: Select;
}) {
  return (
    <>
      {line.text}{" "}
      {line.sources[0] ? (
        <PlayChip source={line.sources[0]} title={title} onSelect={onSelect} />
      ) : null}
    </>
  );
}

function StatCard({
  icon,
  tone,
  label,
  stat,
  missing,
}: {
  icon: ReactNode;
  tone: string;
  label: string;
  stat: Stat | null;
  missing: string;
}) {
  return (
    <div className={`${styles.card} ${styles.stat}`}>
      <span className={`${styles.disc} ${tone}`}>{icon}</span>
      <div className={styles.statText}>
        <span className={styles.statLabel}>{label}</span>
        {stat ? (
          <>
            <span className={styles.statValue}>{stat.value}</span>
            <span className={styles.statSub}>{stat.sub}</span>
          </>
        ) : (
          <span className={styles.statEmpty}>{missing}</span>
        )}
      </div>
    </div>
  );
}

const CHOICES: Array<[CallOutcomeKind, OutcomeKind, string]> = [
  ["won", "won", "Won"],
  ["lost", "lost", "Lost"],
  ["follow_up", "follow_up", "Follow-up Set"],
  ["no_decision", "decision_pending", "Decision Pending"],
];

export function formatMoney(value: { amount: string; currency_code: string }) {
  const amount = Number(value.amount);
  if (!Number.isFinite(amount)) return `${value.amount} ${value.currency_code}`;
  try {
    return new Intl.NumberFormat(
      value.currency_code === "INR" ? "en-IN" : "en",
      {
        style: "currency",
        currency: value.currency_code,
        maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
      },
    ).format(amount);
  } catch {
    return `${value.amount} ${value.currency_code}`;
  }
}

const CURRENCIES = ["INR", "USD", "AED", "EUR", "GBP", "SGD", "AUD", "CAD"];

const AMOUNT_HELP =
  "That doesn’t look like an amount. Use numbers only, like 125000.";

/** "12,50,000", "₹ 1250000" or "12.5" as the decimal string the API accepts. */
export function plainAmount(input: string): string | null {
  const digits = input.replace(/[\s,₹$€£]/g, "");
  if (!digits) return null;
  if (!/^\d{1,16}(?:\.\d{1,4})?$/.test(digits)) return null;
  const [whole, fraction] = digits.split(".");
  const trimmed = whole.replace(/^0+(?=\d)/, "");
  return fraction ? `${trimmed}.${fraction}` : trimmed;
}

function isoDay(offset: number) {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return [
    day.getFullYear(),
    String(day.getMonth() + 1).padStart(2, "0"),
    String(day.getDate()).padStart(2, "0"),
  ].join("-");
}

function shortDay(iso: string) {
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        timeZone: "UTC",
      }).format(date)
    : iso;
}

/**
 * Deal Outcome and Deal Value (image7): one tap records Won or Decision
 * Pending; Lost asks why, Follow-up asks the date. A person's record only:
 * nothing here is guessed, and nothing shows as saved until it reads back.
 */
function DealOutcomeBar({ example }: { example: OutcomeKind | null }) {
  const { state, save } = useCallOutcome();
  const id = useId();
  const [ask, setAsk] = useState<"lost" | "follow_up" | null>(null);
  const [editingValue, setEditingValue] = useState(false);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);

  if (state.status === "off" || state.status === "not_owner") return null;
  const ready = state.status === "ready";
  const record = ready ? state.record.value : null;
  const canEdit = ready && state.record.can_edit;
  const current: CallOutcomeKind | null =
    record?.outcome ??
    (example
      ? (CHOICES.find(([, kind]) => kind === example)?.[0] ?? null)
      : null);
  const typed = plainAmount(amount);
  const preview =
    typed !== null
      ? formatMoney({ amount: typed, currency_code: currency })
      : null;

  async function commit(
    next: Omit<HumanCallOutcome, "deal_value">,
    value = record?.deal_value ?? null,
  ) {
    if (pending.current || !canEdit) return;
    let parsed: HumanCallOutcome;
    try {
      parsed = parseHumanCallOutcome({ ...next, deal_value: value });
    } catch {
      setError(
        next.outcome === "lost" && !next.lost_reason?.trim()
          ? "Add a short reason, then save."
          : next.outcome === "follow_up" && !next.follow_up_on
            ? "Pick the follow-up date, then save."
            : AMOUNT_HELP,
      );
      return;
    }
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      await save(parsed);
      setAsk(null);
      setEditingValue(false);
    } catch {
      setError(OUTCOME_RECORD.saveNotConfirmed);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  function choose(kind: CallOutcomeKind) {
    if (!canEdit || saving) return;
    setError(null);
    setEditingValue(false);
    if (kind === "lost") {
      setReason(record?.lost_reason ?? "");
      setAsk(ask === "lost" ? null : "lost");
      return;
    }
    if (kind === "follow_up") {
      setDate(record?.follow_up_on ?? "");
      setAsk(ask === "follow_up" ? null : "follow_up");
      return;
    }
    setAsk(null);
    void commit({ outcome: kind, lost_reason: null, follow_up_on: null });
  }

  function startValue() {
    setAsk(null);
    setError(null);
    setAmount(record?.deal_value?.amount ?? "");
    setCurrency(record?.deal_value?.currency_code ?? "INR");
    setEditingValue(true);
  }

  function saveValue() {
    if (!record) return;
    if (amount.trim() && typed === null) {
      setError(AMOUNT_HELP);
      return;
    }
    void commit(
      {
        outcome: record.outcome,
        lost_reason: record.lost_reason,
        follow_up_on: record.follow_up_on,
      },
      typed !== null ? { amount: typed, currency_code: currency } : null,
    );
  }

  const cancel = () => {
    setAsk(null);
    setEditingValue(false);
    setError(null);
  };

  return (
    <section
      className={`${styles.card} ${styles.dealBar}`}
      aria-label="Deal outcome"
      aria-busy={saving}
      onKeyDown={(event) => {
        if (event.key === "Escape" && (ask || editingValue)) cancel();
      }}
    >
      <span className={styles.square}>
        <TargetArrow />
      </span>
      <span className={styles.dealLabel}>Deal Outcome</span>
      {state.status === "loading" ? (
        <span className={styles.chipSkeleton} aria-hidden="true" />
      ) : state.status === "unavailable" ? (
        <p className={styles.gap} role="status">
          {OUTCOME_RECORD.readFailed}
        </p>
      ) : (
        <div className={styles.chips} role="group" aria-label="Deal outcome">
          {CHOICES.map(([kind, , label]) => (
            <button
              key={kind}
              type="button"
              className={styles.chip}
              data-outcome-choice={kind}
              aria-pressed={current === kind}
              aria-expanded={
                kind === "lost" || kind === "follow_up"
                  ? ask === kind
                  : undefined
              }
              disabled={!canEdit || saving}
              onClick={() => choose(kind)}
            >
              {current === kind ? (
                <CircleCheck className={styles.chipCheck} aria-hidden="true" />
              ) : null}
              {label}
              {current === kind &&
              kind === "follow_up" &&
              record?.follow_up_on ? (
                <span className={styles.chipNote}>
                  {shortDay(record.follow_up_on)}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      )}
      <span className={styles.dealDivider} aria-hidden="true" />
      <div className={styles.dealValue}>
        <span className={styles.square}>
          <MoneyBag />
        </span>
        {editingValue ? (
          <form
            className={styles.valueEditor}
            onSubmit={(event) => {
              event.preventDefault();
              saveValue();
            }}
          >
            <label className={styles.srOnly} htmlFor={`${id}-currency`}>
              {OUTCOME_RECORD.currency}
            </label>
            <select
              id={`${id}-currency`}
              className={styles.currency}
              value={currency}
              disabled={saving}
              onChange={(event) => setCurrency(event.target.value)}
            >
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
            <label className={styles.srOnly} htmlFor={`${id}-amount`}>
              Deal value amount
            </label>
            <span className={styles.amountBox}>
              <input
                id={`${id}-amount`}
                className={styles.amount}
                inputMode="decimal"
                autoComplete="off"
                placeholder="e.g. 12,50,000"
                value={amount}
                disabled={saving}
                onChange={(event) => setAmount(event.target.value)}
                autoFocus
              />
              <span className={styles.amountPreview} aria-live="polite">
                {preview ?? " "}
              </span>
            </span>
            <button
              type="submit"
              className={styles.iconSave}
              disabled={saving}
              aria-label={saving ? OUTCOME_RECORD.saving : "Save deal value"}
              title="Save"
            >
              <Check size={18} aria-hidden="true" />
            </button>
            <button
              type="button"
              className={styles.iconCancel}
              onClick={cancel}
              aria-label="Cancel"
              title="Cancel"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </form>
        ) : (
          <>
            <div className={styles.dealValueText}>
              <span>Deal Value</span>
              <strong>
                {record?.deal_value
                  ? formatMoney(record.deal_value)
                  : OUTCOME_RECORD.notSet}
              </strong>
            </div>
            {canEdit ? (
              <button
                type="button"
                className={styles.editButton}
                aria-label="Edit deal value"
                title={record ? "Edit deal value" : "Pick the outcome first"}
                disabled={!record || saving}
                onClick={startValue}
              >
                <Pencil size={18} aria-hidden="true" />
              </button>
            ) : null}
          </>
        )}
      </div>
      {canEdit && !record && !example && !ask ? (
        <p className={styles.dealNote}>
          Pick the outcome first, then add the deal value.
        </p>
      ) : null}
      {ask === "lost" ? (
        <form
          className={styles.askPanel}
          onSubmit={(event) => {
            event.preventDefault();
            void commit({
              outcome: "lost",
              lost_reason: reason,
              follow_up_on: null,
            });
          }}
        >
          <label htmlFor={`${id}-reason`} className={styles.askLabel}>
            {OUTCOME_RECORD.lostReason}
          </label>
          <input
            id={`${id}-reason`}
            className={styles.askInput}
            maxLength={1000}
            placeholder="e.g. Chose a cheaper option"
            value={reason}
            disabled={saving}
            onChange={(event) => setReason(event.target.value)}
            autoFocus
          />
          <button
            type="submit"
            className={styles.save}
            disabled={saving || !reason.trim()}
          >
            {saving ? OUTCOME_RECORD.saving : "Mark as Lost"}
          </button>
          <button type="button" className={styles.cancel} onClick={cancel}>
            Cancel
          </button>
        </form>
      ) : ask === "follow_up" ? (
        <form
          className={styles.askPanel}
          onSubmit={(event) => {
            event.preventDefault();
            void commit({
              outcome: "follow_up",
              lost_reason: null,
              follow_up_on: date,
            });
          }}
        >
          <label htmlFor={`${id}-date`} className={styles.askLabel}>
            When is the follow-up?
          </label>
          <div
            className={styles.quickDays}
            role="group"
            aria-label="Quick dates"
          >
            {(
              [
                ["Tomorrow", 1],
                ["In 3 days", 3],
                ["Next week", 7],
              ] as const
            ).map(([label, offset]) => (
              <button
                key={label}
                type="button"
                className={styles.quickDay}
                aria-pressed={date === isoDay(offset)}
                disabled={saving}
                onClick={() => setDate(isoDay(offset))}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            id={`${id}-date`}
            className={styles.askInput}
            type="date"
            value={date}
            disabled={saving}
            onChange={(event) => setDate(event.target.value)}
          />
          <button
            type="submit"
            className={styles.save}
            disabled={saving || !date}
          >
            {saving ? OUTCOME_RECORD.saving : "Set follow-up"}
          </button>
          <button type="button" className={styles.cancel} onClick={cancel}>
            Cancel
          </button>
        </form>
      ) : null}
      {error ? (
        <p className={styles.dealError} role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

/** 1. Overview & Score (image7). */
export function OverviewScore({
  view,
  onSelect,
}: {
  view: XrayView;
  onSelect?: Select;
}) {
  const { summary, score, stats } = view.overview;
  const scoring = scoringNote(view.scoring);
  const band = score ? scoreBand(score.value) : null;
  // A report settings version may hide scores; version 1 shows them.
  const { scores, scoring: rubric } = useReportLook();
  // Brain 4.0 scoring (owner, 22 Oct 2026): its 18 skills replace the 27 pointers'
  // score and highlights wherever the call has a Brain 4.0 read.
  const coach =
    rubric === "brain4_beta" && view.brain4 && !view.illustrative
      ? view.brain4
      : null;
  const { strength, improvement } = coach
    ? brain4Highlights(coach)
    : view.overview;
  return (
    <div className={styles.xr} data-xray-part="overview">
      <section
        className={`${styles.card} ${styles.summary}`}
        aria-label="Call summary"
      >
        <span className={styles.square}>
          <FileText />
        </span>
        <div className={styles.summaryText}>
          <h3 className={styles.cardTitle}>Call Summary</h3>
          <p className={styles.body}>
            {summary ? (
              <LineWithClip
                line={summary}
                title="Call summary"
                onSelect={onSelect}
              />
            ) : (
              <span className={styles.muted}>This report has no summary.</span>
            )}
          </p>
        </div>
      </section>

      <section
        className={`${styles.card} ${styles.scoreCard}`}
        aria-label={scores ? "Overall score" : "Call statistics"}
      >
        {scores && coach ? (
          <>
            <CoachScore view={coach} />
            <hr className={styles.rule} />
          </>
        ) : scores ? (
          <>
            <div
              className={`${styles.score} ${band ? BAND_TONE[band] : styles.neutral}`}
            >
              <span className={styles.eyebrow}>
                Overall Score{" "}
                {view.illustrative ? (
                  <Illustrative />
                ) : view.aiDraft && score ? (
                  <>
                    <AiDraft />
                    {view.beta ? (
                      <BetaScore version={view.beta.version} />
                    ) : null}
                  </>
                ) : null}
              </span>
              {score ? (
                <>
                  <span className={styles.scoreLine}>
                    <span className={styles.scoreValue}>{score.value}</span>
                    <span className={styles.scoreOf}>/100</span>
                  </span>
                  <span className={`${styles.pill} ${styles.scoreBadge}`}>
                    {score.label}
                  </span>
                  <p className={styles.body}>{score.line}</p>
                </>
              ) : (
                <>
                  <span className={styles.scoreLine}>
                    <span className={styles.scoreEmpty}>&ndash;</span>
                    <span className={styles.scoreOf}>/100</span>
                  </span>
                  <span className={`${styles.pill} ${styles.scoreBadge}`}>
                    {scoring.pending ? scoring.title : "Not scored yet"}
                  </span>
                  <p
                    className={styles.body}
                    role={scoring.pending ? "status" : undefined}
                  >
                    {scoring.pending
                      ? scoring.body
                      : "The score appears when this call’s pointers are evaluated."}
                  </p>
                </>
              )}
            </div>
            <hr className={styles.rule} />
          </>
        ) : null}
        <div className={styles.statsHead}>
          <h3 className={styles.cardTitle}>Call Statistics</h3>
          <button
            type="button"
            className={styles.iconButton}
            aria-label="About these numbers"
          >
            <Info aria-hidden="true" />
            <span className={styles.tip} role="tooltip">
              Counted from the recording and its transcript, not guessed: how
              long the call ran, who talked how much, questions each side asked,
              and the longest stretch you spoke without a break.
            </span>
          </button>
        </div>
        <div className={styles.stats}>
          <StatCard
            icon={<ChartPie />}
            tone={styles.blue}
            label="Call Duration"
            stat={stats.duration}
            missing="Length not known"
          />
          <StatCard
            icon={<MessagesSquare />}
            tone={styles.green}
            label="Talk Share"
            stat={stats.talk}
            missing="Mark who is who on the call map"
          />
          <StatCard
            icon={<CircleHelp />}
            tone={styles.amber}
            label="Questions Asked"
            stat={stats.questions}
            missing="Mark who is who on the call map"
          />
          <StatCard
            icon={<AudioLines />}
            tone={styles.purple}
            label="Longest Turn"
            stat={stats.longest}
            missing="Mark who is who on the call map"
          />
        </div>
        <div className={styles.highlights}>
          <div
            className={`${styles.card} ${styles.tinted} ${styles.highlight} ${styles.green}`}
          >
            <span className={styles.disc}>
              <Trophy />
            </span>
            <div>
              <h4 className={styles.highlightTitle}>Biggest Strength</h4>
              <p className={styles.body}>
                {strength ? (
                  <LineWithClip
                    line={strength}
                    title="Biggest strength"
                    onSelect={onSelect}
                  />
                ) : (
                  <span className={styles.muted}>
                    No clear strength in this report.
                  </span>
                )}
              </p>
            </div>
          </div>
          <div
            className={`${styles.card} ${styles.tinted} ${styles.highlight} ${styles.amber}`}
          >
            <span className={styles.disc}>
              <TrendingUp />
            </span>
            <div>
              <h4 className={styles.highlightTitle}>
                Biggest Improvement Area
              </h4>
              <p className={styles.body}>
                {improvement ? (
                  <LineWithClip
                    line={improvement}
                    title="Biggest improvement area"
                    onSelect={onSelect}
                  />
                ) : (
                  <span className={styles.muted}>
                    No clear improvement area in this report.
                  </span>
                )}
              </p>
            </div>
          </div>
        </div>
      </section>

      <DealOutcomeBar example={view.illustrative ? view.outcome.kind : null} />

      {view.guest ? (
        <section
          className={`${styles.card} ${styles.guest}`}
          aria-label={GUEST.fullReport}
        >
          <p className={styles.body}>
            {GUEST.fullReport}: every pointer, the full outcome and your
            coaching.
          </p>
          <UnlockButton className={styles.save}>{GUEST.unlock}</UnlockButton>
        </section>
      ) : null}
    </div>
  );
}

const AREA: Record<string, string> = {
  how_you_talk: "How You Talk",
  understanding_the_buyer: "Understanding the Buyer",
  moving_the_sale_forward: "Moving the Sale Forward",
};

/** The AI coaching score: each area's plain mean of its rated skills (1-5); no total. */
function CoachScore({ view }: { view: Brain4View }) {
  return (
    <div
      className={`${styles.score} ${styles.neutral}`}
      data-xray-coach-score=""
    >
      <span className={styles.eyebrow}>AI Coaching Score</span>
      {view.rated ? (
        <ul className={styles.bullets}>
          {view.categories.map((category) => (
            <li key={category.id}>
              <strong>
                {category.score !== null
                  ? `${category.score.toFixed(1)} / 5`
                  : "–"}
              </strong>{" "}
              {AREA[category.id] ?? category.label}
              <span className={styles.muted}>
                {" "}
                · {category.rated} of {category.of} skills rated
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className={styles.body}>
        {view.rated
          ? `Rated by AI on the coaching lead's Brain 4.0 rubric: ${view.rated} of 18 skills.`
          : "This call was too short, or had too little conversation, to rate the 18 skills."}
      </p>
    </div>
  );
}
