"use client";

/**
 * The import's last step (owner's pick I4-A, 17 Nov 2026, "more colourful"; study 01 §5
 * S3): who gets the new leads and where they start, beside a live "When you import"
 * card with the only Import button. Owners named in the file keep their leads whatever
 * is picked (the server's rule); the choice is for the rest. Each line of the card has
 * its own tinted icon, so the summary reads at a glance.
 */

import {
  CircleAlert,
  CircleCheck,
  Copy,
  Layers,
  ListPlus,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { RowView } from "./import-rows";
import { outcomeCounts } from "./import-rows";
import styles from "./import-assign.module.css";

export type Tone = "good" | "info" | "action" | "calls" | "muted" | "problem";

export type SummaryLine = {
  key: string;
  icon: LucideIcon;
  tone: Tone;
  text: ReactNode;
  sub?: string | null;
};

export function SummaryCard({
  lines,
  action,
  footnote,
}: {
  lines: SummaryLine[];
  action: ReactNode;
  footnote: string | null;
}) {
  return (
    <section className={styles.card} aria-labelledby="import-when">
      <h3 id="import-when" className={styles.cardTitle}>
        When you import
      </h3>
      <ul className={styles.lines}>
        {lines.map((line) => (
          <li key={line.key} data-summary={line.key}>
            <span
              className={styles.icon}
              data-tone={line.tone}
              aria-hidden="true"
            >
              <line.icon size={18} strokeWidth={2.1} />
            </span>
            <span className={styles.text} data-tone={line.tone}>
              <span>{line.text}</span>
              {line.sub ? <small>{line.sub}</small> : null}
            </span>
          </li>
        ))}
      </ul>
      <div className={styles.action}>{action}</div>
      {footnote ? <p className={styles.footnote}>{footnote}</p> : null}
    </section>
  );
}

/** The summary's lines from the check and the choices made. */
export function summaryLines({
  rows,
  fresh,
  side,
  owners,
  whoLine,
  stageLine,
  keptWords,
}: {
  rows: readonly RowView[];
  fresh: number;
  side: "live" | "cold";
  /** "Farah Shaikh 4 · Rohan Patil 3": owners the file names. */
  owners: string;
  whoLine: string;
  stageLine: string;
  keptWords: string;
}): SummaryLine[] {
  const counts = rows.length ? outcomeCounts(rows) : null;
  const lines: SummaryLine[] = [
    {
      key: "new",
      icon: ListPlus,
      tone: "good",
      text: (
        <>
          <strong>{fresh}</strong> new {fresh === 1 ? "lead" : "leads"}
        </>
      ),
      sub: side === "cold" ? "Into Cold Leads" : "Into Inbound Leads",
    },
    {
      key: "who",
      icon: UsersRound,
      tone: "info",
      text: owners ? `From your file: ${owners}` : whoLine,
      sub: owners ? `The rest: ${whoLine}` : null,
    },
    {
      key: "stage",
      icon: Layers,
      tone: "action",
      text: stageLine,
    },
  ];
  if (counts?.known)
    lines.push({
      key: "known",
      icon: CircleCheck,
      tone: "muted",
      text: `${counts.known} already ${counts.known === 1 ? "a lead" : "leads"} · ${keptWords}`,
    });
  if (counts?.repeat)
    lines.push({
      key: "repeat",
      icon: Copy,
      tone: "muted",
      text: `${counts.repeat} repeated ${counts.repeat === 1 ? "row" : "rows"} · added once`,
    });
  if (counts?.cant)
    lines.push({
      key: "cant",
      icon: CircleAlert,
      tone: "problem",
      text: `${counts.cant} ${counts.cant === 1 ? "row" : "rows"} can't be added`,
    });
  return lines;
}

/** The phone's line above the fixed button: "9 new leads · 2 sellers · 3 not imported". */
export function phoneSummary(
  fresh: number,
  sellers: number,
  notImported: number,
): string {
  return [
    `${fresh} new ${fresh === 1 ? "lead" : "leads"}`,
    sellers ? `${sellers} ${sellers === 1 ? "seller" : "sellers"}` : null,
    notImported ? `${notImported} not imported` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "Owners from your file keep their leads" at the top of Assign. */
export function FileOwnersNote({
  owners,
  rest,
}: {
  owners: string;
  rest: number;
}) {
  if (!owners) return null;
  return (
    <div className={styles.owners} data-file-owners="">
      <span className={styles.icon} data-tone="info" aria-hidden="true">
        <UserRound size={18} strokeWidth={2.1} />
      </span>
      <p>
        <strong>Owners from your file keep their leads</strong>
        <small>
          {owners}
          {rest
            ? ` · ${rest} without an owner: choose who gets them below.`
            : ""}
        </small>
      </p>
    </div>
  );
}

export const UNDO_WORDS = "You can undo this import for 48 hours.";
