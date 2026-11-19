"use client";

/**
 * One of Dipak's lessons (owner's pick, 17 Nov 2026; redesign study §5
 * S3-S4, options L-A, Q-A, D-A, N-A): one scroll in his order, each part with
 * its own look, and a track at the top that shows where you are (never how
 * well you did):
 *   your turn first (Dipak, 16 Nov 2026: the question before the answer),
 *   the customer's words as a bubble and three option cards that all look the
 *   same when picked, his word on the one picked right under it; then his old
 *   and new thinking as two cards and his quick answer in numbered beats;
 *   the Deep lesson as an editorial read; the line to remember as a pocket
 *   card; the Next-call mission as a plan you commit to; what to learn next.
 * Every word with his name is his, from the lesson as served; nothing is
 * added, shortened or scored. Computers add an outline of the parts at left.
 */

import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { CoachMark, PartMark, TopicArt } from "./art";
import { CharacterLoop } from "./characters";
import { LessonVideo } from "./lesson-video";
import { Breadcrumb, ScreenButton, toggle, type Open } from "./bits";
import styles from "./ask-dipak.module.css";
import {
  CoachingError,
  readGrowth,
  setActive,
  type Mission,
} from "./coaching-client";
import { COPY } from "./copy";
import { AskIcon } from "./icons";
import { retryLesson, useLesson } from "./lessons";
import {
  draftFor,
  isDraft,
  lessonChip,
  questionById,
  questionLabel,
  type Lesson,
  type Question,
} from "./library";
import type { Progress } from "./progress";
import { toneOfCategory } from "./tones";

type PartKey = "shift" | "quick" | "turn" | "deep" | "cue" | "mission" | "next";

const PART_LABEL: Readonly<Record<PartKey, string>> = {
  shift: COPY.after,
  quick: COPY.quick,
  turn: COPY.turn,
  deep: COPY.deep,
  cue: COPY.cue,
  mission: COPY.mission,
  next: COPY.related,
};

/**
 * The lesson's parts: the question first, then his answer (Dipak's report
 * 228, 16 Nov 2026: answering before the MCQ is "like telling the answer
 * before the exam"); then old and new thinking (only where he wrote them),
 * his quick answer and the rest in his order.
 */
export function partsOf(lesson: Lesson): PartKey[] {
  return [
    "turn",
    ...(lesson.before && lesson.after ? (["shift"] as const) : []),
    "quick",
    "deep",
    "cue",
    "mission",
    "next",
  ];
}

/** His paragraphs, as he separated them with a blank line. */
export const paragraphs = (text: string): string[] =>
  text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);

/** A quoted question inside his words ("“…?”") stands out; the words stay his. */
function Marked({ text }: { text: string }) {
  const pieces = text.split(/(“[^”]{4,}\?”)/);
  return (
    <>
      {pieces.map((piece, index) =>
        index % 2 ? (
          <span key={index} className={styles.keyQuestion}>
            {piece}
          </span>
        ) : (
          piece
        ),
      )}
    </>
  );
}

/** The scenario: the situation as a bubble, his closing question as the ask. */
export function splitScenario(scenario: string): {
  said: string[];
  ask: string | null;
} {
  const parts = paragraphs(scenario);
  const last = parts.at(-1) ?? "";
  if (parts.length > 1 && /\?$/.test(last) && last.length <= 60)
    return { said: parts.slice(0, -1), ask: last };
  return { said: parts, ask: null };
}

/** His "why" lines, with his "छोटा example:" line apart. */
export function splitWhy(why: string): { lines: string[]; example: string[] } {
  const all = why.split("\n").filter((line) => line.trim());
  return {
    lines: all.filter((line) => !/^छोटा example:/.test(line.trim())),
    example: all.filter((line) => /^छोटा example:/.test(line.trim())),
  };
}

/** "अगली तीन …": the mission counts three calls, shown as three dots. */
export const missionCount = (mission: string): number =>
  /अगली तीन|अगले तीन|next three|\b3\b/i.test(mission) ? 3 : 0;

function Track({ parts, at }: { parts: PartKey[]; at: number }) {
  return (
    <ol className={styles.track} aria-label={COPY.trackLabel}>
      {parts.map((part, index) => (
        <li
          key={part}
          className={styles.trackStep}
          data-state={index < at ? "done" : index === at ? "current" : "ahead"}
          aria-current={index === at ? "step" : undefined}
        >
          <span className={styles.srOnly}>{PART_LABEL[part]}</span>
        </li>
      ))}
    </ol>
  );
}

function Section({
  part,
  children,
  className,
}: {
  part: PartKey;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`${styles.part} ${className ?? ""}`}
      data-part={part}
      id={`part-${part}`}
    >
      {children}
    </section>
  );
}

/** Which part is on screen: the last whose top has passed a third of the view. */
function useCurrentPart(
  root: RefObject<HTMLDivElement | null>,
  count: number,
): number {
  const [at, setAt] = useState(0);
  useEffect(() => {
    const node = root.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const sections = Array.from(
      node.querySelectorAll<HTMLElement>("[data-part]"),
    );
    const seen = new Map<Element, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          seen.set(
            entry.target,
            entry.boundingClientRect.top < window.innerHeight / 3,
          );
        let last = 0;
        sections.forEach((section, index) => {
          if (seen.get(section)) last = index;
        });
        setAt(last);
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1], rootMargin: "0px 0px -66% 0px" },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [root, count]);
  return at;
}

/**
 * How far down the app's own pinned header reaches, so the lesson's bar pins
 * just under it (the phone's top bar stays while reading). Measured, not
 * assumed: it differs by screen and by the workspace switcher's height.
 */
function useBarTop(bar: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const node = bar.current;
    if (!node || typeof document.elementsFromPoint !== "function") return;
    const measure = () => {
      let bottom = 0;
      for (const element of document.elementsFromPoint(
        window.innerWidth / 2,
        2,
      )) {
        if (node.contains(element) || element.contains(node)) continue;
        for (
          let at: Element | null = element;
          at && at !== document.body;
          at = at.parentElement
        ) {
          const position = window.getComputedStyle(at).position;
          if (position === "fixed" || position === "sticky") {
            bottom = Math.max(bottom, at.getBoundingClientRect().bottom);
            break;
          }
        }
      }
      node.style.setProperty("--ad-bar-top", `${Math.round(bottom)}px`);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [bar]);
}

function MissionCard({
  id,
  mission,
  draft,
  committed,
}: {
  id: string;
  mission: string;
  draft: boolean;
  committed: boolean;
}) {
  const [record, setRecord] = useState<Mission | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    readGrowth().then(
      (growth) => {
        if (live)
          setRecord(
            growth.missions.find((item) => item.question_id === id) ?? null,
          );
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [id, committed]);

  const commit = (on: boolean) => {
    setNote(null);
    toggle(id, "mission", on);
    // Committing also makes it one of the three asked about after calls.
    setActive(id, on).then(
      (growth) =>
        setRecord(
          growth.missions.find((item) => item.question_id === id) ?? null,
        ),
      (error: unknown) => {
        if (on && error instanceof CoachingError && error.status === 409)
          setNote(COPY.missionFull);
      },
    );
  };

  const count = missionCount(mission);
  const tried = record?.done_calls ?? 0;
  return (
    <div
      className={`${styles.missionCard} ${committed ? styles.missionOn : ""}`}
      data-mission-state={draft ? "draft" : committed ? "on" : "new"}
    >
      <p className={styles.missionLine}>{mission}</p>
      {count && committed ? (
        <span
          className={styles.dots}
          role="img"
          aria-label={COPY.triedOn(tried)}
        >
          {Array.from({ length: count }, (_, index) => (
            <span key={index} data-filled={index < tried || undefined} />
          ))}
        </span>
      ) : null}
      {draft ? (
        <p className={styles.mutedNote}>{COPY.draftMission}</p>
      ) : committed ? (
        <>
          <p className={styles.missionState}>
            <AskIcon name="check" size={18} />
            {COPY.missionOn}
          </p>
          <p className={styles.mutedNote}>
            {tried ? COPY.triedOn(tried) : COPY.missionAfter} {COPY.checkinNote}
          </p>
          {note ? (
            <p className={styles.mutedNote} role="alert">
              {note}
            </p>
          ) : null}
          <button
            type="button"
            className={styles.smallBtn}
            aria-pressed
            aria-label={COPY.undoMission}
            onClick={() => commit(false)}
          >
            {COPY.missionOff}
          </button>
        </>
      ) : (
        <>
          <p className={styles.mutedNote}>{COPY.missionTodo}</p>
          <button
            type="button"
            className={`${styles.smallBtn} ${styles.primary} ${styles.commit}`}
            aria-pressed={false}
            aria-label={COPY.markMission}
            onClick={() => commit(true)}
          >
            {COPY.missionCommit}
          </button>
        </>
      )}
    </div>
  );
}

export function LessonScreen({
  id,
  progress,
  picked,
  tried,
  onPick,
  deepOpen,
  onDeep,
  open,
  back,
}: {
  id: string;
  progress: Progress;
  picked: number | undefined;
  tried: readonly number[];
  onPick: (choice: number) => void;
  deepOpen: boolean;
  onDeep: () => void;
  open: Open;
  back: () => void;
}) {
  const deepId = useId();
  // Dipak's report 228 note (18 Nov 2026): his answer stays folded until an
  // option is picked, or the reader asks to see it anyway.
  const [peek, setPeek] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  // Dipak's lesson from the API (or the phone's copy of it); a draft is local.
  const served = useLesson(id);
  const question = questionById(id);
  const lesson = question ? (draftFor(id) ?? served.lesson) : null;
  const parts = lesson ? partsOf(lesson) : [];
  const at = useCurrentPart(bodyRef, parts.length);
  useBarTop(barRef);
  if (!question)
    return (
      <>
        <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
        <div className={styles.empty}>{COPY.notFound}</div>
      </>
    );
  const tone = styles[toneOfCategory(question.categoryId)];
  const saved = progress.saved.has(id);
  const bar = (
    <div className={styles.lessonBar} ref={barRef}>
      <Breadcrumb onBack={back}>
        <span className={`${styles.chip} ${tone}`}>{lessonChip(question)}</span>
      </Breadcrumb>
      {lesson ? <Track parts={parts} at={at} /> : null}
      <button
        type="button"
        className={`${styles.mark} ${saved ? styles.active : ""}`}
        aria-pressed={saved}
        aria-label={saved ? COPY.unsave : COPY.save}
        onClick={() => toggle(id, "saved", !saved)}
      >
        <AskIcon name="bookmark" size={21} />
      </button>
    </div>
  );
  if (!lesson)
    return (
      <>
        {bar}
        <div className={styles.questionHero}>
          <h2 className={styles.pageTitle}>{questionLabel(question)}</h2>
          <p className={styles.pageSub}>{COPY.parts}</p>
        </div>
        {served.status === "failed" ? (
          <div className={styles.panel} data-lesson-state="failed">
            <p className={styles.copy}>{COPY.loadFailed}</p>
            <button
              type="button"
              className={`${styles.smallBtn} ${styles.primary}`}
              onClick={() => void retryLesson(id)}
            >
              {COPY.retry}
            </button>
          </div>
        ) : (
          <div
            className={styles.panel}
            data-lesson-state="loading"
            role="status"
          >
            <p className={styles.copy}>{COPY.loading}</p>
          </div>
        )}
      </>
    );

  const draft = isDraft(id);
  const committed = progress.missions.has(id);
  const related = lesson.next
    .map((code) => questionById(code))
    .filter((item): item is Question => Boolean(item));
  const scenario = splitScenario(lesson.scenario);
  const seen = new Set(tried);
  const allSeen = [0, 1, 2].every((index) => seen.has(index));
  const answerOpen = peek || picked !== undefined || seen.size > 0;

  const jump = (part: PartKey) =>
    document
      .getElementById(`part-${part}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <>
      {bar}
      <p className={styles.nowLine} aria-live="polite">
        {`${COPY.now}: ${PART_LABEL[parts[at] ?? "quick"]} · ${at + 1} of ${parts.length}`}
      </p>
      <div className={`${styles.lessonGrid} ${tone}`}>
        <nav className={styles.outline} aria-label={COPY.trackLabel}>
          {parts.map((part, index) => (
            <button
              key={part}
              type="button"
              className={styles.outlineItem}
              data-state={
                index < at ? "done" : index === at ? "current" : "ahead"
              }
              onClick={() => jump(part)}
            >
              <PartMark part={part} size={20} />
              {PART_LABEL[part]}
            </button>
          ))}
        </nav>
        <div className={styles.lessonBody} ref={bodyRef}>
          <div className={`${styles.lessonTitle} ${tone}`}>
            <div className={styles.lessonTitleWords}>
              <h2 className={styles.pageTitle}>
                {/* The homepage's wording if it has one, else his doc's, as served. */}
                {questionLabel(question) !== question.title
                  ? questionLabel(question)
                  : (served.title ?? question.title)}
              </h2>
              <p className={styles.pageSub}>{COPY.parts}</p>
              {draft ? (
                <p className={styles.draftTag} data-draft="">
                  {COPY.draftTag}
                </p>
              ) : null}
            </div>
            <span className={styles.lessonArt}>
              <TopicArt category={question.categoryId} size={44} />
            </span>
          </div>

          <Section part="turn">
            <div className={styles.partHead}>
              <PartMark part="turn" />
              <h3 className={styles.sectionH}>{COPY.turn}</h3>
            </div>
            <div className={styles.scene}>
              {/* The hook: Rohit says it (character kit v2: Aman and Rohit
                  open and close a lesson, never the teaching middle). */}
              <div className={styles.sceneWho}>
                <CharacterLoop loop="hook" size={56} />
                <div className={styles.sceneWords}>
                  {scenario.said.map((line) => (
                    <p key={line} className={styles.sceneBubble}>
                      {line}
                    </p>
                  ))}
                </div>
              </div>
              {scenario.ask ? (
                <p className={styles.sceneAsk}>{scenario.ask}</p>
              ) : null}
            </div>
            {picked === undefined ? (
              <p className={styles.pickHint}>{COPY.pickHint}</p>
            ) : null}
            <div className={styles.options}>
              {lesson.options.map((option, index) => {
                const letter = "ABC"[index];
                const chosen = picked === index;
                const why = chosen ? splitWhy(option[1]) : null;
                return (
                  <div key={option[0]} className={styles.optionWrap}>
                    <button
                      type="button"
                      className={`${styles.mcq} ${chosen ? styles.selected : ""}`}
                      aria-pressed={chosen}
                      data-letter={letter}
                      onClick={() => onPick(index)}
                    >
                      {/* The tile draws its letter; readers hear "A. …" once. */}
                      <span
                        className={styles.letter}
                        data-letter={letter}
                        aria-hidden="true"
                      />
                      <span className={styles.optionWords}>
                        <span className={styles.srOnly}>{`${letter}. `}</span>
                        {option[0]}
                        {seen.has(index) && !chosen ? (
                          <span className={styles.seenLine}>{option[2]}</span>
                        ) : null}
                      </span>
                      {seen.has(index) && !chosen ? (
                        <span className={styles.seenTag}>{COPY.seen}</span>
                      ) : (
                        <span className={styles.radio} aria-hidden="true" />
                      )}
                    </button>
                    {why ? (
                      <div className={styles.feedback} role="status">
                        <div className={styles.coachHead}>
                          <CoachMark size="sm" />
                          <strong>{COPY.feedback}</strong>
                        </div>
                        <p className={styles.feedbackLabel}>{COPY.why}</p>
                        {why.lines.map((line) => (
                          <p key={line} className={styles.feedbackLine}>
                            {line}
                          </p>
                        ))}
                        {why.example.length ? (
                          <div className={styles.example}>
                            {why.example.map((line) => (
                              <p key={line} className={styles.feedbackLine}>
                                {line}
                              </p>
                            ))}
                          </div>
                        ) : null}
                        {/* His takeaway with his own label ("Better सोच"). */}
                        <p className={styles.take} data-takeaway="">
                          {`${option[3] ?? COPY.better}: ${option[2]}`}
                        </p>
                        {allSeen ? (
                          <p className={styles.mutedNote}>{COPY.allSeen}</p>
                        ) : (
                          <p className={styles.compareLine}>
                            {COPY.compare}
                            {[0, 1, 2]
                              .filter((other) => other !== index)
                              .map((other) => (
                                <button
                                  key={other}
                                  type="button"
                                  className={styles.compareLink}
                                  aria-label={`${COPY.seeOption} ${"ABC"[other]}`}
                                  onClick={() => onPick(other)}
                                >
                                  {"ABC"[other]}
                                </button>
                              ))}
                          </p>
                        )}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </Section>

          {!answerOpen ? (
            <div className={styles.answerGate} data-answer-gate="">
              <PartMark part="quick" size={28} />
              <p className={styles.gateText}>{COPY.gate}</p>
              <button
                type="button"
                className={styles.smallBtn}
                onClick={() => setPeek(true)}
              >
                {COPY.gatePeek}
              </button>
            </div>
          ) : null}

          {answerOpen && lesson.before && lesson.after ? (
            <Section part="shift">
              <div className={styles.partHead}>
                <PartMark part="shift" />
                <h3 className={styles.sectionH}>{COPY.shift}</h3>
              </div>
              {/* His before and after lines, word for word (his doc's opening). */}
              <div className={styles.shift} data-mindset="">
                <div className={styles.oldThought}>
                  <p className={styles.thoughtLabel}>
                    <AskIcon name="ban" size={20} />
                    {COPY.before}
                  </p>
                  <p className={styles.thought}>{lesson.before}</p>
                </div>
                <span className={styles.shiftArrow} aria-hidden="true">
                  <AskIcon name="down" size={20} />
                </span>
                <div className={styles.newThought}>
                  <p className={styles.thoughtLabel}>
                    <AskIcon name="spark" size={20} />
                    {COPY.after}
                  </p>
                  <p className={styles.thought}>{lesson.after}</p>
                </div>
              </div>
            </Section>
          ) : null}

          {answerOpen ? (
            <>
              <Section part="quick" className={styles.quickCard}>
                <div className={styles.coachHead}>
                  <CoachMark size="sm" />
                  <h3 className={styles.sectionH}>{COPY.quick}</h3>
                </div>
                <ol className={styles.beats}>
                  {paragraphs(lesson.quick).map((beat, index) => (
                    <li key={beat} className={styles.beat}>
                      <span className={styles.beatDot} aria-hidden="true">
                        {index + 1}
                      </span>
                      <p className={styles.beatText}>
                        <Marked text={beat} />
                      </p>
                    </li>
                  ))}
                </ol>
                {/* The studio's video of this lesson, where there is one: it
                    teaches the answer, so it waits for the answer too. */}
                <LessonVideo id={id} />
              </Section>

              <Section part="deep">
                <button
                  type="button"
                  className={styles.fold}
                  aria-expanded={deepOpen}
                  aria-controls={deepId}
                  onClick={onDeep}
                >
                  <span
                    className={`${styles.foldIcon} ${tone}`}
                    aria-hidden="true"
                  >
                    <PartMark part="deep" size={24} />
                  </span>
                  <span className={styles.foldMain}>
                    <strong>{COPY.deep}</strong>
                    <small>{COPY.deepSub}</small>
                  </span>
                  <span
                    className={styles.foldArrow}
                    data-open={deepOpen || undefined}
                  >
                    <AskIcon name="right" size={22} />
                  </span>
                </button>
                {deepOpen ? (
                  <div className={styles.deep} id={deepId}>
                    {lesson.deep.map((paragraph, index) => (
                      <p
                        key={`${index}-${paragraph}`}
                        className={index === 0 ? styles.pull : undefined}
                      >
                        {paragraph}
                      </p>
                    ))}
                    <button
                      type="button"
                      className={styles.smallBtn}
                      onClick={onDeep}
                    >
                      {COPY.deepClose}
                    </button>
                  </div>
                ) : null}
              </Section>

              <Section part="cue">
                <div className={styles.pocket}>
                  <span className={styles.pocketIcon} aria-hidden="true">
                    <PartMark part="cue" size={24} />
                  </span>
                  <div>
                    <h3 className={styles.pocketLabel}>{COPY.cue}</h3>
                    <p className={styles.cue}>{lesson.cue}</p>
                  </div>
                  {/* The payoff: Aman, who takes this line to his next call. */}
                  <CharacterLoop
                    loop="payoff"
                    size={56}
                    className={styles.pocketWho}
                  />
                </div>
              </Section>

              <Section part="mission">
                <div className={styles.coachHead}>
                  <PartMark part="mission" />
                  <h3 className={styles.sectionH}>{COPY.mission}</h3>
                </div>
                <MissionCard
                  id={id}
                  mission={lesson.mission}
                  draft={draft}
                  committed={committed}
                />
              </Section>
            </>
          ) : null}

          <Section part="next">
            <div className={styles.partHead}>
              <PartMark part="next" />
              <h3 className={styles.sectionH}>{COPY.related}</h3>
            </div>
            <div className={styles.nextList}>
              {related.map((item) => (
                <ScreenButton
                  key={item.id}
                  view={{ kind: "lesson", id: item.id }}
                  open={open}
                  className={`${styles.related} ${styles[toneOfCategory(item.categoryId)]}`}
                >
                  <span className={styles.relatedArt} aria-hidden="true">
                    <TopicArt category={item.categoryId} size={28} />
                  </span>
                  <span>{questionLabel(item)}</span>
                  <AskIcon name="right" size={17} />
                </ScreenButton>
              ))}
            </div>
          </Section>
        </div>
        {/* Wide computers (X-B): the line to remember and the mission kept
            beside the reading column once his answer is open. */}
        {answerOpen ? (
          <aside className={styles.rail} aria-label={COPY.railLabel}>
            <div className={styles.railCard}>
              <p className={styles.railHead}>
                <PartMark part="cue" size={20} />
                {COPY.cue}
              </p>
              <p className={styles.railCue}>{lesson.cue}</p>
            </div>
            <button
              type="button"
              className={`${styles.railCard} ${styles.railMission}`}
              onClick={() => jump("mission")}
            >
              <span className={styles.railHead}>
                <PartMark part="mission" size={20} />
                {COPY.mission}
              </span>
              <span className={styles.railLine}>{lesson.mission}</span>
              <span className={styles.railState}>
                {committed ? COPY.missionOn : COPY.missionCommit}
              </span>
            </button>
          </aside>
        ) : null}
      </div>
    </>
  );
}
