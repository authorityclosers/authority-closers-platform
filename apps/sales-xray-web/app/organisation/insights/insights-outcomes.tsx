"use client";

import { useEffect, useState } from "react";

import { readRevenue } from "../../dashboard/revenue-client";
import { Button } from "../../ui/kit";
import {
  count,
  dateLabel,
  OUTCOMES,
  percent,
  rupees,
  type Insights,
  type OutcomeKey,
} from "./insights-data";
import styles from "./outcomes.module.css";

/**
 * Below this many analysed calls Insights makes no claims: one call is not a
 * trend (Dipak's walk, ph1-22, 1 Nov 2026: "Wins held steady" and 100% from
 * one call).
 */
export const MIN_CALLS = 10;

/** This month's Won leads, from the Lead Desk: a win is a deal, not a call. */
export type MonthWins = { deals: number; amount: number };

function useMonthWins(live: boolean): MonthWins | null {
  const [wins, setWins] = useState<MonthWins | null>(null);
  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    readRevenue("team", controller.signal).then(
      (revenue) => setWins({ deals: revenue.deals, amount: revenue.won }),
      () => {
        // No Lead Desk here: the story keeps to its calls.
      },
    );
    return () => controller.abort();
  }, [live]);
  return wins;
}

/** The endings that count as an agreed next step (the ring's three). */
const FORWARD: ReadonlySet<OutcomeKey> = new Set([
  "won",
  "booked",
  "follow_up",
]);

type EndingRow = { key: OutcomeKey; label: string; value: number | null };

/**
 * How every call ended, like a phone's storage bar (owner bug #78, 29 Oct
 * 2026: "something else instead of bars"): one strip split by outcome, and a
 * legend list under it with each count and share, grouped into the endings
 * that agreed a next step and the rest. Each row opens its calls; the colour
 * always sits beside its name, so nothing is colour alone.
 */
function EveryEnding({
  groups,
  calls,
  missing,
  few = false,
  onCalls,
}: {
  groups: { key: string; label: string; rows: EndingRow[] }[];
  calls: number | null;
  missing: boolean;
  /** Too few calls for shares or a most common ending (MIN_CALLS). */
  few?: boolean;
  onCalls: (outcome?: OutcomeKey) => void;
}) {
  const rows = groups.flatMap((group) => group.rows);
  const known = rows.reduce((sum, row) => sum + (row.value ?? 0), 0);
  const [first, second] = [...rows].sort(
    (a, b) => (b.value ?? -1) - (a.value ?? -1),
  );
  // A tie has no single most common ending.
  const top = !few && first && first.value !== second?.value ? first : null;
  const share = (value: number | null) =>
    few ? "" : value === null || !calls ? "—" : percent(value / calls);
  return (
    <section className={styles.card} aria-label="Every call outcome">
      <h2>
        {top && top.value
          ? `${top.label} was the most common ending`
          : "How every call ended"}
      </h2>
      <p className={styles.caption}>
        {calls === null ? "—" : count(calls)} analysed calls · tap an ending to
        see its calls
      </p>
      {known > 0 ? (
        <div
          className={styles.mix}
          role="img"
          aria-label={rows
            .map(
              (row) =>
                `${row.label}: ${row.value === null ? "unknown" : count(row.value)}`,
            )
            .join(", ")}
        >
          {rows.map((row) =>
            row.value ? (
              <i
                key={row.key}
                data-outcome={row.key}
                style={{ flexGrow: row.value }}
              />
            ) : null,
          )}
        </div>
      ) : null}
      <ul className={styles.endings} aria-label="Calls by outcome">
        {groups.map((group) => (
          <li key={group.key} className={styles.endingGroup}>
            <p className={styles.endingHead}>
              <span>{group.label}</span>
              <b>
                {group.rows.some((row) => row.value === null)
                  ? "—"
                  : count(
                      group.rows.reduce(
                        (sum, row) => sum + (row.value ?? 0),
                        0,
                      ),
                    )}
              </b>
            </p>
            <ul>
              {group.rows.map((row) => (
                <li key={row.key}>
                  <button type="button" onClick={() => onCalls(row.key)}>
                    <i data-outcome={row.key} aria-hidden="true" />
                    <span className={styles.endingName}>{row.label}</span>
                    <b>{row.value === null ? "—" : count(row.value)}</b>
                    <small>{share(row.value)}</small>
                  </button>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {missing ? (
        <p className={styles.caption}>— Outcome count unavailable</p>
      ) : null}
    </section>
  );
}

/** Call outcomes are nested sets, never successive stages of unique leads. */
export function OutcomeStory({
  data,
  onCalls,
  wins: given,
}: {
  data: Insights;
  onCalls: (outcome?: OutcomeKey) => void;
  /** This month's Won leads; read from the Lead Desk when not given. */
  wins?: MonthWins | null;
}) {
  const { totals, previous, coverage } = data;
  // Off under test, as the shell's own reads are (pages count their reads).
  const read = useMonthWins(
    given === undefined && !data.synthetic && process.env.NODE_ENV !== "test",
  );
  const wins = given === undefined ? read : given;
  const few = coverage.calls && totals.calls < MIN_CALLS;
  const share =
    !few && coverage.nextStep && coverage.calls && totals.calls > 0
      ? totals.nextStep / totals.calls
      : null;
  const diff =
    previous && coverage.previousWon && coverage.won
      ? totals.won - previous.won
      : null;
  const headline = few
    ? `Not enough calls yet (${count(totals.calls)} of ${MIN_CALLS})`
    : diff === null
      ? "How your calls ended"
      : diff === 0
        ? "Wins held steady this period"
        : `${count(Math.abs(diff))} ${diff > 0 ? "more" : "fewer"} won calls this period`;
  const outcomes = OUTCOMES.map(({ key, label }) => ({
    key,
    label,
    value: data.outcomes.find((row) => row.outcome === key)?.calls ?? null,
  })).sort((a, b) => (b.value ?? -1) - (a.value ?? -1));
  const complete =
    !few &&
    coverage.calls &&
    coverage.nextStep &&
    coverage.won &&
    totals.calls >= totals.nextStep &&
    totals.nextStep >= totals.won;
  const nextHeight =
    complete && totals.calls ? (94 * totals.nextStep) / totals.calls : 0;
  const wonHeight =
    complete && totals.calls ? (94 * totals.won) / totals.calls : 0;
  const other = complete ? totals.calls - totals.nextStep : null;
  const missing = outcomes.some((row) => row.value === null);
  return (
    <>
      <section className={styles.story} aria-label="The sales story">
        <p className={styles.eyebrow}>The sales story</p>
        <h2>{headline}</h2>
        <div className={styles.storyNumbers}>
          {wins ? (
            <strong>
              {count(wins.deals)}
              <small>
                {wins.deals === 1 ? "lead won" : "leads won"} this month
              </small>
            </strong>
          ) : (
            <strong>
              {coverage.won && !few ? count(totals.won) : "—"}
              <small>won calls</small>
            </strong>
          )}
          <p>
            {wins && wins.amount > 0 ? (
              <>
                {rupees(wins.amount)} won this month
                <br />
              </>
            ) : null}
            {few
              ? null
              : previous && coverage.previousWon
                ? `Previous period: ${count(previous.won)} won calls`
                : "Previous period unavailable"}
            {few ? null : <br />}
            {coverage.calls
              ? `${count(totals.calls)} analysed ${totals.calls === 1 ? "call" : "calls"}`
              : "Call count unavailable"}
            {few ? null : (
              <>
                {" "}
                ·{" "}
                {percent(
                  coverage.won && coverage.calls && totals.calls
                    ? totals.won / totals.calls
                    : null,
                )}{" "}
                won
              </>
            )}
          </p>
        </div>
        <p className={styles.caption}>
          {data.window.from && data.window.to
            ? `${dateLabel(data.window.from)} – ${dateLabel(data.window.to)}`
            : "Period dates unavailable"}{" "}
          · One outcome per call
        </p>
      </section>
      <div className={styles.grid}>
        <section className={styles.card} aria-label="Next steps and outcomes">
          <h2>
            {few
              ? "Not enough calls yet"
              : share === null
                ? "Next-step share unavailable"
                : `${percent(share)} of calls agreed a next step`}
          </h2>
          <div className={styles.ringBody}>
            <button
              className={styles.ring}
              type="button"
              onClick={() => onCalls()}
              aria-label={`${coverage.nextStep ? count(totals.nextStep) : "Unknown"} of ${coverage.calls ? count(totals.calls) : "unknown"} analysed calls agreed a next step. View calls.`}
            >
              <svg viewBox="0 0 120 120" aria-hidden="true">
                <circle className={styles.track} cx="60" cy="60" r="50" />
                <circle
                  className={styles.share}
                  cx="60"
                  cy="60"
                  r="50"
                  pathLength="100"
                  strokeDasharray={`${share === null ? 0 : Math.max(0, Math.min(100, share * 100))} 100`}
                />
              </svg>
              <span>
                <b>{percent(share)}</b>
                <small>
                  {coverage.nextStep ? count(totals.nextStep) : "—"} calls
                </small>
              </span>
            </button>
            <div className={styles.key}>
              {OUTCOMES.slice(0, 3).map((row) => (
                <button
                  type="button"
                  key={row.key}
                  onClick={() => onCalls(row.key)}
                >
                  <span>{row.label}</span>
                  <b>
                    {(() => {
                      const value = data.outcomes.find(
                        (item) => item.outcome === row.key,
                      )?.calls;
                      return value == null ? "—" : count(value);
                    })()}
                  </b>
                </button>
              ))}
              <p>
                <span>Other endings</span>
                <b>{other === null ? "—" : count(other)}</b>
              </p>
            </div>
          </div>
          <p className={styles.caption}>
            Won, meeting booked or follow-up set · Of{" "}
            {coverage.calls ? count(totals.calls) : "—"} analysed calls
          </p>
        </section>
        <section className={styles.card} aria-label="Counted call funnel">
          <h2>Where calls move forward</h2>
          <p className={styles.caption}>
            Nested call outcomes · Same count scale
          </p>
          {complete ? (
            <svg
              className={styles.funnel}
              viewBox="0 0 330 170"
              role="img"
              aria-label={`${count(totals.calls)} analysed calls; ${count(totals.nextStep)} agreed a next step, including ${count(totals.won)} won. ${count(other ?? 0)} other endings.`}
            >
              <path
                className={styles.ribbon}
                d={`M8 42 C55 42 68 48 120 48 V${48 + nextHeight} C68 ${48 + nextHeight} 55 ${42 + nextHeight} 8 ${42 + nextHeight} Z`}
              />
              <path
                className={styles.ribbon}
                d={`M128 48 C170 48 174 54 222 54 V${54 + wonHeight} C174 ${54 + wonHeight} 170 ${48 + nextHeight} 128 ${48 + nextHeight} Z`}
              />
              <path
                className={styles.otherRibbon}
                d={`M8 ${42 + nextHeight} C55 ${42 + nextHeight} 68 ${58 + nextHeight} 120 ${58 + nextHeight} V152 C68 152 55 136 8 136 Z`}
              />
              <rect x="0" y="42" width="8" height="94" rx="2" />
              <rect x="120" y="48" width="8" height={nextHeight} rx="2" />
              <rect x="222" y="54" width="8" height={wonHeight} rx="2" />
              <text x="0" y="14">
                Analysed
              </text>
              <text x="0" y="31" className={styles.svgCount}>
                {count(totals.calls)} calls
              </text>
              <text x="120" y="14">
                Next step
              </text>
              <text x="120" y="31" className={styles.svgCount}>
                {count(totals.nextStep)}
              </text>
              <text x="242" y="58">
                Won
              </text>
              <text x="242" y="77" className={styles.svgCount}>
                {count(totals.won)}
              </text>
              <text x="140" y="150">
                Other · {count(other ?? 0)}
              </text>
            </svg>
          ) : (
            <p className={styles.unavailable}>
              {few
                ? `Not enough calls yet (${count(totals.calls)} of ${MIN_CALLS})`
                : "— Funnel counts unavailable"}
            </p>
          )}
          <p className={styles.caption}>
            Won is part of Next step. A lead can appear in several calls.
          </p>
          <Button variant="primary" onClick={() => onCalls()}>
            View matching calls
          </Button>
          <p className={styles.coverage}>
            {coverage.calls
              ? `${count(totals.calls)} calls analysed`
              : "Analysed count unavailable"}
            {data.pending > 0
              ? ` · ${count(data.pending)} pending`
              : coverage.pending
                ? " · No calls pending"
                : " · Pending count unavailable"}
          </p>
        </section>
      </div>
      <EveryEnding
        groups={[
          {
            key: "forward",
            label: "Agreed a next step",
            rows: outcomes.filter((row) => FORWARD.has(row.key)),
          },
          {
            key: "other",
            label: "Other endings",
            rows: outcomes.filter((row) => !FORWARD.has(row.key)),
          },
        ]}
        calls={coverage.calls ? totals.calls : null}
        missing={missing}
        few={few}
        onCalls={onCalls}
      />
    </>
  );
}
