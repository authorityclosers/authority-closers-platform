"use client";

import Image from "next/image";
import {
  ActionButton,
  actionClassName,
  ChoiceOption,
  FocusSession,
  RouteHeader,
  SessionStep,
} from "@ac/ui";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  Clock3,
  Headphones,
  Lightbulb,
  LoaderCircle,
  RotateCcw,
  X,
} from "lucide-react";
import {
  practiceApi,
  PracticeRequestError,
  type PracticeApi,
  type PracticeNode,
  type PracticePrompt,
  type PracticeSet,
  type PracticeSummary,
} from "../lib/practice-api";
import styles from "./practice-arcade.module.css";
import { PracticeEngineRequestError } from "../lib/practice-engine-api";

const labels = {
  choice: "Choose a response",
  gap: "Fill the gap",
  match: "Connect the pairs",
  build: "Build the question",
  order: "Find the sequence",
  audio: "Listen and respond",
  branch: "Try the conversation",
};
const practiceHref = (id: string) => `/practice?set=${encodeURIComponent(id)}`;

function LoadFailure({ error, retry }: { error: unknown; retry: () => void }) {
  const signIn = error instanceof PracticeRequestError && error.status === 401;
  return (
    <section className={styles.loadFailure} role="alert">
      <h1>{signIn ? "Your next practice is waiting" : "Let’s reconnect"}</h1>
      <p>
        {error instanceof PracticeRequestError
          ? error.message
          : "Practice couldn’t load. Check your connection and try again."}
      </p>
      {signIn ? (
        <Link className={actionClassName()} href="/login">
          Sign in
        </Link>
      ) : (
        <ActionButton onClick={retry}>Try again</ActionButton>
      )}
    </section>
  );
}

export function PracticeArcade({
  setId,
  api = practiceApi,
  recognition,
  durable = false,
}: {
  setId?: string;
  api?: PracticeApi;
  recognition?: React.ReactNode;
  durable?: boolean;
}) {
  const [catalog, setCatalog] = useState<PracticeSummary[] | null>(null);
  const [active, setActive] = useState<PracticeSet | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    const load = async () => {
      try {
        const result = setId
          ? await api.set(setId, controller.signal)
          : await api.catalog(controller.signal);
        if (!live) return;
        if ("id" in result) setActive(result);
        else setCatalog(result.items);
      } catch (reason) {
        if (live) setError(reason);
      }
    };
    void load();
    return () => {
      live = false;
      controller.abort();
    };
  }, [api, setId, epoch]);
  const frame = (content: React.ReactNode) =>
    setId ? (
      <FocusSession
        header={
          <Link className={actionClassName("quiet")} href="/practice">
            <ArrowLeft size={18} /> Back to practice
          </Link>
        }
      >
        {content}
      </FocusSession>
    ) : (
      content
    );
  if (error)
    return frame(
      <LoadFailure
        error={error}
        retry={() => {
          setError(null);
          setEpoch((e) => e + 1);
        }}
      />,
    );
  if (active) return <PracticeRun key={active.id} set={active} api={api} />;
  if (!catalog)
    return frame(
      <div className={styles.loading} role="status">
        <LoaderCircle size={24} />
        Getting your practice ready…
      </div>,
    );
  return (
    <div className={styles.arcade}>
      <RouteHeader
        title="Practice Arcade"
        titleId="practice-title"
        description="Build confidence, one conversation at a time."
        aside={<span className={styles.previewBadge}>Preview</span>}
      />
      {recognition}
      <section
        className={styles.featured}
        aria-labelledby="practice-featured-title"
      >
        <Image
          src="/arcade-v02/discovery-compass.svg"
          width={88}
          height={88}
          alt=""
          className={styles.featuredArt}
        />
        <div>
          <p className={styles.skill}>A good place to start</p>
          <h2 id="practice-featured-title">Find your next move</h2>
          <p>Three small decisions. A fresh way to listen.</p>
        </div>
        <Link className={actionClassName()} href={practiceHref("next-move")}>
          Start practice <ArrowRight size={18} />
        </Link>
      </section>
      <section aria-labelledby="practice-library-title">
        <div className={styles.sectionHeading}>
          <div>
            <h2 id="practice-library-title">What would you like to work on?</h2>
            <p>Choose one skill. Every set has three short prompts.</p>
          </div>
          <span>{catalog.length} sets to explore</span>
        </div>
        <div className={styles.library}>
          {catalog.map((item) => (
            <Link
              key={item.id}
              href={practiceHref(item.id)}
              className={styles.setCard}
              data-color={item.color}
            >
              <div className={styles.artTile}>
                <Image
                  src={`/arcade-v02/${item.art}.svg`}
                  width={96}
                  height={96}
                  alt=""
                  loading="lazy"
                />
              </div>
              <div className={styles.setCopy}>
                <span className={styles.skill}>{item.skill}</span>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
                <div className={styles.setMeta}>
                  <span>
                    <Clock3 size={14} />
                    About {item.estimated_minutes} min
                  </span>
                  <span>{item.item_count} prompts</span>
                </div>
              </div>
              <ChevronRight className={styles.cardArrow} size={20} />
            </Link>
          ))}
        </div>
      </section>
      <p className={styles.previewNote}>
        {durable
          ? "Draft practice content is awaiting coach review. Your practice responses and earned rewards are saved separately from course progress and assessments."
          : "You’re exploring draft practice content awaiting coach review. This session stays in this tab and doesn’t change course progress, streaks, or rankings."}
      </p>
    </div>
  );
}

export function isPracticeResponseReady(
  item: PracticePrompt,
  selections: number[],
): boolean {
  if (item.kind === "branch") return selections.length === 1;
  const count =
    item.kind === "match"
      ? item.left.length
      : item.kind === "build" || item.kind === "order"
        ? item.options.length
        : 1;
  return (
    selections.length === count &&
    selections.every((n) => n >= 0) &&
    new Set(selections).size === selections.length
  );
}

function PracticeRun({ set, api }: { set: PracticeSet; api: PracticeApi }) {
  const [position, setPosition] = useState(0);
  const [revised, setRevised] = useState(0);
  const [exitOpen, setExitOpen] = useState(false);
  const exitRef = useRef<HTMLDialogElement>(null);
  const exitButton = useRef<HTMLButtonElement>(null);
  const finishHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (exitOpen) exitRef.current?.showModal();
  }, [exitOpen]);
  const completed = position >= set.items.length;
  useEffect(() => {
    if (completed) finishHeading.current?.focus({ preventScroll: true });
  }, [completed]);
  return (
    <FocusSession
      header={
        <div className={styles.runHeader}>
          <button
            ref={exitButton}
            className={actionClassName("icon")}
            aria-label="Leave practice"
            onClick={() => setExitOpen(true)}
          >
            <X size={21} />
          </button>
          <div className={styles.runIdentity}>
            <span>{set.skill}</span>
            <strong>{set.title}</strong>
          </div>
          <span className={styles.runCount}>
            {Math.min(position + 1, set.items.length)} / {set.items.length}
          </span>
          <div
            className={styles.meter}
            role="progressbar"
            aria-label="Prompts explored in this session"
            aria-valuemin={0}
            aria-valuemax={set.items.length}
            aria-valuenow={position}
          >
            <span
              style={{ width: `${(position / set.items.length) * 100}%` }}
            />
          </div>
        </div>
      }
    >
      {completed ? (
        <section
          className={styles.finish}
          aria-labelledby="practice-finish-heading"
        >
          <Image
            src="/arcade-v02/checkpoint-seal.svg"
            width={136}
            height={136}
            alt=""
          />
          <p className={styles.eyebrow}>A little practice goes a long way</p>
          <h1 id="practice-finish-heading" ref={finishHeading} tabIndex={-1}>
            That’s a good rep.
          </h1>
          <p>
            You explored {set.items.length} prompts in {set.skill.toLowerCase()}
            .
            {revised > 0
              ? ` You also revised ${revised === 1 ? "a response" : `${revised} responses`}. That’s what practice is for.`
              : " Take one useful idea into your next conversation."}
          </p>
          <div className={styles.finishActions}>
            <Link className={actionClassName()} href="/practice">
              Find another skill <ArrowRight size={17} />
            </Link>
            <button
              className={actionClassName("secondary")}
              onClick={() => {
                setPosition(0);
                setRevised(0);
              }}
            >
              Practise this set again
            </button>
          </div>
          <p className={styles.previewNote}>
            Practice preview only. This isn’t a course result or assessment.
          </p>
        </section>
      ) : (
        <PracticeQuestion
          key={set.items[position].id}
          item={set.items[position]}
          setId={set.id}
          api={api}
          last={position === set.items.length - 1}
          onNext={(wasRevised) => {
            if (wasRevised) setRevised((n) => n + 1);
            setPosition((n) => n + 1);
          }}
        />
      )}
      {exitOpen ? (
        <dialog
          ref={exitRef}
          className={styles.exitDialog}
          aria-labelledby="practice-exit-title"
          aria-describedby="practice-exit-description"
          onCancel={() => setExitOpen(false)}
          onClose={() => {
            setExitOpen(false);
            exitButton.current?.focus();
          }}
        >
          <h2 id="practice-exit-title">Leave this practice?</h2>
          <p id="practice-exit-description">
            Your responses in this round aren’t saved. If you leave, you’ll
            start the set again. Your course progress won’t change.
          </p>
          <div className={styles.finishActions}>
            <button
              className={actionClassName()}
              onClick={() => exitRef.current?.close()}
            >
              Keep practising
            </button>
            <Link className={actionClassName("secondary")} href="/practice">
              Leave practice
            </Link>
          </div>
        </dialog>
      ) : null}
    </FocusSession>
  );
}

export type PracticeEditorialResult =
  | { kind: "continue"; node: PracticeNode }
  | { kind: "feedback"; reference_match: boolean | null; explanation: string };

export function PracticeQuestion({
  item,
  setId,
  api = practiceApi,
  last = false,
  onNext,
  checkResponse,
  onAdvance,
  initialState,
  disabled = false,
  onInteraction,
}: {
  item: PracticePrompt;
  setId: string;
  api?: PracticeApi;
  last?: boolean;
  onNext: (revised: boolean) => void;
  checkResponse?: (
    selections: number[],
    signal: AbortSignal,
  ) => Promise<PracticeEditorialResult>;
  onAdvance?: (signal: AbortSignal) => Promise<void>;
  initialState?: {
    selections: number[] | null;
    feedback: PracticeEditorialResult | null;
  };
  disabled?: boolean;
  onInteraction?: (kind: "select" | "submit") => void;
}) {
  const [selections, setSelections] = useState<number[]>(
    item.kind === "branch" ? [] : (initialState?.selections ?? []),
  );
  const [leftSelected, setLeftSelected] = useState<number | null>(null);
  const [node, setNode] = useState<PracticeNode | null>(
    initialState?.feedback?.kind === "continue"
      ? initialState.feedback.node
      : item.kind === "branch"
        ? item.node
        : null,
  );
  const [path, setPath] = useState<number[]>(
    item.kind === "branch"
      ? initialState?.feedback?.kind === "feedback"
        ? (initialState.selections ?? []).slice(0, -1)
        : (initialState?.selections ?? [])
      : [],
  );
  const [conversation, setConversation] = useState<
    { buyer: string; reply: string }[]
  >([]);
  const [hint, setHint] = useState(false);
  const [feedback, setFeedback] = useState<Extract<
    PracticeEditorialResult,
    { kind: "feedback" }
  > | null>(
    initialState?.feedback?.kind === "feedback" ? initialState.feedback : null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [wasRevised, setWasRevised] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const questionRef = useRef<HTMLDivElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
    return () => {
      requestRef.current?.abort();
    };
  }, []);
  const frozen = disabled || busy || feedback !== null;
  const choose = (next: number[]) => {
    if (!frozen) {
      onInteraction?.("select");
      setSelections(next);
      setError(null);
    }
  };
  const check = async () => {
    if (
      inFlight.current ||
      disabled ||
      feedback ||
      !isPracticeResponseReady(item, selections)
    )
      return;
    inFlight.current = true;
    onInteraction?.("submit");
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError(null);
    try {
      const nextPath =
        item.kind === "branch" ? [...path, ...selections] : selections;
      const result = checkResponse
        ? await checkResponse(nextPath, controller.signal)
        : await api.check(setId, item.id, nextPath, controller.signal);
      if (controller.signal.aborted) return;
      if (item.kind === "branch" && node) {
        setConversation((history) => [
          ...history,
          {
            buyer: node.buyer,
            reply: node.options.find((o) => o.id === selections[0])?.text ?? "",
          },
        ]);
      }
      if (result.kind === "continue") {
        setNode(result.node);
        setPath(nextPath);
        setSelections([]);
      } else {
        setFeedback(result);
        if (result.reference_match === false) setWasRevised(true);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason);
    } finally {
      if (!controller.signal.aborted) {
        setBusy(false);
        inFlight.current = false;
      }
    }
  };
  const advance = async () => {
    if (disabled || inFlight.current || !feedback) return;
    onInteraction?.("submit");
    if (!onAdvance) {
      onNext(wasRevised);
      return;
    }
    inFlight.current = true;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError(null);
    try {
      await onAdvance(controller.signal);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason);
    } finally {
      if (!controller.signal.aborted) {
        setBusy(false);
        inFlight.current = false;
      }
    }
  };
  useEffect(() => {
    const scrollBody = questionRef.current?.closest<HTMLElement>(
      '[data-session-scroll="body"]',
    );
    if (scrollBody) scrollBody.scrollTop = 0;
    if (feedback) feedbackRef.current?.focus({ preventScroll: true });
    else headingRef.current?.focus({ preventScroll: true });
  }, [feedback]);
  const options = item.kind === "branch" ? (node?.options ?? []) : item.options;
  const count = item.kind === "match" ? item.left.length : options.length;
  const sequence = item.kind === "build" || item.kind === "order";
  return (
    <SessionStep
      labelledBy={`prompt-${item.id}`}
      footer={
        <div className={styles.footerActions}>
          {!feedback ? (
            <span className={styles.footerHint}>
              Choose your response to continue
            </span>
          ) : null}
          {feedback ? (
            <>
              {feedback.reference_match === false ? (
                <button
                  className={actionClassName("secondary")}
                  disabled={busy || disabled}
                  onClick={() => {
                    setFeedback(null);
                    setError(null);
                    if (item.kind === "branch") {
                      setNode(item.node);
                      setPath([]);
                      setSelections([]);
                      setConversation([]);
                    }
                  }}
                >
                  Try a different answer
                </button>
              ) : null}
              <button
                className={actionClassName()}
                disabled={busy || disabled}
                onClick={() => void advance()}
              >
                {busy ? "Saving…" : last ? "Finish this set" : "Next prompt"}
                <ArrowRight size={17} />
              </button>
            </>
          ) : (
            <button
              className={actionClassName()}
              disabled={
                disabled || busy || !isPracticeResponseReady(item, selections)
              }
              onClick={() => void check()}
            >
              {busy ? (
                <>
                  <LoaderCircle size={18} />
                  Checking…
                </>
              ) : item.kind === "branch" ? (
                <>
                  Send response <ArrowRight size={17} />
                </>
              ) : (
                <>
                  Check my response <Check size={17} />
                </>
              )}
            </button>
          )}
        </div>
      }
    >
      <div className={styles.question} ref={questionRef}>
        {feedback ? (
          <div className={styles.feedbackStage}>
            <p className={styles.eyebrow}>{labels[item.kind]}</p>
            <h1 id={`prompt-${item.id}`} className={styles.feedbackPrompt}>
              {item.prompt}
            </h1>
            {feedback ? (
              <div
                ref={feedbackRef}
                tabIndex={-1}
                className={styles.feedback}
                data-match={feedback.reference_match !== false}
                role="status"
              >
                <div className={styles.feedbackIcon}>
                  {feedback.reference_match === false ? (
                    <Lightbulb size={23} />
                  ) : (
                    <Check size={23} />
                  )}
                </div>
                <div>
                  <h2>
                    {feedback.reference_match === false
                      ? "Here’s a useful way to think about it"
                      : feedback.reference_match === null
                        ? "A thoughtful next step"
                        : "That’s a useful move"}
                  </h2>
                  <p>{feedback.explanation}</p>
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <>
            <div className={styles.promptHeading}>
              <p className={styles.eyebrow}>{labels[item.kind]}</p>
              <h1 ref={headingRef} tabIndex={-1} id={`prompt-${item.id}`}>
                {item.kind === "gap" ? "Choose the missing word" : item.prompt}
              </h1>
            </div>
            {item.kind === "audio" ? (
              <div className={styles.audioCard}>
                <span>
                  <Headphones size={22} />
                  Fictional practice conversation
                </span>
                <audio
                  controls
                  preload="none"
                  src={item.audio_url}
                  aria-label="Play the fictional buyer line"
                />
                <details>
                  <summary>Read the transcript</summary>
                  <p>“{item.spoken}”</p>
                </details>
              </div>
            ) : null}
            {item.kind === "branch" && node ? (
              <div className={styles.conversation}>
                {conversation.length > 0 ? (
                  <details>
                    <summary>
                      {conversation.length} earlier{" "}
                      {conversation.length === 1 ? "exchange" : "exchanges"}
                    </summary>
                    {conversation.map((turn, index) => (
                      <div key={index}>
                        <p className={styles.buyer}>“{turn.buyer}”</p>
                        <p className={styles.reply}>{turn.reply}</p>
                      </div>
                    ))}
                  </details>
                ) : null}
                {!feedback ? (
                  <p className={styles.buyer} aria-live="polite">
                    <span>Buyer</span>“{node.buyer}”
                  </p>
                ) : null}
              </div>
            ) : null}
            {item.kind === "gap" ? (
              <p className={styles.gapPreview} aria-live="polite">
                {item.prompt.split("____")[0]}
                <mark>
                  {options.find((o) => o.id === selections[0])?.text ?? "…"}
                </mark>
                {item.prompt.split("____")[1]}
              </p>
            ) : null}
            {item.kind === "match" ? (
              <div
                className={styles.matchBoard}
                role="group"
                aria-label="Match each statement to a question"
              >
                <div>
                  <h2>What they say</h2>
                  {item.left.map((left) => (
                    <button
                      key={left.id}
                      className={styles.matchTile}
                      data-selected={leftSelected === left.id}
                      data-paired={selections[left.id] >= 0}
                      disabled={frozen}
                      onClick={() => setLeftSelected(left.id)}
                      aria-pressed={leftSelected === left.id}
                    >
                      <span>{left.id + 1}</span>
                      {left.text}
                      {selections[left.id] >= 0 ? (
                        <small>Paired · tap to change</small>
                      ) : null}
                    </button>
                  ))}
                </div>
                <div>
                  <h2>A useful question</h2>
                  {options.map((option) => {
                    const paired = selections.findIndex(
                      (value) => value === option.id,
                    );
                    return (
                      <button
                        key={option.id}
                        className={styles.matchTile}
                        data-paired={paired >= 0}
                        disabled={frozen || leftSelected === null}
                        onClick={() => {
                          if (leftSelected === null) return;
                          const next = Array.from(
                            { length: item.left.length },
                            (_, index) => selections[index] ?? -1,
                          );
                          const previous = next.indexOf(option.id);
                          if (previous >= 0) next[previous] = -1;
                          next[leftSelected] = option.id;
                          choose(next);
                          setLeftSelected(null);
                        }}
                      >
                        {paired >= 0 ? (
                          <span
                            aria-label={`Paired with statement ${paired + 1}`}
                          >
                            {paired + 1}
                          </span>
                        ) : null}
                        {option.text}
                      </button>
                    );
                  })}
                </div>
                <p className={styles.matchHint} role="status">
                  {leftSelected === null
                    ? "Choose a statement on the left, then its question on the right."
                    : `Now choose a question for statement ${leftSelected + 1}.`}
                </p>
              </div>
            ) : sequence ? (
              <div className={styles.sequenceBoard}>
                <div
                  className={styles.answerTray}
                  aria-label="Your assembled response"
                >
                  {selections.length ? (
                    selections.map((id, index) => (
                      <button
                        className={styles.word}
                        key={id}
                        disabled={frozen}
                        onClick={() =>
                          choose(selections.filter((_, i) => i !== index))
                        }
                        aria-label={`Remove ${options.find((o) => o.id === id)?.text}`}
                      >
                        <span>{index + 1}</span>
                        {options.find((o) => o.id === id)?.text}
                        <X size={14} />
                      </button>
                    ))
                  ) : (
                    <p>
                      Tap the pieces below to{" "}
                      {item.kind === "order"
                        ? "put the steps in order"
                        : "build your question"}
                      .
                    </p>
                  )}
                </div>
                <div className={styles.wordBank} aria-label="Available pieces">
                  {options.map((option) => (
                    <button
                      className={styles.word}
                      key={option.id}
                      disabled={frozen || selections.includes(option.id)}
                      onClick={() => choose([...selections, option.id])}
                    >
                      {option.text}
                    </button>
                  ))}
                </div>
                <button
                  className={actionClassName("quiet", styles.textButton)}
                  disabled={frozen || !selections.length}
                  onClick={() => choose([])}
                >
                  <RotateCcw size={15} />
                  Start the order again
                </button>
              </div>
            ) : (
              <fieldset className={styles.options} disabled={frozen}>
                <legend className="sr-only">Choose your response</legend>
                {options.map((option, index) => (
                  <ChoiceOption
                    key={`${path.length}-${option.id}`}
                    name={`response-${item.id}`}
                    value={option.id}
                    checked={selections[0] === option.id}
                    onChange={() => choose([option.id])}
                    marker={String.fromCharCode(65 + index)}
                    label={option.text}
                  />
                ))}
              </fieldset>
            )}
            <div className={styles.hintRow}>
              <button
                className={actionClassName("quiet", styles.textButton)}
                aria-expanded={hint}
                aria-controls={`hint-${item.id}`}
                onClick={() => setHint((v) => !v)}
              >
                <Lightbulb size={17} />
                {hint ? "Hide hint" : "A little hint?"}
              </button>
              {sequence || item.kind === "match" ? (
                <span>
                  {selections.filter((n) => n >= 0).length} of {count} pieces
                </span>
              ) : null}
            </div>
            {hint ? (
              <p className={styles.hint} id={`hint-${item.id}`}>
                {item.hint}
              </p>
            ) : null}
          </>
        )}
        {error ? (
          <p className={styles.requestError} role="alert">
            {error instanceof PracticeRequestError ||
            error instanceof PracticeEngineRequestError
              ? error.message
              : feedback
                ? "Your feedback couldn’t be saved yet. It’s still here—try again."
                : "Couldn’t check that response. Your choices are still here. Try again."}
            {(error instanceof PracticeRequestError ||
              error instanceof PracticeEngineRequestError) &&
            error.status === 401 ? (
              <>
                {" "}
                <Link href="/login">Sign in again</Link>
              </>
            ) : null}
          </p>
        ) : null}
      </div>
    </SessionStep>
  );
}
