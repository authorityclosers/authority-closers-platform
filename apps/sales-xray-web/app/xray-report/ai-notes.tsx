"use client";

/**
 * AI notes a seller can use (competitor teardown 24, 1 Nov 2026; Gong's
 * Briefs, HubSpot's summary beside the human notes, Pipedrive Nova's
 * approve-each-update): the Report's summary card becomes the Recap (three
 * lines, the rest a tap away), the Next step and Copy. Each block takes a
 * thumbs up or down and "Wrong? Tell us", which reaches the team. The
 * suggested updates (stage, next call, amount) are "Apply" chips where the
 * page knows the lead, and nothing is written without a tap. One line of
 * talk numbers closes it: "You 62% · longest monologue 2:10 · their longest
 * story 1:05".
 */

import { Check, Copy, FileText, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { commandId } from "../bug-report/command-id";
import { reportContext } from "../bug-report/device";
import { scrubRoute } from "../bug-report/scrub";
import {
  feedbackRequest,
  postFeedbackRequest,
} from "../feedback/feedback-client";
import { notify } from "../notice-center";
import type { Line } from "../report-story-model";
import { PlayChip, type Select } from "../report-visuals/visuals";
import { clock, type OutcomeKind, type XrayView } from "./model";
import styles from "./xray.module.css";
import own from "./ai-notes.module.css";

/** A line and its clip (the overview's LineWithClip, here without an import cycle). */
function Clip({
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

/** The call's talk, measured: the seller's share and each side's longest turn. */
export type TalkLine = {
  you: number | null;
  yourLongestMs: number | null;
  theirLongestMs: number | null;
};

export type NoteSuggestion =
  | { key: "stage"; outcome: OutcomeKind; label: string }
  | { key: "next_call"; date: string; label: string }
  | { key: "amount"; amount: string; label: string };

const STAGE: Partial<Record<OutcomeKind, string>> = {
  won: "Mark Won",
  lost: "Mark Lost",
  follow_up: "Move to Follow-up",
};

const DAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});

/** What the call says the lead should become: each an update to approve. */
export function noteSuggestions(view: XrayView): NoteSuggestion[] {
  const out: NoteSuggestion[] = [];
  const kind = view.outcome.kind;
  if (kind && STAGE[kind])
    out.push({ key: "stage", outcome: kind, label: STAGE[kind]! });
  const date = view.outcome.nextSteps[0]?.date ?? view.outcome.date;
  const at = date ? new Date(date) : null;
  if (date && at && !Number.isNaN(at.getTime()))
    out.push({
      key: "next_call",
      date,
      label: `Next call ${DAY.format(at)}`,
    });
  const amount = view.outcome.value?.amount?.trim();
  if (amount) out.push({ key: "amount", amount, label: `Amount ${amount}` });
  return out;
}

/** "2:10", not "02:10". */
const short = (ms: number) => clock(ms).replace(/^0(\d)/, "$1");

/** "You 62% · longest monologue 2:10 · their longest story 1:05", or null. */
export function talkWords(talk: TalkLine | null): string | null {
  if (!talk) return null;
  const parts = [
    talk.you !== null ? `You ${talk.you}%` : null,
    talk.yourLongestMs
      ? `longest monologue ${short(talk.yourLongestMs)}`
      : null,
    talk.theirLongestMs
      ? `their longest story ${short(talk.theirLongestMs)}`
      : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** One block's thumbs and "Wrong? Tell us" (Report feedback, moment report_read). */
function Rate({ block, callKey }: { block: string; callKey: string | null }) {
  const id = useId();
  const [chosen, setChosen] = useState<1 | 3 | null>(null);
  const [telling, setTelling] = useState(false);
  const [words, setWords] = useState("");
  const [sent, setSent] = useState(false);
  const subject =
    `ai_notes.${block}:${(callKey ?? "call").replace(/[^A-Za-z0-9_.:-]/g, "-")}`.slice(
      0,
      64,
    );
  const send = async (rating: 1 | 3, comment?: string) => {
    try {
      await postFeedbackRequest(
        feedbackRequest({
          commandId: commandId(),
          moment: "report_read",
          kind: "rating",
          rating,
          comment,
          subject,
          route: scrubRoute(window.location.pathname),
          context: await reportContext(),
        }),
      );
      return true;
    } catch {
      return false;
    }
  };
  if (sent)
    return <p className={own.thanks}>Thanks. The team will look at it.</p>;
  return (
    <div className={own.rate}>
      <button
        type="button"
        className={own.thumb}
        aria-label="Helpful"
        aria-pressed={chosen === 3}
        disabled={chosen !== null}
        onClick={() => {
          setChosen(3);
          void send(3);
        }}
      >
        <ThumbsUp size={15} aria-hidden="true" />
      </button>
      <button
        type="button"
        className={own.thumb}
        aria-label="Not helpful"
        aria-pressed={chosen === 1}
        disabled={chosen !== null}
        onClick={() => {
          setChosen(1);
          setTelling(true);
          void send(1);
        }}
      >
        <ThumbsDown size={15} aria-hidden="true" />
      </button>
      {telling ? (
        <form
          className={own.tell}
          onSubmit={async (event) => {
            event.preventDefault();
            if (!words.trim()) return;
            if (await send(1, words.trim())) setSent(true);
            else
              notify({
                id: "ai-notes-feedback",
                tone: "error",
                title: "That didn’t send",
                message: "Check your connection and try again.",
              });
          }}
        >
          <label htmlFor={id} className={own.srOnly}>
            What is wrong?
          </label>
          <input
            id={id}
            value={words}
            maxLength={1000}
            placeholder="What is wrong?"
            onChange={(event) => setWords(event.target.value)}
          />
          <button type="submit" className={own.send} disabled={!words.trim()}>
            Send
          </button>
        </form>
      ) : (
        <button
          type="button"
          className={own.wrong}
          onClick={() => setTelling(true)}
        >
          Wrong? Tell us
        </button>
      )}
    </div>
  );
}

function ApplyChip({
  suggestion,
  onApply,
}: {
  suggestion: NoteSuggestion;
  onApply: (suggestion: NoteSuggestion) => Promise<void>;
}) {
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  return (
    <button
      type="button"
      className={own.apply}
      data-state={state}
      disabled={state !== "idle"}
      onClick={async () => {
        setState("busy");
        try {
          await onApply(suggestion);
          setState("done");
        } catch {
          setState("idle");
          notify({
            id: "ai-notes-apply",
            tone: "error",
            title: "That wasn’t applied",
            message: "Someone may have changed the lead just now. Try again.",
          });
        }
      }}
    >
      {state === "done" ? <Check size={14} aria-hidden="true" /> : null}
      {state === "done" ? suggestion.label : `Apply: ${suggestion.label}`}
    </button>
  );
}

export function AiNotes({
  view,
  talk = null,
  callKey = null,
  onSelect,
  onApply,
}: {
  view: XrayView;
  talk?: TalkLine | null;
  /** The call, for feedback; never shown. */
  callKey?: string | null;
  onSelect?: Select;
  /** Where the page knows the lead (Leads' lead page): applies one update. */
  onApply?: (suggestion: NoteSuggestion) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  // More shows only when the recap is cut at three lines, measured as it lays out.
  const recap = useRef<HTMLParagraphElement>(null);
  const hasSummary = view.overview.summary !== null;
  const [cut, setCut] = useState(false);
  useEffect(() => {
    const node = recap.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(() =>
      setCut(node.scrollHeight > node.clientHeight + 1),
    );
    watch.observe(node);
    return () => watch.disconnect();
    // The recap's node comes and goes with the summary.
  }, [hasSummary]);
  const summary = view.overview.summary;
  const next = view.outcome.nextSteps[0] ?? null;
  const suggestions =
    onApply && !view.illustrative ? noteSuggestions(view) : [];
  const line = talkWords(talk);
  const copy = async () => {
    const text = [
      summary ? `Recap: ${summary.text}` : null,
      next ? `Next step: ${next.text}` : null,
    ]
      .filter(Boolean)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      notify({ id: "ai-notes-copy", tone: "success", title: "Copied" });
    } catch {
      notify({
        id: "ai-notes-copy",
        tone: "error",
        title: "Couldn’t copy",
        message: "Select the words and copy them instead.",
      });
    }
  };
  return (
    <section
      className={`${styles.card} ${styles.summary}`}
      aria-label="Call summary"
    >
      <span className={styles.square}>
        <FileText />
      </span>
      <div className={`${styles.summaryText} ${own.notes}`}>
        <div className={own.head}>
          <h3 className={styles.cardTitle}>Call Summary</h3>
          {summary || next ? (
            <button
              type="button"
              className={own.copy}
              onClick={() => void copy()}
            >
              <Copy size={14} aria-hidden="true" />
              Copy
            </button>
          ) : null}
        </div>
        <div className={own.block}>
          <span className={own.label}>Recap</span>
          {summary ? (
            <>
              <p
                ref={recap}
                className={`${styles.body} ${own.recap}`}
                data-open={open ? "" : undefined}
              >
                <Clip line={summary} title="Call summary" onSelect={onSelect} />
              </p>
              {cut || open ? (
                <button
                  type="button"
                  className={own.more}
                  aria-expanded={open}
                  onClick={() => setOpen(!open)}
                >
                  {open ? "Less" : "More"}
                </button>
              ) : null}
              {view.illustrative ? null : (
                <Rate block="recap" callKey={callKey} />
              )}
            </>
          ) : (
            <p className={`${styles.body} ${styles.muted}`}>
              This report has no summary.
            </p>
          )}
        </div>
        {next ? (
          <div className={own.block}>
            <span className={own.label}>Next step</span>
            <p className={styles.body}>
              <Clip
                line={{
                  text: next.text,
                  sources: next.source ? [next.source] : [],
                }}
                title="Next step"
                onSelect={onSelect}
              />
            </p>
            {view.illustrative ? null : (
              <Rate block="next_step" callKey={callKey} />
            )}
          </div>
        ) : null}
        {suggestions.length && onApply ? (
          <div
            className={own.applies}
            role="group"
            aria-label="Suggested updates"
          >
            {suggestions.map((suggestion) => (
              <ApplyChip
                key={suggestion.key}
                suggestion={suggestion}
                onApply={onApply}
              />
            ))}
          </div>
        ) : null}
        {line ? <p className={own.talk}>{line}</p> : null}
      </div>
    </section>
  );
}
