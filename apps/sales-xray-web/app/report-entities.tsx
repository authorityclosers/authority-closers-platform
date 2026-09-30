import {
  CalendarDays,
  FileText,
  GraduationCap,
  IndianRupee,
  UserRound,
  Video,
} from "lucide-react";
import type { ReactNode } from "react";

import styles from "./report-entities.module.css";

// Things the AI's report text mentions (WhatsApp, a program, money, a
// document, a video, a date, a person) shown as small icon chips. Pure text
// matching on the saved report: no AI call, nothing invented.

export type EntityKind =
  | "whatsapp"
  | "program"
  | "money"
  | "document"
  | "video"
  | "date"
  | "person";

const PATTERNS: Array<[EntityKind, string]> = [
  ["whatsapp", String.raw`[Ww]hats\s?[Aa]pp|WHATSAPP|व्हाट्सएप|व्हॉट्सऍप`],
  [
    "program",
    String.raw`\b\d+[- ][Dd]ay\s+(?:\p{Lu}[\w-]*\s+){0,4}(?:[Pp]rogram(?:me)?|[Cc]ourse|[Ww]orkshop|[Tt]raining|[Bb]ootcamp|[Ee]vent)\b|\b(?:\p{Lu}[\w-]*\s+){1,4}(?:Program(?:me)?|Course|Workshop|Bootcamp)\b`,
  ],
  [
    "money",
    String.raw`₹\s?[\d,.]+(?:\s?(?:lakh|crore|k))?|\b[\d,.]+(?:\s?(?:to|-)\s?[\d,.]+)?\s?(?:(?:lakh|crore|Lakh|Crore)(?:\s+rupees)?|rupees)\b|\b(?:[Uu]npaid\s+)?[Rr]eceivables?\b|\b[Rr]evenue\b|\b[Tt]urnover\b`,
  ],
  [
    "document",
    String.raw`\b[Ss]yllabus\b|\b[Ww]orkbooks?\b|\b[Bb]rochures?\b|\b[Pp]roposals?\b|\bPDFs?\b|\b[Qq]uotations?\b`,
  ],
  ["video", String.raw`\b[Vv]ideos?\b|\b[Rr]ecordings?\b`],
  [
    "date",
    String.raw`\b[Nn]ext day\b|\b[Tt]omorrow\b|\b[Nn]ext week\b|\b[Nn]ext month\b|\b\d{1,2}(?::\d{2})?\s?(?:am|pm|AM|PM)\b`,
  ],
  [
    "person",
    String.raw`\b[Ss]enior manager\b|\b[Dd]ecision[- ]maker\b|\b[Bb]usiness partner\b|\b[Cc]o-?founder\b`,
  ],
];

// Case matters on purpose: only capitalised names read as a program.
const MATCHER = new RegExp(
  PATTERNS.map(([kind, pattern]) => `(?<${kind}>${pattern})`).join("|"),
  "gu",
);

function WhatsAppMark({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={styles.wa}
    >
      <path
        className={styles.waBubble}
        d="M12 2.2a9.8 9.8 0 0 0-8.4 14.8L2.2 21.8l4.9-1.3A9.8 9.8 0 1 0 12 2.2z"
      />
      <path
        className={styles.waPhone}
        d="M8.6 7.3c.2-.4.4-.4.7-.4h.5c.2 0 .4 0 .6.5l.8 1.9c.1.2.1.4 0 .6l-.4.6c-.1.2-.2.3 0 .6.4.7 1 1.4 1.7 1.9.3.2.7.4 1 .6.3.1.4.1.6-.1l.6-.7c.2-.2.4-.2.6-.1l1.8.9c.2.1.4.2.4.4 0 .5-.1 1.1-.5 1.5-.5.5-1.3.8-2 .7-1.3-.2-2.6-.8-3.7-1.7-1.2-1-2.1-2.2-2.7-3.6-.3-.8-.4-1.7 0-2.5z"
      />
    </svg>
  );
}

const ICONS: Record<EntityKind, ReactNode> = {
  whatsapp: <WhatsAppMark />,
  program: <GraduationCap size={13} aria-hidden="true" />,
  money: <IndianRupee size={12} aria-hidden="true" />,
  document: <FileText size={12} aria-hidden="true" />,
  video: <Video size={13} aria-hidden="true" />,
  date: <CalendarDays size={12} aria-hidden="true" />,
  person: <UserRound size={12} aria-hidden="true" />,
};

/** Splits report text into plain runs and entity matches. */
export function findEntities(
  text: string,
): Array<string | { kind: EntityKind; text: string }> {
  const parts: Array<string | { kind: EntityKind; text: string }> = [];
  let last = 0;
  for (const match of text.matchAll(MATCHER)) {
    const index = match.index ?? 0;
    const kind = (Object.entries(match.groups ?? {}).find(
      ([, value]) => value !== undefined,
    )?.[0] ?? null) as EntityKind | null;
    if (!kind) continue;
    if (index > last) parts.push(text.slice(last, index));
    parts.push({ kind, text: match[0] });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** Report text with its mentions shown as icon chips. */
export function EntityText({ text }: { text: string }) {
  return (
    <>
      {findEntities(text).map((part, index) =>
        typeof part === "string" ? (
          part
        ) : (
          <span key={index} className={styles.chip} data-kind={part.kind}>
            {ICONS[part.kind]}
            {part.text}
          </span>
        ),
      )}
    </>
  );
}
