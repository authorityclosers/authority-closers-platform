"use client";

/**
 * Ask Dipak (Dipak's spec and clickable sample, 13 Nov 2026): his sales
 * library as the tab's home. Home → a topic or category → a question →
 * its lesson (quick answer, your turn with three options and Dipak's word on
 * each, the Deep lesson, the line to remember, the Next-call mission, what
 * to learn next); Search and Saved lessons beside them. Dipak's own lessons
 * show as they are, his before/after lines first, each loaded from the API
 * when opened (lessons.ts); a lesson drafted for him carries a "Draft ·
 * Dipak to confirm" tag, and its mission can't be marked until he confirms it.
 */

import { useSearchParams } from "next/navigation";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { useTabAgain } from "../shell/tab-again";
import styles from "./ask-dipak.module.css";
import { COPY } from "./copy";
import { CoachMark, TopicArt } from "./art";
import { readGrowth, type Growth } from "./coaching-client";
import { ContinueCard, MissionStrip } from "./home-desk";
import { Breadcrumb, ScreenButton, type Open } from "./bits";
import { AskIcon } from "./icons";
import { LessonScreen } from "./lesson-screen";
import { MissionsScreen } from "./missions-screen";
import {
  CATEGORIES,
  CATEGORY_LABELS,
  FEATURED,
  QUESTIONS,
  REAL_SITUATIONS,
  categoryById,
  categoryQuestions,
  featuredById,
  featuredQuestions,
  lessonChip,
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
import { loadProgress, useProgress, type Progress } from "./progress";
import { rememberLesson } from "./recent";
import { toneOfCategory, toneOfFeatured, type Tone } from "./tones";

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

/**
 * One question of a topic, its own bordered card with its number in the
 * topic's colour (Dipak's report 227, 16 Nov 2026: "no differentiation
 * between the points … make borders").
 */
function QuestionRow({
  question,
  open,
  number,
}: {
  question: Question;
  open: Open;
  number: number;
}) {
  return (
    <ScreenButton
      view={{ kind: "lesson", id: question.id }}
      open={open}
      className={styles.questionRow}
    >
      <span className={styles.rowNumber} aria-hidden="true">
        {number}
      </span>
      <span className={styles.rowWords}>{questionLabel(question)}</span>
      <AskIcon name="right" size={18} />
    </ScreenButton>
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

/**
 * Dipak's card, the Coach's desk (owner's pick H-A, 17 Nov 2026), the strong
 * card at the top (owner, 17 Nov 2026): his monogram until an approved photo
 * exists (never a generated face), his hello and his question, and the lesson
 * to Continue inside it; his three intro lines fold behind "Dipak के बारे में"
 * (owner, 16 Nov 2026: keep it compact), sliding open and shut (none with
 * reduced motion). Saved lessons opens from its corner. No listen pill until
 * Dipak records his own voice.
 */
function Greeting({ open }: { open: Open }) {
  const [more, setMore] = useState(false);
  const moreId = useId();
  return (
    <section className={styles.hero} data-more={more || undefined}>
      <div className={styles.heroMain}>
        <div className={styles.coachRow}>
          <CoachMark />
          <div className={styles.coachWords}>
            <p className={styles.eyebrow}>{COPY.eyebrow}</p>
            <h2 className={styles.hello}>{COPY.hello}</h2>
            <p className={styles.heroAsk}>
              <strong>{COPY.introAsk}</strong>
            </p>
          </div>
          <button
            type="button"
            className={styles.heroSaved}
            aria-label={COPY.savedLessons}
            onClick={() => open({ kind: "saved" })}
          >
            <AskIcon name="bookmark" size={20} />
          </button>
        </div>
        <div
          className={styles.introMore}
          id={moreId}
          aria-hidden={!more}
          inert={!more}
        >
          <div>
            {COPY.intro.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        </div>
        <button
          type="button"
          className={styles.introToggle}
          aria-expanded={more}
          aria-controls={moreId}
          onClick={() => setMore((now) => !now)}
        >
          {more ? COPY.introLess : COPY.introMore}
          <span className={styles.foldArrow} data-open={more || undefined}>
            <AskIcon name="right" size={16} />
          </span>
        </button>
      </div>
      <ContinueCard open={open} />
    </section>
  );
}

/**
 * The three real situations each look like their own moment (Dipak's report
 * 226, 16 Nov 2026: "teenhi goshti ek distay", the three look the same): the
 * colour and drawing of what the customer's words are about, by meaning:
 * price (Price & Objections), a decision someone else shares (Qualification
 * & Decision Process) and "I'll think about it", a follow-up (Closing &
 * Follow-Up).
 */
const SITUATION_LOOK: Readonly<
  Record<string, { tone: Tone; category: string }>
> = {
  PB03: { tone: "action", category: "08" },
  DM02: { tone: "info", category: "06" },
  OB03: { tone: "good", category: "09" },
};

/**
 * The Coach's desk, top to bottom (redesign study §5 S1, with H-B's situation
 * block): Dipak's card; Continue; today's mission and its check-in (only while
 * one is active); search; real situations as the customer's own words; the
 * four topics, each with its drawing; My missions. Computers lay the same
 * blocks on a wider grid (the stylesheet).
 */
function HomeScreen({ open }: { open: Open }) {
  return (
    <>
      <div className={styles.desk}>
        <Greeting open={open} />
        <MissionStrip open={open} />
      </div>
      <ScreenButton
        view={{ kind: "search" }}
        open={open}
        className={styles.searchHome}
      >
        <AskIcon name="search" size={21} />
        <span>{COPY.searchPlaceholder}</span>
      </ScreenButton>
      <div className={`${styles.hrow} ${styles.realTitle}`}>
        <h2>{COPY.real}</h2>
      </div>
      <div className={styles.situations}>
        {REAL_SITUATIONS.map((id) => {
          const question = questionById(id);
          if (!question) return null;
          const look = SITUATION_LOOK[id];
          return (
            <ScreenButton
              key={id}
              view={{ kind: "lesson", id }}
              open={open}
              className={`${styles.situation} ${styles[look?.tone ?? toneOfCategory(question.categoryId)]}`}
            >
              <span className={styles.situationTop}>
                <span className={styles.situationArt} aria-hidden="true">
                  <TopicArt
                    category={look?.category ?? question.categoryId}
                    size={36}
                  />
                </span>
                <span className={styles.chip}>{lessonChip(question)}</span>
              </span>
              <span className={styles.bubble}>{questionLabel(question)}</span>
              <span className={styles.situationFoot}>
                <span className={styles.entryMeta}>{COPY.parts}</span>
                <AskIcon name="right" size={18} />
              </span>
            </ScreenButton>
          );
        })}
      </div>
      <div className={styles.hrow}>
        <h2>{COPY.explore}</h2>
        <ScreenButton
          view={{ kind: "topics" }}
          open={open}
          className={styles.see}
        >
          {`${COPY.seeAll} ${CATEGORIES.length}`}
          <AskIcon name="right" size={16} />
        </ScreenButton>
      </div>
      <div className={`${styles.topicGrid} ${styles.homeTopics}`}>
        {FEATURED.map((topic) => (
          <ScreenButton
            key={topic.id}
            view={{ kind: "topic", id: topic.id }}
            open={open}
            className={`${styles.topicCard} ${styles.topicTile} ${styles[toneOfFeatured(topic.id)]}`}
          >
            <span className={styles.topicArt}>
              <TopicArt featured={topic.id} size={56} />
            </span>
            <span className={styles.topicTitle}>{topic.name}</span>
            <span className={styles.topicSub}>{topic.sub}</span>
            <span className={styles.arr}>
              <AskIcon name="right" size={18} />
            </span>
          </ScreenButton>
        ))}
      </div>
      <ScreenButton
        view={{ kind: "missions" }}
        open={open}
        className={`${styles.entry} ${styles.missionsEntry}`}
      >
        <span className={styles.entryCopy}>
          <span className={styles.entryTitle}>{COPY.myMissions}</span>
          <span className={styles.entryMeta}>{COPY.myMissionsMeta}</span>
        </span>
        <AskIcon name="right" size={18} />
      </ScreenButton>
      <p className={styles.notice}>{COPY.notice}</p>
    </>
  );
}

/**
 * A topic's cover (owner's pick C-A, 17 Nov 2026; redesign study §5 S2): its
 * drawing on its soft colour, its number or kind, name, short line and real
 * lesson count.
 */
function Cover({
  tone,
  eyebrow,
  title,
  sub,
  count,
  art,
}: {
  tone: string;
  eyebrow: string;
  title: string;
  sub: string;
  count: number;
  art: ReactNode;
}) {
  return (
    <div className={`${styles.cover} ${styles[tone]}`} data-cover="">
      <div className={styles.coverWords}>
        <p className={styles.coverEyebrow}>{eyebrow}</p>
        <h2 className={styles.pageTitle}>{title}</h2>
        <p className={styles.coverSub}>{sub}</p>
        <p className={styles.coverCount}>{COPY.lessonCount(count)}</p>
      </div>
      <span className={styles.coverArt}>{art}</span>
    </div>
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
            className={`${styles.topicCard} ${styles.topicTile} ${styles[toneOfCategory(category.id)]}`}
          >
            <span className={styles.topicArt}>
              <TopicArt category={category.id} size={52} />
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
      <Cover
        tone={toneOfFeatured(topic.id)}
        eyebrow={COPY.topicChip}
        title={topic.name}
        sub={topic.sub}
        count={featuredQuestions(topic).length}
        art={<TopicArt featured={topic.id} size={64} />}
      />
      <p className={styles.pageSub}>{COPY.topicSub}</p>
      <div className={`${styles.rows} ${styles[toneOfFeatured(topic.id)]}`}>
        {featuredQuestions(topic).map((question, index) => (
          <QuestionRow
            key={question.id}
            question={question}
            open={open}
            number={index + 1}
          />
        ))}
      </div>
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
      <Cover
        tone={toneOfCategory(category.id)}
        eyebrow={category.id}
        title={category.name}
        sub={CATEGORY_LABELS[category.id]}
        count={categoryQuestions(category).length}
        art={<TopicArt category={category.id} size={64} />}
      />
      <p className={styles.pageSub}>{COPY.categorySub}</p>
      <div className={`${styles.rows} ${styles[toneOfCategory(category.id)]}`}>
        {categoryQuestions(category).map((question, index) => (
          <QuestionRow
            key={question.id}
            question={question}
            open={open}
            number={index + 1}
          />
        ))}
      </div>
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
          <div className={`${styles.rows} ${styles.good}`}>
            {results.map((question, index) => (
              <QuestionRow
                key={question.id}
                question={question}
                open={open}
                number={index + 1}
              />
            ))}
          </div>
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

/**
 * My learning (redesign study §5 S6, options P-A/P-B; 18 Nov 2026): Progress
 * and Saved as one personal record. Progress counts only what the account
 * keeps (saved lessons, missions, calls the seller said they tried), never a
 * score, streak or percentage, and nothing resets.
 */
function ProgressPane({ progress }: { progress: Progress }) {
  const [growth, setGrowth] = useState<Growth | null>(null);
  useEffect(() => {
    let live = true;
    readGrowth().then(
      (answer) => {
        if (live) setGrowth(answer);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  const tried = growth
    ? growth.missions.reduce((sum, item) => sum + item.done_calls, 0)
    : null;
  const kept = (id: string) =>
    progress.saved.has(id) || progress.missions.has(id);
  const stats: [number | null, string][] = [
    [progress.saved.size, COPY.statSaved],
    [progress.missions.size, COPY.statMissions],
    [tried, COPY.statTried],
  ];
  const anything = progress.saved.size + progress.missions.size > 0;
  return (
    <div data-pane="progress">
      <div className={styles.stats}>
        {stats.map(([value, label]) => (
          <div key={label} className={styles.stat}>
            <strong>{value ?? "–"}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      {anything ? null : <p className={styles.pageSub}>{COPY.progressZero}</p>}
      <div className={styles.topicProgress}>
        {CATEGORIES.map((category) => {
          const lessons = categoryQuestions(category);
          const count = lessons.filter((question) => kept(question.id)).length;
          return (
            <div
              key={category.id}
              className={`${styles.topicLine} ${styles[toneOfCategory(category.id)]}`}
              data-topic-line={category.id}
            >
              <span className={styles.topicLineArt}>
                <TopicArt category={category.id} size={28} />
              </span>
              <span className={styles.topicLineWords}>
                <span className={styles.topicLineName}>{category.name}</span>
                <span className={styles.topicLineBar} aria-hidden="true">
                  <span
                    style={{
                      width: `${lessons.length ? (count / lessons.length) * 100 : 0}%`,
                    }}
                  />
                </span>
              </span>
              <span className={styles.topicLineCount}>
                {COPY.keptOf(count, lessons.length)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
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
  const [pane, setPane] = useState<"progress" | "saved">("saved");
  const saved = QUESTIONS.filter((question) => progress.saved.has(question.id));
  const waiting = progress.status === "idle" || progress.status === "loading";
  return (
    <>
      <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
      <h2 className={styles.pageTitle}>{COPY.learningTitle}</h2>
      <div
        className={styles.segment}
        role="tablist"
        aria-label={COPY.learningTitle}
      >
        {(["progress", "saved"] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={pane === key}
            className={styles.segmentItem}
            onClick={() => setPane(key)}
          >
            {key === "progress"
              ? COPY.paneProgress
              : `${COPY.paneSaved} (${saved.length})`}
          </button>
        ))}
      </div>
      {pane === "progress" ? (
        <ProgressPane progress={progress} />
      ) : (
        <>
          <p className={styles.pageSub}>{COPY.savedSub}</p>
          {saved.length ? (
            <div className={styles.savedList}>
              {saved.map((question, index) => (
                <div
                  key={question.id}
                  className={`${styles.rows} ${styles[toneOfCategory(question.categoryId)]}`}
                >
                  <QuestionRow
                    question={question}
                    open={open}
                    number={index + 1}
                  />
                </div>
              ))}
            </div>
          ) : waiting ? (
            <div className={styles.rowSkeleton} aria-busy="true" />
          ) : progress.status === "failed" ? (
            <div className={styles.empty}>
              <strong>Couldn&rsquo;t open your saved lessons</strong>
              Check your connection, then try again.
              <button
                type="button"
                className={`${styles.smallBtn} ${styles.primary}`}
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
      )}
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
  // Options looked at per lesson this visit, for their "देखा" tags.
  const [tried, setTried] = useState<Record<string, readonly number[]>>(() =>
    Object.fromEntries(
      Object.entries(initial?.picked ?? {}).map(([id, at]) => [id, [at]]),
    ),
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

  // The home's Continue card opens the lesson last opened here.
  const lessonId = view.kind === "lesson" ? view.id : null;
  useEffect(() => {
    if (lessonId && questionById(lessonId)) rememberLesson(lessonId);
  }, [lessonId]);

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
    case "missions":
      screen = (
        <>
          <Breadcrumb onBack={back}>{COPY.title}</Breadcrumb>
          <MissionsScreen open={open} />
        </>
      );
      break;
    case "lesson":
      screen = (
        <LessonScreen
          key={view.id}
          id={view.id}
          progress={progress}
          picked={picked[view.id]}
          tried={tried[view.id] ?? []}
          onPick={(choice) => {
            setPicked((now) => ({ ...now, [view.id]: choice }));
            setTried((now) => ({
              ...now,
              [view.id]: [...new Set([...(now[view.id] ?? []), choice])],
            }));
          }}
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
