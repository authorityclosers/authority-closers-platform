"use client";

/**
 * "How was it?" after a key moment (owner, 23 Oct 2026: "each single
 * interaction we take review from the user"), without ever getting in the way.
 *
 * A small card above the tab bar (bottom corner on computers), never a modal:
 * three faces with words, an X for "not now", and "Don't ask about this
 * again". "Great" says thanks (and, in the phone app after a good moment, may
 * offer the Play Store rating Google allows); "Okay" or "Not good" asks what
 * would make it better, optionally. A "Not good" with words reaches the team's
 * bug list. It appears only once the person has seen the result and moved on
 * (another screen, or a few seconds without a touch), when no sheet, dialog or
 * unlogged call is in the way and nothing they might tap is where it would sit;
 * at most once a day and three times a week (rules.ts); and it leaves by itself
 * after a while.
 */

import { Frown, Meh, Smile, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { retryLater } from "../bug-report/bug-report-client";
import { commandId } from "../bug-report/command-id";
import { reportContext } from "../bug-report/device";
import { keepNow } from "../bug-report/outbox";
import { scrubRoute } from "../bug-report/scrub";
import { askStoreReview, inPhoneApp } from "../leads/native-phone";
import { peekPendingCall } from "../leads/leads-client";
import { tick } from "../ui/haptics";
import { ASK_FEEDBACK_EVENT, askFeedback, type AskDetail } from "./ask";
import {
  feedbackRequest,
  feedbackState,
  postFeedbackRequest,
  type FeedbackState,
  type Moment,
} from "./feedback-client";
import styles from "./feedback.module.css";
import { NO_ASKS, mayAsk, shown, type LocalAsks } from "./rules";

export const QUESTION: Record<Moment, string> = {
  report_read: "How useful was this Report?",
  call_outcome: "How easy was logging that call?",
  first_import: "How did your import go?",
  plan_purchase: "How was buying your plan?",
  chats_used: "How are Chats working for you?",
  app_update: "How is this update?",
  general: "How is Sales X-Ray for you?",
};

const FACES = [
  { rating: 1, label: "Not good", Icon: Frown },
  { rating: 2, label: "Okay", Icon: Meh },
  { rating: 3, label: "Great", Icon: Smile },
] as const;

const LOCAL_KEY = "sx-feedback-asks";
const REVIEW_KEY = "sx-store-review-at";
const REVIEW_MOMENTS: readonly Moment[] = [
  "report_read",
  "call_outcome",
  "app_update",
];
const LEAVE_AFTER_MS = 25_000;
const STATE_TTL_MS = 5 * 60_000;

function loadLocal(): LocalAsks {
  try {
    const raw = JSON.parse(window.localStorage.getItem(LOCAL_KEY) ?? "null");
    return raw && Array.isArray(raw.shown) ? (raw as LocalAsks) : NO_ASKS;
  } catch {
    return NO_ASKS;
  }
}

function saveLocal(value: LocalAsks): void {
  try {
    window.localStorage.setItem(LOCAL_KEY, JSON.stringify(value));
  } catch {
    // Private mode: the server's counts still keep it rare.
  }
}

/** Nothing is in the way: no sheet or dialog, the page is in front, no call to log. */
export function quiet(): boolean {
  return (
    !document.hidden &&
    !document.querySelector("dialog[open], [aria-modal='true']") &&
    peekPendingCall() === null
  );
}

/*
 * When a moment may ask (orchestrator, 23 Oct 2026, Redmi retest: "How was
 * buying your plan?" came at once over Payment confirmed's buttons): only after
 * the person has seen the result and moved on, to the next screen once it has
 * drawn, or by leaving this one untouched for a few seconds. Never over
 * something they might tap. While the card shows, the page gets room at its
 * end, so nothing has to stay under it.
 */
const SETTLE_MS = 1500;
const IDLE_MS = 6000;
const WAIT_MS = 180_000;
const POLL_MS = 500;
const CARD_PX = 176;
const ROOM_PX = 200;
const INPUTS = [
  "pointerdown",
  "keydown",
  "wheel",
  "touchstart",
  "scroll",
] as const;

let lastInput = 0;
function noteInput(): void {
  lastInput = Date.now();
}

/** Buttons, links and fields; a list's rows and the app's own bars don't count. */
const ACTIONS =
  "button, a[href], input:not([type='hidden']), select, textarea, [role='button'], [role='link'], [role='switch'], [role='tab']";
const NOT_ACTIONS =
  "nav, header, li, tr, [role='listitem'], [role='row'], [data-feedback-stack]";

export type Area = Readonly<{
  top: number;
  bottom: number;
  left: number;
  right: number;
}>;

/** Where the card would sit: one card tall, on its stack's line, as wide as the stack. */
function cardArea(stack: HTMLElement | null): Area | null {
  if (!stack) return null;
  const box = stack.getBoundingClientRect();
  return {
    top: box.bottom - CARD_PX,
    bottom: box.bottom,
    left: box.left,
    right: box.right,
  };
}

/** Something the person might tap is where the card would sit. */
export function coversAction(area: Area | null): boolean {
  if (!area || area.right <= area.left) return false;
  for (const element of document.querySelectorAll<HTMLElement>(ACTIONS)) {
    if (element.closest(NOT_ACTIONS)) continue;
    const box = element.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    if (
      box.bottom <= area.top ||
      box.top >= area.bottom ||
      box.right <= area.left ||
      box.left >= area.right
    ) {
      continue;
    }
    return true;
  }
  return false;
}

async function send(request: Record<string, unknown>): Promise<void> {
  try {
    await postFeedbackRequest(request);
  } catch (error) {
    if (retryLater(error)) {
      await keepNow("feedback", String(request.command_id), request);
    }
  }
}

/** The Play Store rating, after a good moment in the phone app; Google keeps it rare too. */
function maybeStoreReview(moment: Moment): void {
  if (!inPhoneApp() || !REVIEW_MOMENTS.includes(moment)) return;
  try {
    const last = Number(window.localStorage.getItem(REVIEW_KEY) ?? 0);
    if (Date.now() - last < 60 * 86_400_000) return;
    window.localStorage.setItem(REVIEW_KEY, String(Date.now()));
  } catch {
    return;
  }
  window.setTimeout(() => void askStoreReview(), 1200);
}

type Phase =
  | { at: "faces" }
  | { at: "words"; rating: 1 | 2 }
  | { at: "thanks" };

export function FeedbackCard({
  ask,
  onDone,
}: {
  ask: AskDetail;
  onDone: () => void;
}) {
  const [phase, setPhase] = useState<Phase>({ at: "faces" });
  const [words, setWords] = useState("");
  const command = useRef(commandId());
  const titleId = useId();
  const answered = useRef(false);

  const answer = async (
    kind: "rating" | "dismissed" | "opt_out",
    rating?: 1 | 2 | 3,
    comment?: string,
  ) => {
    if (answered.current) return;
    answered.current = true;
    await send(
      feedbackRequest({
        commandId: command.current,
        moment: ask.moment,
        kind,
        rating,
        comment,
        subject: ask.subject,
        route: scrubRoute(window.location.pathname + window.location.search),
        context: await reportContext(),
      }),
    );
  };

  // Left alone, it goes away by itself (counted as "not now").
  useEffect(() => {
    if (phase.at !== "faces") return;
    const timer = window.setTimeout(() => {
      void answer("dismissed");
      onDone();
    }, LEAVE_AFTER_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per phase
  }, [phase.at]);

  useEffect(() => {
    if (phase.at !== "thanks") return;
    const timer = window.setTimeout(onDone, 2400);
    return () => window.clearTimeout(timer);
  }, [phase.at, onDone]);

  return (
    <section
      className={styles.card}
      aria-labelledby={titleId}
      data-capture-skip=""
    >
      {phase.at === "thanks" ? (
        <p className={styles.thanks} role="status">
          Thanks. That helps us make it better.
        </p>
      ) : (
        <>
          <div className={styles.head}>
            <p id={titleId} className={styles.question}>
              {phase.at === "words"
                ? "What would make it better?"
                : QUESTION[ask.moment]}
            </p>
            <button
              type="button"
              className={styles.close}
              aria-label="Not now"
              onClick={() => {
                if (phase.at === "words") void answer("rating", phase.rating);
                else void answer("dismissed");
                onDone();
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          {phase.at === "faces" ? (
            <>
              <div
                className={styles.faces}
                role="group"
                aria-labelledby={titleId}
              >
                {FACES.map(({ rating, label, Icon }) => (
                  <button
                    key={rating}
                    type="button"
                    className={styles.face}
                    data-rating={rating}
                    onClick={() => {
                      tick();
                      if (rating === 3) {
                        void answer("rating", 3);
                        setPhase({ at: "thanks" });
                        maybeStoreReview(ask.moment);
                      } else {
                        setPhase({ at: "words", rating });
                      }
                    }}
                  >
                    <Icon size={24} aria-hidden="true" />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={styles.never}
                onClick={() => {
                  void answer("opt_out");
                  onDone();
                }}
              >
                Don&apos;t ask about this again
              </button>
            </>
          ) : (
            <form
              className={styles.words}
              onSubmit={(event) => {
                event.preventDefault();
                void answer("rating", phase.rating, words.trim() || undefined);
                setPhase({ at: "thanks" });
              }}
            >
              <textarea
                aria-label="What would make it better? (optional)"
                value={words}
                rows={2}
                maxLength={1000}
                placeholder="Optional. Your words only reach the team."
                onChange={(event) => setWords(event.target.value)}
              />
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.skip}
                  onClick={() => {
                    void answer("rating", phase.rating);
                    setPhase({ at: "thanks" });
                  }}
                >
                  Skip
                </button>
                <button type="submit" className={styles.send}>
                  Send
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </section>
  );
}

const CALL_REPORT = /^\/analysis\/calls\/([^/]+)/;
const READ_SECONDS = 25;

/** On a call's Report: asks once it has been read to the end (scrolled, and some time spent). */
function useReportRead(pathname: string | null) {
  useEffect(() => {
    const call = pathname ? CALL_REPORT.exec(pathname)?.[1] : undefined;
    if (!call) return;
    const since = Date.now();
    let asked = false;
    const onScroll = (event: Event) => {
      if (asked || Date.now() - since < READ_SECONDS * 1000) return;
      const target = event.target;
      const box =
        target instanceof Element
          ? target
          : (document.scrollingElement ?? null);
      if (!box || box.scrollHeight < box.clientHeight + 400) return;
      if (box.scrollTop + box.clientHeight >= box.scrollHeight - 48) {
        asked = true;
        askFeedback("report_read", { subject: `call:${call}`.slice(0, 64) });
      }
    };
    document.addEventListener("scroll", onScroll, {
      capture: true,
      passive: true,
    });
    return () =>
      document.removeEventListener("scroll", onScroll, { capture: true });
  }, [pathname]);
}

/**
 * Mounted once in the app frame. Listens for askFeedback(), waits until the
 * person has moved on and nothing is in the way, decides with the rules and
 * shows the card. Also notices when a call's Report has been read.
 */
export function FeedbackHost() {
  const pathname = usePathname();
  const [current, setCurrent] = useState<AskDetail | null>(null);
  const stack = useRef<HTMLDivElement>(null);
  const server = useRef<{ at: number; state: FeedbackState | null }>({
    at: 0,
    state: null,
  });
  useReportRead(pathname);

  useEffect(() => {
    for (const type of INPUTS) {
      document.addEventListener(type, noteInput, {
        capture: true,
        passive: true,
      });
    }
    return () => {
      for (const type of INPUTS) {
        document.removeEventListener(type, noteInput, { capture: true });
      }
    };
  }, []);

  useEffect(() => {
    let waiting: number | null = null;
    let cancelled = false;
    const consider = async (detail: AskDetail) => {
      const askedAt = Date.now();
      const from = window.location.pathname;
      let movedAt: number | null = null;
      for (;;) {
        if (cancelled) return;
        const now = Date.now();
        if (now - askedAt > WAIT_MS) return;
        if (movedAt === null && window.location.pathname !== from)
          movedAt = now;
        const still = now - lastInput;
        const movedOn =
          movedAt !== null
            ? now - movedAt >= SETTLE_MS && still >= SETTLE_MS
            : now - askedAt >= IDLE_MS && still >= IDLE_MS;
        if (movedOn && quiet() && !coversAction(cardArea(stack.current))) break;
        await new Promise((resolve) => {
          waiting = window.setTimeout(resolve, POLL_MS);
        });
      }
      if (cancelled) return;
      if (Date.now() - server.current.at > STATE_TTL_MS) {
        server.current = {
          at: Date.now(),
          state: await feedbackState().catch(() => null),
        };
      }
      const now = Date.now();
      const local = loadLocal();
      if (
        !mayAsk(detail.moment, detail.subject, now, local, server.current.state)
          .ask
      ) {
        return;
      }
      saveLocal(shown(local, detail.moment, detail.subject, now));
      server.current = { at: 0, state: null };
      if (!cancelled) setCurrent(detail);
    };
    const listen = (event: Event) => {
      void consider((event as CustomEvent<AskDetail>).detail);
    };
    window.addEventListener(ASK_FEEDBACK_EVENT, listen);
    return () => {
      cancelled = true;
      if (waiting !== null) window.clearTimeout(waiting);
      window.removeEventListener(ASK_FEEDBACK_EVENT, listen);
    };
  }, []);

  // While the card shows, room at the page's end, so its last buttons can scroll clear.
  const page = current ? document.getElementById("main-content") : null;
  return (
    <div ref={stack} className={styles.stack} data-feedback-stack="">
      {current ? (
        <FeedbackCard
          key={`${current.moment}:${current.subject ?? ""}`}
          ask={current}
          onDone={() => setCurrent(null)}
        />
      ) : null}
      {page
        ? createPortal(
            <div
              data-feedback-room=""
              aria-hidden="true"
              style={{ height: ROOM_PX }}
            />,
            page,
          )
        : null}
    </div>
  );
}
