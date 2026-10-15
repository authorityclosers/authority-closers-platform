"use client";

import {
  AudioLines,
  ChartPie,
  CircleCheck,
  CircleHelp,
  FileText,
  Info,
  MessagesSquare,
  Pencil,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";

import {
  parseHumanCallOutcome,
  type CallOutcomeKind,
  type HumanCallOutcome,
} from "../report-call-outcome-contract";
import { GUEST, OUTCOME_RECORD } from "../report-copy";
import { UnlockButton } from "../report-sections/shared";
import { useCallOutcome } from "../report-outcome-context";
import type { Line } from "../report-story-model";
import { PlayChip, type Select } from "../report-visuals/visuals";
import { MoneyBag, TargetArrow } from "./icons";
import { scoreBand, type OutcomeKind, type Stat, type XrayView } from "./model";
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

/**
 * Deal Outcome and Deal Value (image7): one tap records Won or Decision
 * Pending; Lost asks why, Follow-up asks the date. A person's record only:
 * nothing here is guessed, and nothing shows as saved until it reads back.
 */
function DealOutcomeBar({ example }: { example: OutcomeKind | null }) {
  const { state, save } = useCallOutcome();
  const id = useId();
  const [ask, setAsk] = useState<"lost" | "follow_up" | "value" | null>(null);
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
          ? OUTCOME_RECORD.needReason
          : next.outcome === "follow_up" && !next.follow_up_on
            ? OUTCOME_RECORD.needDate
            : OUTCOME_RECORD.checkValues,
      );
      return;
    }
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      await save(parsed);
      setAsk(null);
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
    if (kind === "lost") {
      setReason(record?.lost_reason ?? "");
      setAsk("lost");
      return;
    }
    if (kind === "follow_up") {
      setDate(record?.follow_up_on ?? "");
      setAsk("follow_up");
      return;
    }
    setAsk(null);
    void commit({ outcome: kind, lost_reason: null, follow_up_on: null });
  }

  function saveValue() {
    if (!record) {
      setError("Set the outcome first, then add the deal value.");
      return;
    }
    void commit(
      {
        outcome: record.outcome,
        lost_reason: record.lost_reason,
        follow_up_on: record.follow_up_on,
      },
      amount.trim()
        ? {
            amount: amount.trim(),
            currency_code: currency.trim().toUpperCase(),
          }
        : null,
    );
  }

  return (
    <section
      className={`${styles.card} ${styles.dealBar}`}
      aria-label="Deal outcome"
      aria-busy={saving}
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
              aria-pressed={current === kind}
              disabled={!canEdit || saving}
              onClick={() => choose(kind)}
            >
              {current === kind ? (
                <CircleCheck className={styles.chipCheck} aria-hidden="true" />
              ) : null}
              {label}
            </button>
          ))}
        </div>
      )}
      <span className={styles.dealDivider} aria-hidden="true" />
      <div className={styles.dealValue}>
        <span className={styles.square}>
          <MoneyBag />
        </span>
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
            onClick={() => {
              setAmount(record?.deal_value?.amount ?? "");
              setCurrency(record?.deal_value?.currency_code ?? "INR");
              setError(null);
              setAsk(ask === "value" ? null : "value");
            }}
          >
            <Pencil size={18} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {ask === "lost" ? (
        <form
          className={styles.dealForm}
          onSubmit={(event) => {
            event.preventDefault();
            void commit({
              outcome: "lost",
              lost_reason: reason,
              follow_up_on: null,
            });
          }}
        >
          <label htmlFor={`${id}-reason`}>
            {OUTCOME_RECORD.lostReason}
            <input
              id={`${id}-reason`}
              maxLength={1000}
              value={reason}
              disabled={saving}
              onChange={(event) => setReason(event.target.value)}
              autoFocus
            />
          </label>
          <button type="submit" className={styles.save} disabled={saving}>
            {saving ? OUTCOME_RECORD.saving : OUTCOME_RECORD.save}
          </button>
          <button
            type="button"
            className={styles.cancel}
            onClick={() => setAsk(null)}
          >
            Cancel
          </button>
        </form>
      ) : ask === "follow_up" ? (
        <form
          className={styles.dealForm}
          onSubmit={(event) => {
            event.preventDefault();
            void commit({
              outcome: "follow_up",
              lost_reason: null,
              follow_up_on: date,
            });
          }}
        >
          <label htmlFor={`${id}-date`}>
            {OUTCOME_RECORD.followUpDate}
            <input
              id={`${id}-date`}
              type="date"
              value={date}
              disabled={saving}
              onChange={(event) => setDate(event.target.value)}
              autoFocus
            />
          </label>
          <button type="submit" className={styles.save} disabled={saving}>
            {saving ? OUTCOME_RECORD.saving : OUTCOME_RECORD.save}
          </button>
          <button
            type="button"
            className={styles.cancel}
            onClick={() => setAsk(null)}
          >
            Cancel
          </button>
        </form>
      ) : ask === "value" ? (
        <form
          className={styles.dealForm}
          onSubmit={(event) => {
            event.preventDefault();
            saveValue();
          }}
        >
          <label htmlFor={`${id}-amount`}>
            {OUTCOME_RECORD.amount}
            <input
              id={`${id}-amount`}
              inputMode="decimal"
              value={amount}
              disabled={saving}
              onChange={(event) => setAmount(event.target.value)}
              autoFocus
            />
          </label>
          <label htmlFor={`${id}-currency`}>
            {OUTCOME_RECORD.currency}
            <input
              id={`${id}-currency`}
              maxLength={3}
              size={4}
              placeholder={OUTCOME_RECORD.currencyExample}
              value={currency}
              disabled={saving}
              onChange={(event) => setCurrency(event.target.value)}
            />
          </label>
          <button type="submit" className={styles.save} disabled={saving}>
            {saving ? OUTCOME_RECORD.saving : OUTCOME_RECORD.save}
          </button>
          <button
            type="button"
            className={styles.cancel}
            onClick={() => setAsk(null)}
          >
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
  const { summary, score, stats, strength, improvement } = view.overview;
  const band = score ? scoreBand(score.value) : null;
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
        aria-label="Overall score"
      >
        <div
          className={`${styles.score} ${band ? BAND_TONE[band] : styles.neutral}`}
        >
          <span className={styles.eyebrow}>
            Overall Score {view.illustrative ? <Illustrative /> : null}
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
                Not scored yet
              </span>
              <p className={styles.body}>
                The score appears when this call&rsquo;s pointers are evaluated.
              </p>
            </>
          )}
        </div>
        <hr className={styles.rule} />
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
