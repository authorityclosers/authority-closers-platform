"use client";

/**
 * Ask Dipak (Dipak's spec and clickable sample, 13 Nov 2026): his sales
 * library as the tab's home. Home → a topic or category → a question →
 * its lesson (quick answer, your turn with three options and Dipak's word on
 * each, the Deep lesson, the line to remember, the Next-call mission, what
 * to learn next); Search and Saved lessons beside them. Everything shown is
 * Dipak's own text; a question without a lesson yet says so.
 */

import { useSearchParams } from "next/navigation";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { notify } from "../notice-center";
import { useTabAgain } from "../shell/tab-again";
import styles from "./ask-dipak.module.css";
import { COPY } from "./copy";
import { AskIcon } from "./icons";
import {
  CATEGORIES,
  CATEGORY_ICONS,
  CATEGORY_LABELS,
  FEATURED,
  QUESTIONS,
  REAL_SITUATIONS,
  categoryById,
  categoryQuestions,
  featuredById,
  featuredQuestions,
  lessonChip,
  lessonFor,
  questionById,
  questionLabel,
  searchQuestions,
  type Question,
} from "./library";
import {
  arrive,
  go,
  goBack,
  onLeave,
  parseView,
  rememberScroll,
  restart,
  scrollFor,
  startTrail,
  useSearchWords,
  viewHref,
  type AskView,
} from "./nav";
import { loadProgress, setItem, useProgress, type Progress } from "./progress";

/** The element that scrolls this page: the shell's panel, or the window. */
function scrollerOf(node: HTMLElement | null): Element {
  for (let at = node?.parentElement ?? null; at; at = at.parentElement) {
    const overflow = window.getComputedStyle(at).overflowY;
    if (
      (overflow === "auto" || overflow === "scroll") &&
      at.scrollHeight > at.clientHeight
    )
      return at;
  }
  return document.scrollingElement ?? document.documentElement;
}

type Open = (view: AskView) => void;

/** A row or card that opens a screen: a real link, moved in place. */
function ScreenButton({
  view,
  open,
  className,
  children,
  label,
}: {
  view: AskView;
  open: Open;
  className: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <a
      className={className}
      href={viewHref(view)}
      aria-label={label}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        event.preventDefault();
        open(view);
      }}
    >
      {children}
    </a>
  );
}

function QuestionRow({ question, open }: { question: Question; open: Open }) {
  return (
    <ScreenButton
      view={{ kind: "lesson", id: question.id }}
      open={open}
      className={styles.questionRow}
    >
      <span>{questionLabel(question)}</span>
      <AskIcon name="right" size={18} />
    </ScreenButton>
  );
}

function Breadcrumb({
  onBack,
  children,
}: {
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className={styles.breadcrumb} onClick={onBack}>
      <AskIcon name="left" size={19} />
      {children}
    </button>
  );
}

function Tools({ view, open }: { view: AskView; open: Open }) {
  return (
    <div className={styles.deskTools}>
      <button
        type="button"
        className={styles.tool}
        aria-label={COPY.searchTool}
        onClick={() => open({ kind: "search" })}
      >
        <AskIcon name="search" size={22} />
      </button>
      <button
        type="button"
        className={styles.tool}
        aria-label={COPY.savedTool}
        aria-current={view.kind === "saved" ? "page" : undefined}
        onClick={() => open({ kind: "saved" })}
      >
        <AskIcon name="bookmark" size={22} />
      </button>
    </div>
  );
}

function HomeScreen({ open }: { open: Open }) {
  return (
    <>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>{COPY.eyebrow}</p>
        <h2 className={styles.hello}>{COPY.hello}</h2>
        {COPY.intro.map((line) => (
          <p key={line}>{line}</p>
        ))}
        <p>
          <strong>{COPY.introAsk}</strong>
        </p>
      </section>
      <ScreenButton
        view={{ kind: "search" }}
        open={open}
        className={styles.searchHome}
      >
        <AskIcon name="search" size={21} />
        <span>{COPY.searchPlaceholder}</span>
      </ScreenButton>
      <div className={styles.hrow}>
        <h2>{COPY.explore}</h2>
        <ScreenButton
          view={{ kind: "topics" }}
          open={open}
          className={styles.see}
        >
          {COPY.seeAll}
          <AskIcon name="right" size={16} />
        </ScreenButton>
      </div>
      <div className={styles.topicGrid}>
        {FEATURED.map((topic) => (
          <ScreenButton
            key={topic.id}
            view={{ kind: "topic", id: topic.id }}
            open={open}
            className={styles.topicCard}
          >
            <span className={styles.topicIcon}>
              <AskIcon name={topic.icon} />
            </span>
            <span className={styles.topicTitle}>{topic.name}</span>
            <span className={styles.topicSub}>{topic.sub}</span>
            <span className={styles.arr}>
              <AskIcon name="right" size={18} />
            </span>
          </ScreenButton>
        ))}
      </div>
      <div className={`${styles.hrow} ${styles.realTitle}`}>
        <h2>{COPY.real}</h2>
      </div>
      <div className={styles.realList}>
        {REAL_SITUATIONS.map((id) => {
          const question = questionById(id);
          if (!question) return null;
          return (
            <ScreenButton
              key={id}
              view={{ kind: "lesson", id }}
              open={open}
              className={styles.entry}
            >
              <span className={styles.entryCopy}>
                <span className={styles.entryTitle}>
                  {questionLabel(question)}
                </span>
                <span className={styles.entryMeta}>{COPY.parts}</span>
              </span>
              <AskIcon name="right" size={18} />
            </ScreenButton>
          );
        })}
      </div>
      <p className={styles.notice}>{COPY.notice}</p>
    </>
  );
}

function TopicsScreen({ open, back }: { open: Open; back: () => void }) {
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
      <h2 className={styles.pageTitle}>{COPY.allTitle}</h2>
      <p className={styles.pageSub}>{COPY.allSub}</p>
      <div className={`${styles.topicGrid} ${styles.browseGrid}`}>
        {CATEGORIES.map((category) => (
          <ScreenButton
            key={category.id}
            view={{ kind: "category", id: category.id }}
            open={open}
            className={styles.topicCard}
          >
            <span className={styles.topicIcon}>
              <AskIcon name={CATEGORY_ICONS[category.id] ?? "layers"} />
            </span>
            <span className={styles.topicTitle}>{category.name}</span>
            <span className={styles.topicSub}>
              {CATEGORY_LABELS[category.id]}
            </span>
            <span className={styles.arr}>
              <AskIcon name="right" size={18} />
            </span>
          </ScreenButton>
        ))}
      </div>
    </>
  );
}

function TopicScreen({
  id,
  open,
  back,
}: {
  id: string;
  open: Open;
  back: () => void;
}) {
  const topic = featuredById(id) ?? FEATURED[0];
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
      <div className={styles.chip}>{COPY.topicChip}</div>
      <h2 className={styles.pageTitle}>{topic.name}</h2>
      <p className={styles.pageSub}>
        {topic.sub} · {COPY.topicSub}
      </p>
      {featuredQuestions(topic).map((question) => (
        <QuestionRow key={question.id} question={question} open={open} />
      ))}
    </>
  );
}

function CategoryScreen({
  id,
  open,
  back,
}: {
  id: string;
  open: Open;
  back: () => void;
}) {
  const category = categoryById(id) ?? CATEGORIES[0];
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.allTitle}</Breadcrumb>
      <div className={styles.chip}>{CATEGORY_LABELS[category.id]}</div>
      <h2 className={styles.pageTitle}>{category.name}</h2>
      <p className={styles.pageSub}>{COPY.categorySub}</p>
      {categoryQuestions(category).map((question) => (
        <QuestionRow key={question.id} question={question} open={open} />
      ))}
    </>
  );
}

function SearchScreen({
  query,
  onQuery,
  open,
  back,
  inputRef,
}: {
  query: string;
  onQuery: (query: string) => void;
  open: Open;
  back: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const results = searchQuestions(query);
  const field = useId();
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
      <h2 className={styles.pageTitle}>{COPY.searchTitle}</h2>
      <p className={styles.pageSub}>{COPY.searchSub}</p>
      <label className={styles.searchField} htmlFor={field}>
        <AskIcon name="search" size={21} />
        <input
          ref={inputRef}
          id={field}
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          placeholder={COPY.searchPlaceholder}
          aria-label={COPY.searchPlaceholder}
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </label>
      <div aria-live="polite" data-results="">
        {results.length ? (
          results.map((question) => (
            <QuestionRow key={question.id} question={question} open={open} />
          ))
        ) : (
          <div className={styles.empty}>
            <strong>{COPY.noMatch}</strong>
            {COPY.noMatchHint}
          </div>
        )}
      </div>
    </>
  );
}

function SavedScreen({
  progress,
  open,
  back,
}: {
  progress: Progress;
  open: Open;
  back: () => void;
}) {
  const saved = QUESTIONS.filter((question) => progress.saved.has(question.id));
  const waiting = progress.status === "idle" || progress.status === "loading";
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
      <h2 className={styles.pageTitle}>{COPY.savedTitle}</h2>
      <p className={styles.pageSub}>{COPY.savedSub}</p>
      {saved.length ? (
        saved.map((question) => (
          <QuestionRow key={question.id} question={question} open={open} />
        ))
      ) : waiting ? (
        <div className={styles.rowSkeleton} aria-busy="true" />
      ) : progress.status === "failed" ? (
        <div className={styles.empty}>
          <strong>Couldn&rsquo;t open your saved lessons</strong>
          Check your connection, then try again.
          <button
            type="button"
            className={styles.smallBtn}
            onClick={() => void loadProgress()}
          >
            Try again
          </button>
        </div>
      ) : (
        <div className={styles.empty}>
          <strong>{COPY.savedEmpty}</strong>
          {COPY.savedEmptyHint}
        </div>
      )}
    </>
  );
}

function saveFailed(retry: () => void) {
  notify({
    id: "ask-dipak-save",
    tone: "error",
    title: "Couldn’t save that",
    message: "Check your connection, then try again.",
    action: { label: "Try again", run: retry },
  });
}

function toggle(id: string, item: "saved" | "mission", on: boolean) {
  void setItem(id, item, on).then((done) => {
    if (!done) saveFailed(() => toggle(id, item, on));
  });
}

function LessonScreen({
  id,
  progress,
  picked,
  onPick,
  deepOpen,
  onDeep,
  open,
  back,
}: {
  id: string;
  progress: Progress;
  picked: number | undefined;
  onPick: (choice: number) => void;
  deepOpen: boolean;
  onDeep: () => void;
  open: Open;
  back: () => void;
}) {
  const deepId = useId();
  const question = questionById(id);
  if (!question)
    return (
      <>
        <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
        <div className={styles.empty}>{COPY.notFound}</div>
      </>
    );
  const lesson = lessonFor(id);
  const head = (
    <Breadcrumb onBack={back}>
      <span className={styles.chip}>{lessonChip(question)}</span>
    </Breadcrumb>
  );
  if (!lesson)
    return (
      <>
        {head}
        <div className={styles.questionHero}>
          <h2 className={styles.pageTitle}>{questionLabel(question)}</h2>
          <p className={styles.pageSub}>{COPY.notReadyChip}</p>
        </div>
        <div className={styles.panel} data-lesson-state="not-ready">
          <p className={styles.copy}>{COPY.notReady}</p>
          <button type="button" className={styles.smallBtn} onClick={back}>
            {COPY.backToQuestions}
          </button>
        </div>
      </>
    );
  const saved = progress.saved.has(id);
  const done = progress.missions.has(id);
  const chosen = picked === undefined ? null : lesson.options[picked];
  const related = lesson.next
    .map((code) => questionById(code))
    .filter((item): item is Question => Boolean(item));
  return (
    <>
      {head}
      <div className={styles.detailTop}>
        <div className={styles.questionHero}>
          <h2 className={styles.pageTitle}>{questionLabel(question)}</h2>
          <p className={styles.pageSub}>{COPY.parts}</p>
        </div>
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

      <h3 className={styles.sectionH}>{COPY.quick}</h3>
      <div className={styles.panel}>
        <p className={styles.copy}>{lesson.quick}</p>
      </div>

      <h3 className={styles.sectionH}>{COPY.turn}</h3>
      <div className={styles.panel}>
        <p className={styles.copy}>{lesson.scenario}</p>
      </div>
      <div className={styles.options}>
        {lesson.options.map((option, index) => (
          <button
            key={option[0]}
            type="button"
            className={`${styles.mcq} ${picked === index ? styles.selected : ""}`}
            aria-pressed={picked === index}
            onClick={() => onPick(index)}
          >
            <span className={styles.radio} aria-hidden="true" />
            <span>{`${"ABC"[index]}. ${option[0]}`}</span>
          </button>
        ))}
      </div>
      {chosen ? (
        <div className={styles.feedback} role="status">
          <strong>{COPY.feedback}</strong>
          <p>{chosen[1]}</p>
          <div className={styles.take}>{chosen[2]}</div>
          <p className={styles.mutedNote}>{COPY.compare}</p>
        </div>
      ) : null}

      <button
        type="button"
        className={styles.fold}
        aria-expanded={deepOpen}
        aria-controls={deepId}
        onClick={onDeep}
      >
        <AskIcon name="layers" size={22} />
        <span className={styles.foldMain}>
          <strong>{COPY.deep}</strong>
          <small>{COPY.deepSub}</small>
        </span>
        <span className={styles.foldArrow} data-open={deepOpen || undefined}>
          <AskIcon name="right" size={22} />
        </span>
      </button>
      {deepOpen ? (
        <div className={styles.deep} id={deepId}>
          {lesson.deep.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      ) : null}

      <h3 className={styles.sectionH}>{COPY.cue}</h3>
      <div className={styles.panel}>
        <p className={styles.cue}>{lesson.cue}</p>
      </div>

      <h3 className={styles.sectionH}>{COPY.mission}</h3>
      <div className={`${styles.panel} ${styles.mission}`}>
        <button
          type="button"
          className={`${styles.check} ${done ? styles.done : ""}`}
          aria-pressed={done}
          aria-label={done ? COPY.undoMission : COPY.markMission}
          onClick={() => toggle(id, "mission", !done)}
        >
          {done ? <AskIcon name="check" size={19} /> : null}
        </button>
        <div className={styles.missionText}>
          {lesson.mission}
          <p className={styles.mutedNote}>
            {done ? COPY.missionDone : COPY.missionTodo}
          </p>
        </div>
      </div>

      <h3 className={styles.sectionH}>{COPY.related}</h3>
      <div className={`${styles.panel} ${styles.relatedList}`}>
        {related.map((item) => (
          <ScreenButton
            key={item.id}
            view={{ kind: "lesson", id: item.id }}
            open={open}
            className={styles.related}
          >
            <span>{questionLabel(item)}</span>
            <AskIcon name="right" size={17} />
          </ScreenButton>
        ))}
      </div>
    </>
  );
}

export function AskDipakView({
  initial,
}: {
  /** The review fixture's screenshots only: an option picked, Deep lessons open. */
  initial?: Readonly<{
    picked?: Record<string, number>;
    deep?: Record<string, boolean>;
  }>;
} = {}) {
  const params = useSearchParams();
  const view = parseView(params);
  const href = viewHref(view);
  const progress = useProgress();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const first = useRef(true);
  // This visit's choices (spec section 31): picks and open Deep lessons; the
  // search words live with the screens (nav.ts), as opening Search clears them.
  const [picked, setPicked] = useState<Record<string, number>>(
    () => initial?.picked ?? {},
  );
  const [deep, setDeep] = useState<Record<string, boolean>>(
    () => initial?.deep ?? {},
  );
  const [query, setQuery] = useSearchWords();

  useLayoutEffect(() => {
    if (first.current) {
      first.current = false;
      startTrail(href);
      return;
    }
    const move = arrive(href);
    const scroller = scrollerOf(rootRef.current);
    scroller.scrollTo({ top: move === "pop" ? scrollFor(href) : 0 });
    // A new visit to Search is ready to type (go() emptied the words); Back
    // to it keeps them (spec section 12).
    if (move === "push" && href === viewHref({ kind: "search" }))
      inputRef.current?.focus({ preventScroll: true });
  }, [href]);

  // Leaving a screen notes how far it was scrolled, so Back returns there.
  useEffect(
    () =>
      onLeave(() =>
        rememberScroll(href, scrollerOf(rootRef.current).scrollTop),
      ),
    [href],
  );

  // The tab tapped again: back to the top of Ask Dipak's home.
  useTabAgain("ask", () => {
    restart();
    scrollerOf(rootRef.current).scrollTo({ top: 0 });
  });

  const open: Open = (next) => go(next);
  const back = () => goBack(view);

  let screen: ReactNode;
  switch (view.kind) {
    case "home":
      screen = <HomeScreen open={open} />;
      break;
    case "topics":
      screen = <TopicsScreen open={open} back={back} />;
      break;
    case "topic":
      screen = <TopicScreen id={view.id} open={open} back={back} />;
      break;
    case "category":
      screen = <CategoryScreen id={view.id} open={open} back={back} />;
      break;
    case "search":
      screen = (
        <SearchScreen
          query={query}
          onQuery={setQuery}
          open={open}
          back={back}
          inputRef={inputRef}
        />
      );
      break;
    case "saved":
      screen = <SavedScreen progress={progress} open={open} back={back} />;
      break;
    case "lesson":
      screen = (
        <LessonScreen
          key={view.id}
          id={view.id}
          progress={progress}
          picked={picked[view.id]}
          onPick={(choice) =>
            setPicked((now) => ({ ...now, [view.id]: choice }))
          }
          deepOpen={Boolean(deep[view.id])}
          onDeep={() =>
            setDeep((now) => ({ ...now, [view.id]: !now[view.id] }))
          }
          open={open}
          back={back}
        />
      );
      break;
  }

  return (
    <div ref={rootRef} className={styles.root} data-ask-view={view.kind}>
      <Tools view={view} open={open} />
      {screen}
    </div>
  );
}
