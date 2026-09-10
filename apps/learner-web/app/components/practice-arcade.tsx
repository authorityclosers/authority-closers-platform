"use client";

import Image from "next/image";
import {
  ActionButton,
  actionClassName,
  ChoiceOption,
  FocusSession,
  SessionStep,
  type PracticeCompanionKind,
} from "@ac/ui";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  Headphones,
  Lightbulb,
  Link2,
  LoaderCircle,
  RotateCcw,
  Trophy,
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
import { PracticeArt } from "./practice-art";
import { PracticeCompanionStage } from "./practice-companion-stage";
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
const formats: Record<PracticeSummary["kind"], string> = {
  choice: "Next move",
  gap: "Fill the gap",
  match: "Matching pairs",
  build: "Question builder",
  order: "Sequence",
  audio: "Listening",
  branch: "Conversation",
};
const cardTone = (color: string) =>
  ["cobalt", "mint", "lilac", "amber"].includes(color) ? color : "cobalt";

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
  // Feature content returned by this academy's catalog, never an assumed set.
  const featured =
    catalog.find((item) => item.id === "next-move") ?? catalog[0];
  return (
    <div className={styles.arcade}>
      <header className={styles.hubHeader}>
        <h1 id="practice-title">Practice Arcade</h1>
        {durable ? (
          <Link
            className={styles.leaderboardShortcut}
            href="/leaderboard"
            aria-label="Academy leaderboard"
            title="Academy leaderboard"
          >
            <Trophy size={21} aria-hidden="true" />
            <span>Leaderboard</span>
          </Link>
        ) : (
          <span className={styles.previewBadge}>Preview</span>
        )}
      </header>
      {recognition}
      {featured && !durable ? (
        <section
          className={styles.featured}
          aria-labelledby="practice-featured-title"
        >
          <span className={styles.featuredArt}>
            <PracticeArt kind={featured.kind} />
          </span>
          <div>
            <p className={styles.skill}>Your next small win</p>
            <h2 id="practice-featured-title">{featured.title}</h2>
            <p>
              {featured.item_count} prompts · About {featured.estimated_minutes}{" "}
              min · At your pace
            </p>
          </div>
          <Link className={actionClassName()} href={practiceHref(featured.id)}>
            Start practice <ArrowRight size={18} />
          </Link>
        </section>
      ) : !featured ? (
        <section
          className={styles.emptyLibrary}
          aria-labelledby="practice-empty-title"
        >
          <h2 id="practice-empty-title">Your next practice is on its way</h2>
          <p>
            There are no practice sets available here yet. Keep going with your
            academy’s lessons.
          </p>
          <Link className={actionClassName("secondary")} href="/learning">
            Continue learning <ArrowRight size={18} />
          </Link>
        </section>
      ) : null}
      {catalog.length > 0 ? (
        <section aria-labelledby="practice-library-title">
          <div className={styles.sectionHeading}>
            <div>
              <h2 id="practice-library-title">Pick your next challenge</h2>
              <p>Different skills. A fresh way to practise.</p>
            </div>
            <span>
              {catalog.length} {catalog.length === 1 ? "set" : "sets"} to
              explore
            </span>
          </div>
          <div className={styles.library}>
            {catalog.map((item) => (
              <PracticeCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      ) : null}
      <p className={styles.previewNote}>
        {durable
          ? "Draft practice content is awaiting coach review. Your practice responses and earned rewards are saved separately from course progress and assessments."
          : "You’re exploring draft practice content awaiting coach review. This session stays in this tab and doesn’t change course progress, streaks, or rankings."}
      </p>
    </div>
  );
}

function PracticeCard({ item }: { item: PracticeSummary }) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const surface = dialog.current;
    const opener = trigger.current;
    const previousOverflow = document.body.style.overflow;
    surface?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
      surface?.close();
      opener?.focus({ preventScroll: true });
    };
  }, [open]);
  return (
    <article className={styles.setCard} data-color={cardTone(item.color)}>
      <Link
        href={practiceHref(item.id)}
        className={styles.setLink}
        aria-label={`${formats[item.kind]}: ${item.title}`}
      >
        <div className={styles.artTile}>
          <PracticeArt kind={item.kind} />
        </div>
        <div className={styles.setCopy}>
          <h3>{item.title}</h3>
          <div className={styles.setMeta}>
            <span>
              <Clock3 size={13} aria-hidden="true" />
              {item.estimated_minutes} min
            </span>
            <span>{item.item_count} prompts</span>
          </div>
        </div>
        <span className={styles.cardArrow}>
          <span>Play</span>
          <ArrowRight size={18} aria-hidden="true" />
        </span>
      </Link>
      <button
        ref={trigger}
        className={styles.cardInfo}
        type="button"
        aria-label={`About ${item.title}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? `game-dialog-${item.id}` : undefined}
        onClick={() => setOpen(true)}
      >
        <span aria-hidden="true">i</span>
      </button>
      {open ? (
        <dialog
          ref={dialog}
          id={`game-dialog-${item.id}`}
          className={styles.gameInfo}
          aria-labelledby={`game-info-${item.id}`}
          aria-describedby={`game-description-${item.id}`}
          onCancel={(event) => {
            event.preventDefault();
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
        >
          <button
            className={styles.infoClose}
            type="button"
            aria-label="Close practice details"
            onClick={() => setOpen(false)}
          >
            <X size={20} />
          </button>
          <div className={styles.infoArt}>
            <PracticeArt kind={item.kind} />
          </div>
          <p className={styles.skill}>
            {item.skill} · {formats[item.kind]}
          </p>
          <h2 id={`game-info-${item.id}`}>{item.title}</h2>
          <p id={`game-description-${item.id}`}>{item.description}</p>
          <p className={styles.setMeta}>
            {item.item_count} prompts · About {item.estimated_minutes} minutes
          </p>
          <Link className={actionClassName()} href={practiceHref(item.id)}>
            Start practice <ArrowRight size={18} />
          </Link>
        </dialog>
      ) : null}
    </article>
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
  companion = "echo",
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
  companion?: PracticeCompanionKind;
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
      className={styles.playStep}
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
      <div
        className={styles.question}
        ref={questionRef}
        data-feedback-tone={
          feedback
            ? feedback.reference_match === false
              ? "retry"
              : feedback.reference_match === true
                ? "success"
                : "reflection"
            : undefined
        }
      >
        {feedback ? (
          <div className={styles.feedbackStage}>
            <div className={styles.reactionScene} aria-hidden="true">
              <div className={styles.reactionHalo} />
              {feedback.reference_match === true ? (
                <div className={styles.confetti}>
                  {Array.from({ length: 12 }, (_, index) => (
                    <i
                      key={index}
                      style={{ "--particle": index } as React.CSSProperties}
                    />
                  ))}
                </div>
              ) : null}
              <PracticeCompanionStage
                variant={companion}
                mood={
                  feedback.reference_match === false
                    ? "encourage"
                    : feedback.reference_match === true
                      ? "celebrate"
                      : "ready"
                }
                size={190}
              />
              <span className={styles.reactionBadge}>
                {feedback.reference_match === false ? (
                  <RotateCcw size={23} />
                ) : feedback.reference_match === true ? (
                  <Check size={25} strokeWidth={3} />
                ) : (
                  <Lightbulb size={23} />
                )}
              </span>
            </div>
            <div
              ref={feedbackRef}
              tabIndex={-1}
              className={styles.feedback}
              data-match={feedback.reference_match !== false}
              role="status"
            >
              <div>
                <p className={styles.feedbackLabel}>
                  {feedback.reference_match === false
                    ? "Not quite"
                    : feedback.reference_match === true
                      ? "Good connection"
                      : "Keep exploring"}
                </p>
                <h1 id={`prompt-${item.id}`}>
                  {feedback.reference_match === false
                    ? "Try another approach"
                    : feedback.reference_match === null
                      ? "A thoughtful next step"
                      : "Nicely done!"}
                </h1>
                <p>
                  {feedback.reference_match === false
                    ? "Your response differs from the reference. Give it another try."
                    : feedback.explanation}
                </p>
              </div>
            </div>
            {feedback.reference_match === false ? (
              <details className={styles.promptDetails}>
                <summary>Reference explanation</summary>
                <p>{feedback.explanation}</p>
              </details>
            ) : null}
            <details className={styles.promptDetails}>
              <summary>Review the prompt</summary>
              <p>{item.prompt}</p>
            </details>
          </div>
        ) : (
          <>
            <div className={styles.promptHeading}>
              <span className={styles.promptArt} aria-hidden="true">
                <PracticeArt kind={item.kind} />
              </span>
              <div>
                <p className={styles.eyebrow}>
                  {item.kind === "match" ? "Link each pair" : labels[item.kind]}
                </p>
                <h1 ref={headingRef} tabIndex={-1} id={`prompt-${item.id}`}>
                  {item.kind === "gap"
                    ? "Choose the missing word"
                    : item.kind === "match"
                      ? "Connect the pairs"
                      : item.prompt}
                </h1>
              </div>
            </div>
            {item.kind === "match" ? (
              <details className={styles.promptDetails}>
                <summary>How to play</summary>
                <p>{item.prompt}</p>
              </details>
            ) : null}
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
                      data-pair={
                        selections[left.id] >= 0 ? left.id % 3 : undefined
                      }
                      disabled={frozen}
                      onClick={() => {
                        onInteraction?.("select");
                        setLeftSelected(left.id);
                      }}
                      aria-pressed={leftSelected === left.id}
                      aria-label={`${left.text}${selections[left.id] >= 0 ? `. Paired with ${options.find((option) => option.id === selections[left.id])?.text}. Select to change.` : ""}`}
                    >
                      <span aria-hidden="true">{left.id + 1}</span>
                      {left.text}
                      {selections[left.id] >= 0 ? (
                        <Link2
                          className={styles.pairLink}
                          size={16}
                          aria-hidden="true"
                        />
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
                        data-pair={paired >= 0 ? paired % 3 : undefined}
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
                        {paired >= 0 ? (
                          <Link2
                            className={styles.pairLink}
                            size={16}
                            aria-hidden="true"
                          />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
                <p className={styles.matchHint} role="status">
                  {leftSelected === null
                    ? `${selections.filter((value) => value >= 0).length}/${item.left.length} linked. Pick a statement, then a question.`
                    : `Choose a question for ${leftSelected + 1}.`}
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
