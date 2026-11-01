"use client";

/**
 * Ask Dipak (28 Oct 2026 meeting, "What the meeting decided"): the tab bar's
 * middle slot, with Dipak's face, where the + used to be. Until Dipak's
 * approved answer library ships (plan phase 6), it answers from what is
 * already known about a lead (orchestrator, 1 Nov 2026: "coming soon" was a
 * dead end, phone personas ph1-35): the last analysed call's Report (what
 * happened, what holds them back, the next step) and the notes on the lead,
 * each saying where it came from. Opened from a lead it answers about that
 * lead; from the tab bar the seller picks one first. It never shows an
 * invented answer, and it writes nothing.
 */

import {
  ChevronLeft,
  ChevronRight,
  FileText,
  GraduationCap,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { acquisition, callHref, submissionPath } from "../acquisition-client";
import { displayName } from "../display-name";
import { callBrief, type CallBrief } from "../leads/call-brief";
import {
  readLead,
  searchDesk,
  when,
  type LeadDetail,
  type LeadEvent,
  type LeadRow,
} from "../leads/leads-client";
import { Skeleton } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./ask-deepak.module.css";

type Picked = { id: string; name: string };

/** What a lead's own record says, read once per lead. */
type Answer = {
  id: string;
  detail: LeadDetail | null;
  call: { id: string; at: string; brief: CallBrief | null } | null;
};

const NOTES = 3;

/** The newest words people wrote on the lead: notes, and remarks saved with a call's outcome. */
export function leadNotes(detail: LeadDetail): LeadEvent[] {
  return detail.events
    .filter(
      (event) =>
        (event.kind === "note" ||
          (event.kind === "result" && !event.answer_undone)) &&
        Boolean(event.note?.trim()),
    )
    .slice(0, NOTES);
}

/**
 * Where the lead stands, from its own record, report or not: its stage, then
 * its last call and how it went ("Interested · last call Tue 4:30 pm, no
 * answer"). Phone personas ph1-49, 1 Nov 2026: a lead whose calls had no
 * report showed only its follow-up.
 */
export function standing(detail: LeadDetail): string {
  const call = detail.events.find((event) => event.kind === "call");
  const answer = detail.events.find(
    (event) => event.kind === "result" && !event.answer_undone,
  );
  const how = answer
    ? answer.connected
      ? "talked"
      : (answer.reason_label ?? "no answer").toLowerCase()
    : null;
  const last = call ?? answer;
  return [
    detail.lead.stage_label,
    last
      ? `last call ${when(last.at)}${how ? `, ${how}` : ""}`
      : "not called yet",
  ]
    .filter(Boolean)
    .join(" · ");
}

async function answerFor(id: string, signal: AbortSignal): Promise<Answer> {
  const detail = await readLead(id, signal);
  const call = detail.events.find(
    (event) => event.kind === "call" && event.submission_id,
  );
  if (!call?.submission_id) return { id, detail, call: null };
  let brief: CallBrief | null = null;
  try {
    brief = callBrief(
      await acquisition(`${submissionPath(call.submission_id)}/report`, {
        signal,
      }),
    );
  } catch {
    // Not analysed yet, or not this person's to read: the notes still answer.
  }
  return { id, detail, call: { id: call.submission_id, at: call.at, brief } };
}

export function AskDipakSheet({
  open,
  onClose,
  about = null,
  leadId = null,
}: {
  open: boolean;
  onClose: () => void;
  /** The customer it is about, from their Prospect's Information (item 97). */
  about?: string | null;
  /** That customer's lead: the sheet answers about it at once. */
  leadId?: string | null;
}) {
  const [picked, setPicked] = useState<Picked | null>(null);
  // Each opening starts from the choice; the last answer stays while the sheet
  // slides away.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setPicked(null);
  }
  const chosen: Picked | null = leadId
    ? { id: leadId, name: about ?? "" }
    : picked;
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        (chosen?.name ?? about)
          ? `Ask Dipak about ${displayName(chosen?.name ?? about ?? "")}`
          : "Ask Dipak"
      }
      wide="center"
    >
      {chosen ? (
        <LeadAnswer
          key={chosen.id}
          lead={chosen}
          onOther={leadId ? null : () => setPicked(null)}
          onLeave={onClose}
        />
      ) : (
        <PickLead start={about ?? ""} onPick={setPicked} />
      )}
      <Link className={styles.coaching} href="/coaching" onClick={onClose}>
        <GraduationCap size={18} aria-hidden="true" />
        <span>Dipak&rsquo;s coaching on your calls</span>
        <ChevronRight size={18} aria-hidden="true" />
      </Link>
    </Sheet>
  );
}

/**
 * From the tab bar: which lead it is about, found by a few letters of its name.
 * Opened from a lead that didn't say which, its name is already searched.
 */
function PickLead({
  start,
  onPick,
}: {
  start: string;
  onPick: (lead: Picked) => void;
}) {
  const field = useId();
  const [query, setQuery] = useState(start);
  const [found, setFound] = useState<{
    query: string;
    leads: LeadRow[] | null;
  } | null>(null);
  const words = query.trim();

  useEffect(() => {
    if (words.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchDesk(words, controller.signal).then(
        (result) => setFound({ query: words, leads: result.leads.slice(0, 6) }),
        () => {
          if (!controller.signal.aborted)
            setFound({ query: words, leads: null });
        },
      );
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [words]);

  const shown = words.length >= 2 && found?.query === words ? found : null;
  return (
    <div className={styles.body}>
      <span className={styles.face} aria-hidden="true" />
      <p className={styles.lead}>
        Before a call, see what the last call and your notes say about a lead.
      </p>
      <label className={styles.find} htmlFor={field}>
        <Search size={18} aria-hidden="true" />
        <span className="visually-hidden">Which lead?</span>
        <input
          id={field}
          type="search"
          inputMode="search"
          autoComplete="off"
          enterKeyHint="search"
          placeholder="Which lead? Type their name"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {words.length < 2 ? null : !shown ? (
        <Skeleton height={44} radius={12} />
      ) : shown.leads === null ? (
        <p className={styles.quiet}>
          Couldn&rsquo;t search just now. Try again.
        </p>
      ) : shown.leads.length === 0 ? (
        <p className={styles.quiet}>No lead matches &ldquo;{words}&rdquo;.</p>
      ) : (
        <ul className={styles.results} aria-label="Leads">
          {shown.leads.map((lead) => (
            <li key={lead.lead_id}>
              <button
                type="button"
                onClick={() => onPick({ id: lead.lead_id, name: lead.name })}
              >
                <span>
                  <strong>{displayName(lead.name)}</strong>
                  <small>{lead.stage_label}</small>
                </span>
                <ChevronRight size={18} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What the lead's own record says: its last call's Report and its notes. */
function LeadAnswer({
  lead,
  onOther,
  onLeave,
}: {
  lead: Picked;
  /** Back to choosing, when the seller chose it here. */
  onOther: (() => void) | null;
  onLeave: () => void;
}) {
  const [answer, setAnswer] = useState<
    Answer | { id: string; failed: true } | null
  >(null);

  useEffect(() => {
    const controller = new AbortController();
    answerFor(lead.id, controller.signal).then(setAnswer, () => {
      if (!controller.signal.aborted) setAnswer({ id: lead.id, failed: true });
    });
    return () => controller.abort();
  }, [lead.id]);

  const name = displayName(lead.name) || "this lead";
  const ready = answer?.id === lead.id ? answer : null;
  const read = ready && "detail" in ready ? ready : null;
  const brief = read?.call?.brief ?? null;
  const notes = read?.detail ? leadNotes(read.detail) : [];
  const next = read?.detail?.lead.next_action_at ?? null;
  // A follow-up saved with a note: its words show once, under Notes.
  const said = read?.detail?.next_action_note?.trim() || null;
  const nextNote =
    said && !notes.some((note) => note.note?.trim() === said) ? said : null;
  const nothing = read !== null && !brief && notes.length === 0 && !next;

  return (
    <div className={styles.answer} aria-live="polite" aria-busy={!ready}>
      {onOther ? (
        <button type="button" className={styles.other} onClick={onOther}>
          <ChevronLeft size={16} aria-hidden="true" />
          Another lead
        </button>
      ) : null}
      {!ready ? (
        <>
          <Skeleton height={18} width="60%" />
          <Skeleton height={64} radius={12} />
          <Skeleton height={44} radius={12} />
        </>
      ) : !read ? (
        <p className={styles.quiet}>
          Couldn&rsquo;t read {name} just now. Close this and try again.
        </p>
      ) : (
        <>
          {read.detail ? (
            <p className={styles.follow}>{standing(read.detail)}</p>
          ) : null}
          {brief && read.call ? (
            <section className={styles.part} aria-label="From the last call">
              <h3>From the last call, {when(read.call.at)}</h3>
              <dl>
                {brief.summary ? (
                  <>
                    <dt>What happened</dt>
                    <dd>{brief.summary}</dd>
                  </>
                ) : null}
                {brief.objection ? (
                  <>
                    <dt>What holds them back</dt>
                    <dd>{brief.objection}</dd>
                  </>
                ) : null}
                {brief.next ? (
                  <>
                    <dt>Next step</dt>
                    <dd>{brief.next.text}</dd>
                  </>
                ) : null}
              </dl>
              <Link
                className={styles.source}
                href={callHref(read.call.id)}
                onClick={onLeave}
              >
                <FileText size={16} aria-hidden="true" />
                Open the report
              </Link>
            </section>
          ) : null}
          {next ? (
            <p className={styles.follow}>
              Follow-up {when(next)}
              {nextNote ? `: ${nextNote}` : ""}
            </p>
          ) : null}
          {notes.length ? (
            <section className={styles.part} aria-label="Notes on this lead">
              <h3>Notes</h3>
              <ul>
                {notes.map((note, index) => (
                  <li key={`${note.at}-${index}`}>
                    <p>{note.note}</p>
                    <small>
                      {when(note.at)}
                      {note.actor_name
                        ? ` · ${displayName(note.actor_name)}`
                        : ""}
                    </small>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {nothing ? (
            <p className={styles.quiet}>
              Nothing on {name} yet: no analysed call and no notes. After your
              next call with them, the answer starts here.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
