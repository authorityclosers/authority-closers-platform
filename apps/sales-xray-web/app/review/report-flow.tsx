"use client";

/**
 * Report review (owner, 23 Oct 2026). The coaching lead checks every item of a call's
 * Report: the AI coaching score's skills, the overview, the outcome, the buyer and
 * whatever the Report adds later. The server builds the items from the Report's own
 * structure (review_schema), so a new section shows here with no code change. Each item
 * takes Agree (one tap, moves on), Disagree, or Fix: the right rating 1-5 or the right
 * words, with an optional note. Every save is a gold label, newest answer counts.
 */

import { ArrowLeft, ChevronLeft, Pause, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { notify } from "../notice-center";
import {
  SKIP_WORDS,
  callName,
  clock,
  headsByTarget,
  saveLine,
  type LineSave,
  type ReportItem,
  type ReportVerdict,
  type SavedRow,
  type Segment,
  type SkipReason,
  type Workspace,
} from "./review-client";
import styles from "./review.module.css";

const SPEEDS = [1, 1.25, 1.5];
const VERDICTS: [ReportVerdict, string, string, "good" | "warn" | "bad"][] = [
  ["agree", "Agree", "AI is right", "good"],
  ["disagree", "Disagree", "AI is wrong", "bad"],
  ["fix", "Fix", "Give the right one", "warn"],
];
const VERDICT_WORDS: Record<ReportVerdict, string> = {
  agree: "Agreed",
  disagree: "Disagreed",
  fix: "Fixed",
};

export const itemTarget = (id: string) => `item:${id}`;

export type Draft = {
  verdict: ReportVerdict | null;
  rating: number | null;
  correction: string;
  note: string;
};
const EMPTY: Draft = { verdict: null, rating: null, correction: "", note: "" };

function draftOf(row: SavedRow | undefined): Draft {
  const value = row?.value;
  if (!value || value.skip) return EMPTY;
  const verdict =
    value.verdict === "agree" ||
    value.verdict === "disagree" ||
    value.verdict === "fix"
      ? value.verdict
      : null;
  return {
    verdict,
    rating: typeof value.rating === "number" ? value.rating : null,
    correction: value.correction ?? "",
    note: value.opinion ?? "",
  };
}

/** Fix needs the right rating (rated items) or the right words. */
export function canSave(draft: Draft, item: ReportItem | undefined): boolean {
  if (!item || !draft.verdict) return false;
  if (draft.verdict !== "fix") return true;
  return (
    (item.kind === "rating" && draft.rating !== null) ||
    draft.correction.trim().length > 0
  );
}

/** What one judgement sends: Agree carries nothing else; a rating only on a rated item. */
export function saveOf(draft: Draft, item: ReportItem): LineSave {
  const value: LineSave = { verdict: draft.verdict };
  if (draft.verdict === "agree") return value;
  if (draft.note.trim()) value.opinion = draft.note.trim();
  if (draft.verdict === "fix") {
    if (item.kind === "rating" && draft.rating !== null)
      value.rating = draft.rating;
    if (draft.correction.trim()) value.correction = draft.correction.trim();
  }
  return value;
}

function speakerNames(segments: Segment[]): Map<string, string> {
  const names = new Map<string, string>();
  for (const segment of segments)
    if (!names.has(segment.speaker_id))
      names.set(
        segment.speaker_id,
        `Speaker ${String.fromCharCode(65 + names.size)}`,
      );
  return names;
}

export function ReportFlow({
  assignmentId,
  workspace,
  onFinished,
  onReload,
}: {
  assignmentId: string;
  workspace: Workspace;
  onFinished: () => void;
  onReload: () => void;
}) {
  const sections = useMemo(() => workspace.sections ?? [], [workspace]);
  const items = useMemo(() => sections.flatMap((s) => s.items), [sections]);
  const sectionNames = useMemo(
    () => new Map(sections.map((s) => [s.id, s.label])),
    [sections],
  );
  const segments = workspace.transcript.segments;
  const names = useMemo(() => speakerNames(segments), [segments]);
  const [heads, setHeads] = useState(() => headsByTarget(workspace.saved));
  const headsRef = useRef(heads);
  // What he chose here, before the server answers, so going back shows it.
  const chosen = useRef(new Map<string, Draft>());
  // Start at the first item he hasn't judged.
  const [index, setIndex] = useState(() => {
    const open = items.findIndex((item) => !heads.has(itemTarget(item.id)));
    return open === -1 ? items.length : open;
  });
  const [draft, setDraft] = useState<Draft>(() =>
    draftOf(heads.get(itemTarget(items[index]?.id ?? ""))),
  );
  const [skipping, setSkipping] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const shownAt = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);

  // A reload brings the server's saves.
  const [seen, setSeen] = useState(workspace);
  if (seen !== workspace) {
    setSeen(workspace);
    setHeads(headsByTarget(workspace.saved));
  }
  useEffect(() => {
    headsRef.current = heads;
  }, [heads]);
  useEffect(() => {
    shownAt.current = Date.now();
  }, []);

  const handled = items.filter((item) => heads.has(itemTarget(item.id))).length;

  const persist = useCallback(
    (target: string, value: LineSave) => {
      // Time on this item, measured when he answers (at most 15 minutes).
      const seconds = Math.min(
        900,
        Math.round((Date.now() - shownAt.current) / 1000),
      );
      const key =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;
      chain.current = chain.current.then(async () => {
        try {
          const row = await saveLine(
            assignmentId,
            workspace.review_id,
            target,
            { ...value, seconds },
            headsRef.current.get(target)?.id ?? null,
            key,
          );
          const map = new Map(headsRef.current);
          map.set(target, row);
          headsRef.current = map;
          setHeads(map);
        } catch (error) {
          chosen.current.delete(target);
          notify({
            id: `review-save-${target}`,
            tone: "error",
            title: "A review didn't save",
            message: (error as Error).message,
            action: { label: "Reload", run: onReload },
          });
        }
      });
    },
    [assignmentId, workspace.review_id, onReload],
  );

  const go = useCallback(
    (next: number) => {
      const to = Math.max(0, Math.min(next, items.length));
      const target = itemTarget(items[to]?.id ?? "");
      setIndex(to);
      setDraft(
        chosen.current.get(target) ?? draftOf(headsRef.current.get(target)),
      );
      setSkipping(false);
      shownAt.current = Date.now();
      scroller.current?.scrollTo({ top: 0 });
    },
    [items],
  );

  function save(next: Draft) {
    const item = items[index];
    if (!item || !canSave(next, item)) return;
    const target = itemTarget(item.id);
    const before =
      chosen.current.get(target) ?? draftOf(headsRef.current.get(target));
    const same = JSON.stringify(before) === JSON.stringify(next);
    if (!same || headsRef.current.get(target)?.value?.skip) {
      chosen.current.set(target, next);
      persist(target, saveOf(next, item));
    }
    go(index + 1);
  }

  function choose(verdict: ReportVerdict) {
    if (verdict === "agree") {
      save({ ...EMPTY, verdict });
      return;
    }
    setDraft({ ...draft, verdict });
  }

  function skip(reason: SkipReason) {
    const item = items[index];
    if (!item) return;
    chosen.current.delete(itemTarget(item.id));
    persist(itemTarget(item.id), { skip: reason });
    go(index + 1);
  }

  function jump(section: string) {
    const first = items.findIndex(
      (item) =>
        item.section === section && !headsRef.current.has(itemTarget(item.id)),
    );
    go(
      first === -1
        ? items.findIndex((item) => item.section === section)
        : first,
    );
  }

  function playFrom(ms: number) {
    const element = audio.current;
    if (!element) return;
    if (playing === ms && !element.paused) {
      element.pause();
      setPlaying(null);
      return;
    }
    element.currentTime = ms / 1000;
    element.playbackRate = speed;
    void element.play().then(
      () => setPlaying(ms),
      () =>
        notify({
          id: "review-audio",
          tone: "error",
          title: "The recording didn't play",
          message: "Check your connection and try again.",
        }),
    );
  }

  function changeSpeed(value: number) {
    setSpeed(value);
    if (audio.current) audio.current.playbackRate = value;
  }

  // Keys for desktop reviewers: 1 agree, 2 disagree, 3 fix, arrows move.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        index >= items.length
      )
        return;
      if (event.key === "1") choose("agree");
      else if (event.key === "2") choose("disagree");
      else if (event.key === "3") choose("fix");
      else if (event.key === "ArrowRight") go(index + 1);
      else if (event.key === "ArrowLeft") go(index - 1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const total = items.length;
  const item = index < total ? items[index] : undefined;
  const savedRow = item ? heads.get(itemTarget(item.id)) : undefined;
  const savedSkip = savedRow?.value?.skip;
  const name = callName(
    workspace.context?.recorded_at ?? "",
    workspace.context?.duration_ms,
  );
  const open = draft.verdict === "disagree" || draft.verdict === "fix";

  return (
    <div className={styles.flow}>
      <div className={styles.top}>
        <div className={styles.topLine}>
          <button
            type="button"
            onClick={onFinished}
            aria-label="Back to the review queue"
          >
            <ArrowLeft size={16} aria-hidden="true" />
          </button>
          <span className={styles.callName}>{name}</span>
          <span className={styles.pill} data-tone="accent">
            Report
          </span>
          <span className={styles.counter} aria-live="polite">
            {handled}/{total} done
          </span>
        </div>
        <div className={styles.inline}>
          <audio
            ref={audio}
            className={styles.player}
            src={workspace.audio_source_url}
            preload="none"
            controls
            onPause={() => setPlaying(null)}
            onEnded={() => setPlaying(null)}
            onPlay={(event) => {
              event.currentTarget.playbackRate = speed;
            }}
          />
          <div className={styles.chipRow} aria-label="Playback speed">
            {SPEEDS.map((value) => (
              <button
                key={value}
                type="button"
                className={styles.chip}
                aria-pressed={speed === value}
                onClick={() => changeSpeed(value)}
              >
                {value}×
              </button>
            ))}
          </div>
        </div>
        <div className={styles.chipRow} aria-label="Report sections">
          {sections.map((section) => {
            const done = section.items.filter((i) =>
              heads.has(itemTarget(i.id)),
            ).length;
            return (
              <button
                key={section.id}
                type="button"
                className={styles.chip}
                aria-pressed={item?.section === section.id}
                onClick={() => jump(section.id)}
              >
                {section.label} {done}/{section.items.length}
              </button>
            );
          })}
        </div>
        <div
          className={styles.bar}
          role="progressbar"
          aria-label="Report items reviewed"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={handled}
        >
          <span style={{ width: `${(handled / Math.max(total, 1)) * 100}%` }} />
        </div>
      </div>

      <div className={styles.evidence} ref={scroller}>
        {item ? (
          <ItemCard
            item={item}
            section={sectionNames.get(item.section) ?? item.section}
            saved={savedRow}
            segments={segments}
            names={names}
            playing={playing}
            onPlay={playFrom}
            context={index === 0 ? workspace.context : undefined}
          />
        ) : (
          <Done items={items} heads={heads} />
        )}
      </div>

      <div className={styles.choices}>
        {!item ? (
          <div className={styles.nav}>
            <button
              type="button"
              className={styles.navBtn}
              onClick={() => go(total - 1)}
              disabled={total === 0}
            >
              <ChevronLeft size={16} aria-hidden="true" /> Back
            </button>
            <span />
            <button
              type="button"
              className={styles.navBtn}
              data-primary=""
              onClick={onFinished}
            >
              Next call
            </button>
          </div>
        ) : skipping ? (
          <>
            <p className={styles.ask}>Why skip this item?</p>
            <div className={styles.chipRow}>
              {(Object.keys(SKIP_WORDS) as SkipReason[]).map((reason) => (
                <button
                  key={reason}
                  type="button"
                  className={styles.chip}
                  onClick={() => skip(reason)}
                >
                  {SKIP_WORDS[reason]}
                </button>
              ))}
            </div>
            <div className={styles.nav}>
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => setSkipping(false)}
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <p className={styles.ask}>
              {savedSkip
                ? `Skipped (${SKIP_WORDS[savedSkip]}). Judge it now or move on.`
                : "Is the AI right about this?"}
            </p>
            <div className={styles.verdicts}>
              {VERDICTS.map(([value, label, hint, tone]) => (
                <button
                  key={value}
                  type="button"
                  className={styles.verdict}
                  data-tone={tone}
                  aria-pressed={draft.verdict === value}
                  onClick={() => choose(value)}
                >
                  {label}
                  <small>{hint}</small>
                </button>
              ))}
            </div>
            {open ? (
              <Detail item={item} draft={draft} setDraft={setDraft} />
            ) : null}
            <div className={styles.nav}>
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => go(index - 1)}
                disabled={index === 0}
              >
                <ChevronLeft size={16} aria-hidden="true" /> Back
              </button>
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => setSkipping(true)}
              >
                Skip
              </button>
              {open ? (
                <button
                  type="button"
                  className={styles.navBtn}
                  data-primary=""
                  disabled={!canSave(draft, item)}
                  onClick={() => save(draft)}
                >
                  Save
                </button>
              ) : (
                <button
                  type="button"
                  className={styles.navBtn}
                  data-primary=""
                  onClick={() => go(index + 1)}
                >
                  Next
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Detail({
  item,
  draft,
  setDraft,
}: {
  item: ReportItem;
  draft: Draft;
  setDraft: (draft: Draft) => void;
}) {
  const fix = draft.verdict === "fix";
  return (
    <>
      {fix && item.kind === "rating" ? (
        <div className={styles.field}>
          <span className={styles.ask}>
            The right rating
            {item.rating !== null ? ` (AI: ${item.rating})` : ""}
          </span>
          <div className={styles.ratings}>
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                className={styles.rating}
                data-ai={value === item.rating ? "" : undefined}
                aria-pressed={draft.rating === value}
                onClick={() =>
                  setDraft({
                    ...draft,
                    rating: draft.rating === value ? null : value,
                  })
                }
              >
                {value}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {fix ? (
        <textarea
          className={styles.note}
          data-tall=""
          value={draft.correction}
          maxLength={600}
          rows={2}
          placeholder={
            item.kind === "rating"
              ? "What it should say (optional)"
              : "What it should say"
          }
          aria-label="What it should say"
          onChange={(event) =>
            setDraft({ ...draft, correction: event.target.value })
          }
        />
      ) : null}
      <input
        className={styles.note}
        value={draft.note}
        maxLength={4000}
        placeholder="A short note (optional)"
        aria-label="A short note (optional)"
        onChange={(event) => setDraft({ ...draft, note: event.target.value })}
      />
    </>
  );
}

function ItemCard({
  item,
  section,
  saved,
  segments,
  names,
  playing,
  onPlay,
  context,
}: {
  item: ReportItem;
  section: string;
  saved: SavedRow | undefined;
  segments: Segment[];
  names: Map<string, string>;
  playing: number | null;
  onPlay: (ms: number) => void;
  context?: Workspace["context"];
}) {
  const bySegment = new Map(segments.map((segment) => [segment.id, segment]));
  const verdict = saved?.value?.verdict;
  const mark =
    verdict === "agree" || verdict === "disagree" || verdict === "fix"
      ? verdict
      : null;
  return (
    <>
      {context?.summary ? (
        <details className={styles.more}>
          <summary>About this call</summary>
          <p className={styles.said}>{context.summary}</p>
        </details>
      ) : null}
      <div className={styles.pointerHead}>
        <span className={styles.number}>
          {item.number ?? section.slice(0, 1).toUpperCase()}
        </span>
        <div>
          <h2>{item.label}</h2>
          <div className={styles.tags}>
            <span className={styles.pill}>{section}</span>
            <span className={styles.pill} data-tone="accent">
              AI draft
            </span>
            {mark ? (
              <span
                className={styles.pill}
                data-tone={
                  mark === "agree" ? "good" : mark === "fix" ? "warn" : "bad"
                }
              >
                {VERDICT_WORDS[mark]}
              </span>
            ) : null}
          </div>
        </div>
        {item.kind === "rating" ? (
          <div className={styles.score}>
            <b>{item.rating ?? "–"}</b>
            <span>AI rating</span>
          </div>
        ) : (
          <span />
        )}
      </div>
      {item.text ? <p className={styles.said}>{item.text}</p> : null}
      {item.detail ? (
        <p className={styles.said} data-detail="">
          {item.detail}
        </p>
      ) : null}
      {item.evidence.map((quote, i) => {
        const segment = bySegment.get(quote.segment_id ?? "");
        return (
          <blockquote
            key={`${quote.segment_id ?? i}-${i}`}
            className={styles.quote}
          >
            {typeof quote.start_ms === "number" ? (
              <PlayChip ms={quote.start_ms} playing={playing} onPlay={onPlay} />
            ) : (
              <span />
            )}
            <span>
              {segment ? (
                <span className={styles.speaker}>
                  {names.get(segment.speaker_id)}
                </span>
              ) : null}
              {quote.quote}
            </span>
          </blockquote>
        );
      })}
    </>
  );
}

function Done({
  items,
  heads,
}: {
  items: ReportItem[];
  heads: Map<string, SavedRow>;
}) {
  const counts = { agree: 0, disagree: 0, fix: 0, skipped: 0 };
  for (const item of items) {
    const value = heads.get(itemTarget(item.id))?.value;
    if (value?.skip) counts.skipped += 1;
    else if (
      value?.verdict === "agree" ||
      value?.verdict === "disagree" ||
      value?.verdict === "fix"
    )
      counts[value.verdict] += 1;
  }
  const handled = items.filter((item) => heads.has(itemTarget(item.id))).length;
  const all = handled >= items.length && items.length > 0;
  return (
    <div className={styles.done}>
      <span className={styles.pill} data-tone={all ? "good" : "warn"}>
        {handled}/{items.length} items
      </span>
      <h2>{all ? "This call's Report is reviewed" : "Some items are open"}</h2>
      <p className={styles.muted}>
        {counts.agree} agreed · {counts.disagree} disagreed · {counts.fix} fixed
        {counts.skipped ? ` · ${counts.skipped} skipped` : ""}
      </p>
      <p className={styles.muted}>
        Every save is already in the gold set. Go back to any item to change it;
        the newest answer counts.
      </p>
    </div>
  );
}

function PlayChip({
  ms,
  playing,
  onPlay,
}: {
  ms: number;
  playing: number | null;
  onPlay: (ms: number) => void;
}) {
  const active = playing === ms;
  return (
    <button
      type="button"
      className={styles.play}
      data-playing={active ? "" : undefined}
      onClick={() => onPlay(ms)}
      aria-label={`${active ? "Pause" : "Play from"} ${clock(ms)}`}
    >
      {active ? (
        <Pause size={12} aria-hidden="true" />
      ) : (
        <Play size={12} aria-hidden="true" />
      )}
      {clock(ms)}
    </button>
  );
}
