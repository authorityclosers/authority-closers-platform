"use client";

/**
 * Performance (Leads redesign, section 6; owner and Dipak, 30 Oct 2026): one
 * page from Home's Performance button, on the Performance engine. For each
 * seller: the work done, what was missed and the breaks taken. Inbound and
 * Cold leads are measured apart (Dipak's table): a 1,000-contact upload must
 * not change an Inbound number. A seller's red flags show without opening
 * their card. Owners and admins see the team and every seller; a seller
 * their own.
 */

import { useEffect, useState } from "react";

import { BreakRow, breakLength } from "../dashboard/home-today";
import { Segmented } from "../ui/kit";
import {
  readEffort,
  type Effort,
  type EffortDays,
  type SellerEffort,
  type SideEffort,
} from "./performance-client";
import styles from "./performance.module.css";

const PERIODS: { key: string; label: string; days: EffortDays }[] = [
  { key: "1", label: "Today", days: 1 },
  { key: "7", label: "7 days", days: 7 },
  { key: "30", label: "30 days", days: 30 },
];

/** "42%", or a dash when there is nothing to divide. */
export const percent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";

const talk = (seconds: number) => breakLength(Math.round(seconds / 60));

const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** One row of Dipak's table: what it measures, then Inbound and Cold. */
export type Measure = { label: string; inbound: string; cold: string };

const row = (
  label: string,
  inbound: SideEffort,
  cold: SideEffort,
  pick: (side: SideEffort) => string,
): Measure => ({ label, inbound: pick(inbound), cold: pick(cold) });

/** The work done, Inbound and Cold apart. */
export function measures(inbound: SideEffort, cold: SideEffort): Measure[] {
  return [
    row("Calls attempted", inbound, cold, (side) => String(side.attempted)),
    row("Connection rate", inbound, cold, (side) =>
      percent(side.connected, side.attempted),
    ),
    row("Talk time", inbound, cold, (side) => talk(side.talk_seconds)),
    row("Leads reached", inbound, cold, (side) => String(side.reached)),
    row("Contact coverage", inbound, cold, (side) =>
      percent(side.leads_attempted, side.eligible),
    ),
    row("To Interested", inbound, cold, (side) => String(side.interested)),
    row("Meetings booked", inbound, cold, (side) => String(side.meetings)),
    row("Won", inbound, cold, (side) => String(side.won)),
    row("Worked → Interested", inbound, cold, (side) =>
      percent(side.worked_interested, side.leads_attempted),
    ),
    {
      label: "First call in",
      inbound:
        inbound.first_call_minutes === null
          ? "–"
          : breakLength(inbound.first_call_minutes),
      cold: "Not measured",
    },
  ];
}

/** What was missed, Inbound and Cold apart. */
export function missed(inbound: SideEffort, cold: SideEffort): Measure[] {
  return [
    row("Late now (over an hour)", inbound, cold, (side) => String(side.late)),
    row("Missed calls", inbound, cold, (side) => String(side.missed_calls)),
    row("Not called back", inbound, cold, (side) =>
      String(side.not_called_back),
    ),
    row("Not called yet", inbound, cold, (side) => String(side.backlog)),
  ];
}

function MeasureTable({ rows, label }: { rows: Measure[]; label: string }) {
  return (
    <table className={styles.table} aria-label={label}>
      <thead>
        <tr>
          <th scope="col">
            <span className={styles.hidden}>Measure</span>
          </th>
          <th scope="col" data-side="inbound">
            Inbound
          </th>
          <th scope="col" data-side="cold">
            Cold
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((item) => (
          <tr key={item.label}>
            <th scope="row">{item.label}</th>
            <td>{item.inbound}</td>
            <td>{item.cold}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** "45 calls · 42% connected · 1 h 20 min talk". */
export function sellerLine(seller: SellerEffort): string {
  const attempted = seller.inbound.attempted + seller.cold.attempted;
  const connected = seller.inbound.connected + seller.cold.connected;
  const seconds = seller.inbound.talk_seconds + seller.cold.talk_seconds;
  return [
    `${attempted} ${attempted === 1 ? "call" : "calls"}`,
    `${percent(connected, attempted)} connected`,
    `${talk(seconds)} talk`,
  ].join(" · ");
}

const count = (value: number, one: string, many: string) =>
  `${value} ${value === 1 ? one : many}`;

/** What needs the owner's eye, shown before the card opens: only what isn't 0. */
export function flags(seller: SellerEffort): string[] {
  const late = seller.inbound.late + seller.cold.late;
  const back = seller.inbound.not_called_back + seller.cold.not_called_back;
  return [
    late ? count(late, "lead late", "leads late") : "",
    back ? `${back} not called back` : "",
    seller.tasks_late
      ? count(seller.tasks_late, "task late", "tasks late")
      : "",
    seller.missing_recordings
      ? count(
          seller.missing_recordings,
          "call without a recording",
          "calls without a recording",
        )
      : "",
  ].filter(Boolean);
}

function SellerCard({ seller, own }: { seller: SellerEffort; own: boolean }) {
  const red = flags(seller);
  const name = own ? "Your" : `${seller.name}'s`;
  return (
    <details className={styles.seller} open={own}>
      <summary>
        <strong>{own ? "You" : seller.name}</strong>
        <span>{sellerLine(seller)}</span>
        {red.length ? (
          <ul className={styles.flags} aria-label="Needs attention">
            {red.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        ) : null}
      </summary>
      <section className={styles.part}>
        <h3>Work done</h3>
        <MeasureTable
          rows={measures(seller.inbound, seller.cold)}
          label={`${name} work, Inbound and Cold`}
        />
      </section>
      <section className={styles.part}>
        <h3>Missed</h3>
        <MeasureTable
          rows={missed(seller.inbound, seller.cold)}
          label={`${name} missed work, Inbound and Cold`}
        />
        <p
          className={styles.line}
          data-red={seller.tasks_late ? "" : undefined}
        >
          {seller.tasks_late
            ? `${count(seller.tasks_late, "task", "tasks")} more than an hour late`
            : "No tasks late"}
        </p>
        <p
          className={styles.line}
          data-red={seller.missing_recordings ? "" : undefined}
        >
          {seller.missing_recordings
            ? `${count(seller.missing_recordings, "call", "calls")} without a recording today`
            : "Every connected call today has its recording"}
        </p>
      </section>
      <section className={styles.part}>
        <h3>Breaks</h3>
        {seller.first_call_at && seller.last_call_at ? (
          <p className={styles.line}>
            {`Today: first call ${CLOCK.format(new Date(seller.first_call_at))}, last call ends ${CLOCK.format(new Date(seller.last_call_at))}`}
          </p>
        ) : null}
        {seller.breaks.length ? (
          <ol className={styles.breaks} aria-label="3 longest breaks">
            {seller.breaks.map((gap) => (
              <BreakRow key={gap.start} gap={gap} />
            ))}
          </ol>
        ) : (
          <p className={styles.quiet}>No breaks between calls.</p>
        )}
        <p className={styles.line}>
          {`Between calls, outside set breaks: ${breakLength(seller.unplanned_break_minutes)}`}
        </p>
      </section>
    </details>
  );
}

type State =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; effort: Effort };

export function PerformanceView() {
  const [days, setDays] = useState<EffortDays>(1);
  const [state, setState] = useState<State>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    readEffort(days, controller.signal).then(
      (effort) => setState({ status: "ready", effort }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setState({ status: "error" });
      },
    );
    return () => controller.abort();
  }, [days]);

  const effort = state.status === "ready" ? state.effort : null;
  const approximate = effort?.sellers.some((seller) =>
    seller.breaks.some((gap) => gap.approximate),
  );
  return (
    <div className={styles.page}>
      <Segmented
        label="Performance for"
        value={String(days)}
        onChange={(key) => {
          // Loading until the new period's read lands.
          setState({ status: "loading" });
          setDays(PERIODS.find((period) => period.key === key)?.days ?? 1);
        }}
        items={PERIODS.map(({ key, label }) => ({ key, label }))}
      />
      {state.status === "loading" ? (
        <p className={styles.quiet} role="status">
          Counting the calls…
        </p>
      ) : state.status === "error" || !effort ? (
        <p className={styles.quiet} role="alert">
          Performance didn&apos;t load. Come back in a moment.
        </p>
      ) : (
        <>
          {effort.team ? (
            <section className={styles.card} aria-labelledby="team-title">
              <h2 id="team-title">Team</h2>
              <p className={styles.sub}>
                Inbound and Cold leads are counted apart, so an uploaded list
                doesn&apos;t change the Inbound numbers.
              </p>
              <MeasureTable
                rows={measures(effort.inbound, effort.cold)}
                label="The team's work, Inbound and Cold"
              />
              <MeasureTable
                rows={missed(effort.inbound, effort.cold)}
                label="The team's missed work, Inbound and Cold"
              />
              <p
                className={styles.line}
                data-red={effort.missing_recordings ? "" : undefined}
              >
                {`${count(effort.missing_recordings, "call", "calls")} without a recording today`}
              </p>
            </section>
          ) : null}
          <section className={styles.list} aria-label="Sellers">
            {effort.team && effort.sellers.length === 0 ? (
              <p className={styles.quiet}>No sellers yet.</p>
            ) : null}
            {effort.sellers.map((seller) => (
              <SellerCard
                key={seller.person_id}
                seller={seller}
                own={!effort.team}
              />
            ))}
          </section>
          {approximate ? (
            <p className={styles.quiet}>
              ≈ Next to a call from the app&apos;s Call button: its time is when
              the seller came back to the app.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
