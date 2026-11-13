"use client";

/**
 * "Before you call" (lead page P5, spec §3; Dipak's top summary, kept short):
 * the problem, the goal, the last talk and the next step, from the same brief
 * the prospect pages draw (prospect-brief-model.ts) on this lead's newest
 * analysed call. Nothing is guessed: what isn't known reads "Not known yet".
 * "See more" opens the brief's other five areas in place. A lead nobody has
 * talked to yet says why they enquired, and that there was no conversation.
 * When the Report names a day for the next step, "Use as follow-up" books it
 * (it was the "Last call, in short" panel's, which the page no longer has).
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  BRIEF_SECTIONS,
  prospectBrief,
  type BriefSection,
} from "../prospect-brief-model";
import { notify } from "../notice-center";
import { useLatestCallReport } from "../prospect-latest-call";
import type { ProspectCall, ProspectSummary } from "../prospects-client";
import { watchCapture } from "./auto-capture-state";
import { callBrief } from "./call-brief";
import {
  LeadsError,
  setFollowUp,
  when,
  type LeadDetail,
  type LeadEvent,
} from "./leads-client";
import styles from "./lead-page.module.css";

const UNKNOWN = "Not known yet";

/** The lead's calls with a Report (newest first), as the brief reads calls. */
export function analysedCalls(events: readonly LeadEvent[]): ProspectCall[] {
  return events
    .filter((event) => event.kind === "call" && event.submission_id)
    .map(
      (event) =>
        ({
          submission_id: event.submission_id,
          created_at: event.at,
          has_report: true,
          snapshot: null,
        }) as unknown as ProspectCall,
    );
}

/** The lead as the brief's prospect: its name, stage and next step, no more. */
function asProspect(detail: LeadDetail): ProspectSummary {
  const { lead } = detail;
  return {
    prospect_id: lead.lead_id,
    name: lead.name,
    revision: 0,
    owner_person_id: lead.owner_person_id ?? "",
    stage: lead.stage_label,
    tags: [],
    photo_url: null,
    contact: null,
    fields: [],
    buyer_intent: null,
    next_step: detail.next_action_note?.trim() || null,
    last_promise: null,
    call_count: lead.calls,
    last_call: null,
  };
}

/** The newest call that was a conversation: the phone said connected, it has
 *  a recording, or the phone measured its talk; or its seller answered "We
 *  talked" after it (Redmi QA batch 10, 13 Nov 2026: "No previous
 *  conversation" above "talked to them: Interested"). That answer is the
 *  seller's own record, so the briefing goes by it; the numbers still count
 *  phone evidence only. A dial nobody answered isn't a talk. */
export function lastTalkOf(events: readonly LeadEvent[]): LeadEvent | null {
  for (const [index, event] of events.entries()) {
    if (
      event.kind === "call" &&
      (event.connected === true ||
        !!event.submission_id ||
        (!!event.via && (event.duration_seconds ?? 0) > 0))
    )
      return event;
    // Newest first: the call before a "We talked" is that talk.
    if (event.kind === "result" && event.connected && !event.answer_undone)
      return (
        events.slice(index + 1).find((item) => item.kind === "call") ?? event
      );
  }
  return null;
}

/** "3 Nov · 12 min": its day, and its length only where the phone or the
 *  recording measured it (never an estimate). */
export function talkNote(event: LeadEvent): string {
  const day = new Date(event.at).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
  const seconds = event.duration_seconds ?? 0;
  const measured = !!(event.seconds_from || event.via || event.submission_id);
  if (!measured || seconds <= 0) return day;
  const length =
    seconds < 60 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
  return `${day} · ${length}`;
}

/** With no Report: what the seller wrote about that talk (the call's own
 *  note, or the "We talked" answer saved after it), as written. */
export function sellerWords(
  events: readonly LeadEvent[],
  talk: LeadEvent,
): string | null {
  const after = events
    .slice(0, events.indexOf(talk))
    .reverse()
    .find(
      (event) =>
        event.kind === "result" && event.connected && !event.answer_undone,
    );
  const words = (text: string | null | undefined) =>
    text?.replace(/\s+/g, " ").trim() || null;
  return words(talk.note) ?? words(after?.note);
}

type Row = {
  label: string;
  note?: string;
  value: string | null;
  action?: ReactNode;
};

function Rows({ rows }: { rows: readonly Row[] }) {
  return (
    <dl className={styles.brief}>
      {rows.map((row) => (
        <div key={row.label} className={styles.briefRow}>
          <dt>
            {row.label}
            {row.note ? (
              <span className={styles.briefNote}>{row.note}</span>
            ) : null}
          </dt>
          <dd data-unknown={row.value ? undefined : ""}>
            {row.value ?? UNKNOWN}
          </dd>
          {row.action}
        </div>
      ))}
    </dl>
  );
}

function Area({ title, section }: { title: string; section: BriefSection }) {
  return (
    <section className={styles.briefArea}>
      <h4>{title}</h4>
      {section.facts.length ? (
        <Rows
          rows={section.facts.map((item) => ({
            label: item.label,
            value: item.value,
          }))}
        />
      ) : null}
      {section.unknown.length ? (
        <p className={styles.briefUnknown}>
          {UNKNOWN}: {section.unknown.map((item) => item.label).join(" · ")}
        </p>
      ) : null}
    </section>
  );
}

/** Whether the newest recorded call's Report may be asked for: the capture
 *  guard follows that recording and it isn't Report ready (a short call never
 *  is), there is none, and asking would 404 on every open (QA robot f3525cfb,
 *  2 Nov 2026; as the "Last call, in short" panel read it). */
function useReportReady(events: readonly LeadEvent[]): boolean {
  const call =
    events.find((event) => event.kind === "call" && event.submission_id) ??
    null;
  const id = call?.submission_id ?? null;
  const eventId = call?.event_id ?? null;
  const [gate, setGate] = useState<{ id: string; ready: boolean } | null>(null);
  useEffect(() => {
    if (!id || !eventId) return;
    return watchCapture(eventId, ({ server }) =>
      setGate({
        id,
        ready: server?.submission_id !== id || server.state === "report_ready",
      }),
    );
  }, [id, eventId]);
  if (!id) return false;
  return !eventId || (gate?.id === id && gate.ready);
}

export function LeadBrief({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged?: (next: LeadDetail) => void;
}) {
  const calls = useMemo(() => analysedCalls(detail.events), [detail.events]);
  const ready = useReportReady(detail.events);
  const latest = useLatestCallReport(calls, ready).latest;
  const prospect = useMemo(() => asProspect(detail), [detail]);
  const brief = useMemo(() => {
    try {
      return prospectBrief(prospect, calls, latest);
    } catch {
      // A Report it can't read never hides what is known without it.
      return prospectBrief(prospect, calls);
    }
  }, [prospect, calls, latest]);
  const said = useMemo(
    () => (latest ? callBrief({ content: latest.report }) : null),
    [latest],
  );
  const [open, setOpen] = useState(false);
  const [booking, setBooking] = useState(false);
  const id = `lead-brief-${detail.lead.lead_id}`;
  const lead = detail.lead;
  const nextAt = said?.next?.at ?? null;
  const canBook =
    !!nextAt &&
    !!onChanged &&
    detail.can_edit &&
    lead.stage !== "won" &&
    lead.stage !== "lost" &&
    lead.stage !== "junk";
  const book = async () => {
    if (!nextAt || !onChanged) return;
    setBooking(true);
    try {
      onChanged(await setFollowUp(lead, nextAt));
      notify({
        id: `brief-booked-${lead.lead_id}`,
        tone: "success",
        title: `Next call booked for ${when(nextAt.toISOString())}`,
      });
    } catch (reason) {
      notify({
        id: `brief-booked-${lead.lead_id}`,
        tone: "error",
        title:
          reason instanceof LeadsError
            ? reason.message
            : "Not booked. Try again.",
      });
    } finally {
      setBooking(false);
    }
  };

  const facts = brief.sections.flatMap((section) => section.facts);
  const fact = (...labels: string[]) =>
    facts.find((item) => labels.includes(item.label))?.value ?? null;
  const talk = lastTalkOf(detail.events);

  const rows: Row[] = talk
    ? [
        { label: "Problem", value: fact("Main problem") },
        { label: "Goal", value: fact("Main goal", "Desired outcome") },
        {
          label: "Last talk",
          note: talkNote(talk),
          value: said?.summary ?? sellerWords(detail.events, talk),
        },
        {
          label: "Next step",
          value:
            fact("Next step") ??
            (said?.next
              ? `${said.next.text}${nextAt ? ` · ${when(nextAt.toISOString())}` : ""}`
              : null),
          action: canBook ? (
            <button
              type="button"
              className={`${styles.textAction} ${styles.briefAction}`}
              disabled={booking}
              onClick={() => void book()}
            >
              Use as follow-up · {when(nextAt.toISOString())}
            </button>
          ) : null,
        },
      ]
    : [
        {
          label: "Why they enquired",
          value: detail.lead.interest?.trim() || null,
        },
        { label: "Last talk", value: "No previous conversation" },
      ];

  return (
    <section
      className={styles.card}
      aria-labelledby={id}
      data-open={open || undefined}
    >
      <h3 id={id} className={styles.cardTitle}>
        Before you call
      </h3>
      <Rows rows={rows} />
      {open ? (
        <div className={styles.briefMore}>
          {brief.sections.slice(1).map((section, index) => (
            <Area
              key={BRIEF_SECTIONS[index + 1].title}
              title={BRIEF_SECTIONS[index + 1].title}
              section={section}
            />
          ))}
        </div>
      ) : null}
      <button
        type="button"
        className={styles.textAction}
        aria-expanded={open}
        onClick={() => setOpen((now) => !now)}
      >
        {open ? "See less" : "See more"}
      </button>
    </section>
  );
}
