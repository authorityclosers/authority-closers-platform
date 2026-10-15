"use client";

import { LockKeyhole } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, type ReactNode } from "react";

import { COMMON, GUEST, recordedOutcome } from "../report-copy";
import type { DocumentReportData } from "../report-document-data";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "../report-contract";
import { RichText } from "../report-entities";
import { useReportPeople } from "../report-kit";
import { useCallOutcome } from "../report-outcome-context";
import { reportStoryModel, type Line } from "../report-story-model";
import { InferredTag, PlayChip, type Select } from "../report-visuals/visuals";
import styles from "./sections.module.css";

export type { Select };
export type People = ReturnType<typeof useReportPeople>;
export { GUEST } from "../report-copy";

const NO_CHIPS = [] as const;

/** Calm prose: words only, no coloured entity chips inside the story. */
export function Text({ text }: { text: string }) {
  return <RichText text={text} kinds={NO_CHIPS} />;
}

const EMPTY_TRANSCRIPT = {
  revision: "",
  timebase_id: "",
  duration_ms: 0,
  segments: [],
} as unknown as Transcript;

/** A person's recorded outcome for this call, in the Report's words. */
function useRecorded() {
  const { state } = useCallOutcome();
  const value = state.status === "ready" ? state.record.value : null;
  // One mapping for the screen and the Document (G's copy module).
  return useMemo(() => (value ? recordedOutcome(value) : null), [value]);
}

/** One model per report and speaker roles, shared by all six pillars. */
export function useStory(data: DocumentReportData, callId: string | null) {
  const people = useReportPeople(callId, data.transcript ?? EMPTY_TRANSCRIPT);
  const recorded = useRecorded();
  const seller = people.roles?.seller ?? null;
  const prospect = people.roles?.prospect ?? null;
  const model = useMemo(() => {
    if (!data.report) return null;
    try {
      return reportStoryModel(data.report, data.transcript, {
        roles: { seller, prospect },
        recorded,
      });
    } catch {
      // A malformed older report shows a quiet note, never a broken page.
      return "unavailable" as const;
    }
  }, [data.report, data.transcript, seller, prospect, recorded]);
  return { model, people };
}

/** Who said a quote, in the shape the visual Quote takes. */
export function speakerOf(people: People, source: ReportEvidence | undefined) {
  const person = people.speakerOf(source);
  if (!person) return null;
  const role =
    person.id === people.roles?.seller
      ? ("you" as const)
      : person.id === people.roles?.prospect
        ? ("prospect" as const)
        : null;
  return { name: person.name, role };
}

/** A line in the call's own words reads as speech: in quotes, with who said it. */
export function Words({ line, people }: { line: Line; people: People }) {
  if (!line.quoted) return <Text text={line.text} />;
  const who = speakerOf(people, line.sources[0]);
  return (
    <span className={styles.said}>
      “<Text text={line.text} />”
      {who ? <span className={styles.saidBy}>{who.name}</span> : null}
    </span>
  );
}

/** One quiet line naming what this report leaves out of a pillar. */
export function Gap({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <p className={styles.gap}>
      <span>{COMMON.gapsLead}</span> {items.join(" · ")}
    </p>
  );
}

export type Preview = NonNullable<SalesReport["preview"]>;
type PreviewSection = keyof Preview["sections"];

/** The app's router, or null where none is mounted (a static render). */
function useOptionalRouter() {
  try {
    return useRouter();
  } catch {
    return null;
  }
}

/** Sign-in that keeps this analysed call (the studio restores it after). */
export function UnlockButton({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const router = useOptionalRouter();
  if (!router)
    return (
      <a className={className} href="/login">
        {children}
      </a>
    );
  return (
    <button
      type="button"
      className={className}
      onClick={() => router.push("/login")}
    >
      {children}
    </button>
  );
}

/** A guest sees the visible part; the rest waits behind sign-in, by count. */
export function Locked({
  preview,
  sections,
  noun,
}: {
  preview?: Preview;
  sections: PreviewSection[];
  noun: [one: string, many: string];
}) {
  const hidden = preview
    ? sections.reduce(
        (sum, name) => sum + (preview.sections[name]?.hidden_count ?? 0),
        0,
      )
    : 0;
  if (!hidden) return null;
  return (
    <p className={styles.locked}>
      <LockKeyhole size={13} aria-hidden="true" />
      {GUEST.more(hidden, noun)}{" "}
      <UnlockButton className={styles.unlock}>{GUEST.unlock}</UnlockButton>
    </p>
  );
}

/** A labelled part of a card: small label, then the words. */
export function Field({
  label,
  inferred,
  children,
}: {
  label: ReactNode;
  inferred?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={styles.field}>
      <p className={styles.fieldLabel}>
        {label}
        {inferred ? <InferredTag /> : null}
      </p>
      <div className={styles.fieldText}>{children}</div>
    </div>
  );
}

/** A sentence from the report with its play chip at the end. */
export function LineText({
  line,
  title,
  onSelect,
  last = false,
}: {
  line: Line;
  title: string;
  onSelect?: Select;
  /** Play the last source (an agreement is usually confirmed last). */
  last?: boolean;
}) {
  const source = last ? line.sources.at(-1) : line.sources[0];
  return (
    <p className={styles.line}>
      <Text text={line.text} />
      {source ? (
        <>
          {" "}
          <PlayChip source={source} title={title} onSelect={onSelect} />
        </>
      ) : null}
    </p>
  );
}

/** A short bulleted list of plain lines. */
export function Bullets({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className={styles.bullets}>
      {items.map((item) => (
        <li key={item}>
          <Text text={item} />
        </li>
      ))}
    </ul>
  );
}
