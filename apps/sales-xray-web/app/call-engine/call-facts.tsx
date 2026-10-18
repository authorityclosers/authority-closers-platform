"use client";

/**
 * "From the calls" on a lead (owner direction 19 Oct: every call becomes data).
 * After a call the engine fills what it heard plainly and asks the seller the
 * rest, one at a time: keep, change or not right, with the line it came from.
 * Below, everything the calls established, grouped. A person's answer always
 * wins; nothing here guesses. Nothing shows until a call has been read.
 */

import { Check, ChevronDown, Pencil, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { readLead, type LeadDetail } from "../leads/leads-client";
import { notify } from "../notice-center";
import { Badge, Button, Skeleton } from "../ui/kit";
import {
  answer,
  CallDataError,
  readLeadFacts,
  type LeadFacts,
  type Question,
} from "./call-data-client";
import styles from "./call-facts.module.css";
import {
  basisLabel,
  editedValue,
  editStart,
  fieldLabel,
  groupFacts,
  keepLabel,
  questionText,
  rejectLabel,
  speakerLine,
} from "./call-facts-model";

const POLL_MS = 4000;
const POLL_LIMIT = 45; // about three minutes after a call, then stop

/** When the newest call with a recording reached this lead (only those are read). */
function newestRecordedCallAt(detail: LeadDetail): string | null {
  return (
    detail.events.find((event) => event.kind === "call" && event.submission_id)
      ?.at ?? null
  );
}

export function CallFacts({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const leadId = detail.lead.lead_id;
  const [facts, setFacts] = useState<LeadFacts | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [answered, setAnswered] = useState(0);
  const polls = useRef(0);
  const filledSeen = useRef<string | null>(null);
  // The parent may pass a new function each render; reads must not refire for it.
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  }, [onChanged]);
  const callAt = newestRecordedCallAt(detail);

  /** One read of the facts; the lead itself too when the engine just filled it. */
  const read = useCallback(
    async (signal?: AbortSignal) => {
      const next = await readLeadFacts(leadId, signal);
      const filled = next.filled.map((item) => item.object_id).join(",");
      const lead =
        filledSeen.current !== null && filled !== filledSeen.current
          ? await readLead(leadId, signal)
          : null;
      filledSeen.current = filled;
      return { next, lead };
    },
    [leadId],
  );

  const load = useCallback(
    (signal?: AbortSignal) =>
      read(signal).then(
        ({ next, lead }) => {
          setFacts(next);
          // The engine filled the lead since we last looked: show the new details.
          if (lead) changed.current(lead);
          setLoaded(leadId);
        },
        (error: unknown) => {
          if (signal?.aborted) return;
          // Not in an organisation, or not this seller's lead: show nothing.
          if (!(error instanceof CallDataError) || error.status >= 500)
            setFacts(null);
          setLoaded(leadId);
        },
      ),
    [read, leadId],
  );

  useEffect(() => {
    const controller = new AbortController();
    polls.current = 0;
    load(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [load, callAt, detail.lead.calls]);

  // A call was just made or uploaded and its facts are not in yet: look again
  // every few seconds for a while (the fast pipeline takes seconds).
  const waiting =
    facts !== null &&
    (facts.pipelines.fast.state === "running" ||
      (callAt !== null &&
        (facts.pipelines.fast.at === null ||
          facts.pipelines.fast.at < callAt)));
  useEffect(() => {
    if (!waiting || polls.current >= POLL_LIMIT) return;
    const timer = window.setTimeout(() => {
      polls.current += 1;
      void load();
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [waiting, facts, load]);

  if (loaded !== leadId) {
    return detail.lead.calls > 0 ? (
      <section className={styles.card} aria-label="From the calls" aria-busy>
        <Skeleton height={14} width="40%" />
        <Skeleton height={44} />
      </section>
    ) : null;
  }
  if (!facts || (!facts.facts.length && !facts.questions.length && !waiting))
    return null;

  const question: Question | undefined = facts.questions[0];
  const groups = groupFacts(facts.facts, facts.categories);
  const total = facts.questions.length;

  const decide = async (
    target: Question,
    decision: "accepted" | "edited" | "rejected",
    value?: Record<string, unknown>,
  ) => {
    setBusy(true);
    try {
      setFacts(await answer(target.object_id, decision, value));
      setAnswered((count) => count + 1);
      setEditing(null);
      if (target.lead_field && decision !== "rejected") {
        onChanged(await readLead(leadId));
      }
    } catch (error) {
      notify({
        id: `call-fact-${target.object_id}`,
        tone: "error",
        title: "Not saved",
        message:
          error instanceof CallDataError
            ? error.message
            : "Try again in a moment.",
      });
      void load();
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = (target: Question) => {
    const value = editedValue(target, draft);
    if (!value) {
      notify({
        id: `call-fact-${target.object_id}`,
        tone: "info",
        title: "Write it the way it was said",
        message:
          target.kind === "numeric"
            ? "Use numbers, like 8 or 4-5 lakh a month."
            : "The box can't be empty.",
        timeout: 5000,
      });
      return;
    }
    void decide(target, "edited", value);
  };

  return (
    <section className={styles.card} aria-label="From the calls">
      <div className={styles.head}>
        <h3>
          <Sparkles size={15} aria-hidden="true" />
          From the calls
        </h3>
        {waiting ? (
          <Badge tone="accent">Reading the call…</Badge>
        ) : facts.pipelines.deep.state === "running" ? (
          <Badge tone="accent">Deep analysis running</Badge>
        ) : null}
      </div>

      {facts.filled.length ? (
        <p className={styles.filled}>
          <Check size={14} aria-hidden="true" />
          Filled in for you:{" "}
          {facts.filled
            .map((item) => `${fieldLabel(item.field)} ${item.value}`)
            .join(" · ")}
        </p>
      ) : null}

      {question ? (
        <div className={styles.ask} aria-live="polite">
          <div className={styles.askTop}>
            <span className={styles.askCount}>
              Check {answered + 1} of {answered + total}
            </span>
            <span className={styles.askLabel}>{question.label}</span>
          </div>
          <p className={styles.askQuestion}>{questionText(question)}</p>
          {editing === question.object_id ? (
            <form
              className={styles.editRow}
              onSubmit={(event) => {
                event.preventDefault();
                saveEdit(question);
              }}
            >
              <input
                className={styles.input}
                aria-label={question.label}
                value={draft}
                autoFocus
                maxLength={300}
                onChange={(event) => setDraft(event.target.value)}
              />
              <Button type="submit" variant="primary" disabled={busy}>
                Save
              </Button>
              <Button disabled={busy} onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </form>
          ) : (
            <p className={styles.askValue}>{question.display}</p>
          )}
          {question.evidence[0] ? (
            <blockquote className={styles.quote}>
              <span className={styles.quoteWho}>
                {speakerLine(question.evidence[0])}
              </span>
              “{question.evidence[0].quote}”
            </blockquote>
          ) : null}
          {editing === question.object_id ? null : (
            <div className={styles.actions}>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => void decide(question, "accepted")}
              >
                <Check size={14} aria-hidden="true" />
                {keepLabel(question)}
              </Button>
              {question.kind !== "enum" ? (
                <Button
                  disabled={busy}
                  onClick={() => {
                    setDraft(editStart(question));
                    setEditing(question.object_id);
                  }}
                >
                  <Pencil size={14} aria-hidden="true" />
                  Change
                </Button>
              ) : null}
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void decide(question, "rejected")}
              >
                <X size={14} aria-hidden="true" />
                {rejectLabel(question)}
              </Button>
            </div>
          )}
        </div>
      ) : null}

      {groups.length ? (
        <div className={styles.known}>
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            What the calls told us ({facts.facts.length})
            <ChevronDown
              size={14}
              aria-hidden="true"
              data-open={open || undefined}
            />
          </button>
          {open ? (
            <div className={styles.groups}>
              {groups.map((group) => (
                <div key={group.key} className={styles.group}>
                  <span className={styles.groupLabel}>{group.label}</span>
                  <dl className={styles.rows}>
                    {group.facts.map((fact) => (
                      <div key={fact.object_id}>
                        <dt>{fact.label}</dt>
                        <dd>
                          <span>{fact.display}</span>
                          <small data-basis={fact.ai_read ? "ai" : fact.basis}>
                            {basisLabel(fact)}
                          </small>
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
