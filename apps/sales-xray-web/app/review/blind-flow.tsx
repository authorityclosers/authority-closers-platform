"use client";

/**
 * Blind Brain 4.0 rating (orchestrator, 21 Oct 2026). The reviewer listens to the call
 * and rates each of Brain 4.0's 18 skills 1-5, or "-" with why, without seeing any AI
 * answer (AC-SVAL-01 section 8.1). He can note moments he would correct or praise as
 * he listens. Once all 18 are saved the server shows Brain 4.0's ratings next to his,
 * with its coaching and the lines it cites; his ratings are then locked, and he marks
 * which of his moments Brain 4.0's coaching caught.
 */

import { ArrowLeft, ChevronLeft, Pause, Play, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { notify } from "../notice-center";
import {
  DIMENSION_SKIP_WORDS,
  callName,
  clock,
  headsByTarget,
  saveLine,
  type Brain4Dimension,
  type Caught,
  type Dimension,
  type DimensionSkip,
  type LineSave,
  type MomentKind,
  type SavedRow,
  type Segment,
  type Workspace,
} from "./review-client";
import styles from "./review.module.css";

const SPEEDS = [1, 1.25, 1.5];
const MAX_MOMENTS = 40;
const CAUGHT_WORDS: Record<Caught, string> = {
  yes: "Yes",
  partly: "Partly",
  no: "No",
};

export const dimensionTarget = (id: string) => `brain4:${id}`;

type Mine = { rating: number | null; skip: DimensionSkip | null };

function mine(row: SavedRow | undefined): Mine | null {
  const value = row?.value;
  if (!value) return null;
  if (typeof value.rating === "number")
    return { rating: value.rating, skip: null };
  if (value.skip && value.skip in DIMENSION_SKIP_WORDS)
    return { rating: null, skip: value.skip as DimensionSkip };
  return null;
}

/** Same rating: good; one apart, or one side "-": close; two or more apart: far. */
export function compareTone(
  yours: number | null,
  theirs: number | null,
): "good" | "warn" | "bad" {
  if (yours === null || theirs === null)
    return yours === theirs ? "good" : "warn";
  const gap = Math.abs(yours - theirs);
  return gap === 0 ? "good" : gap === 1 ? "warn" : "bad";
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

function parseClock(text: string): number | null {
  const match = /^(\d{1,3}):([0-5]\d)$/.exec(text.trim());
  return match ? (Number(match[1]) * 60 + Number(match[2])) * 1000 : null;
}

export function BlindFlow({
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
  const dims = useMemo(() => workspace.dimensions ?? [], [workspace]);
  const segments = workspace.transcript.segments;
  const names = useMemo(() => speakerNames(segments), [segments]);
  const revealed = workspace.revealed === true;
  const [heads, setHeads] = useState(() => headsByTarget(workspace.saved));
  const headsRef = useRef(heads);
  // Start: the intro on a new call, the first unrated skill on a started one, the
  // comparison once Brain 4.0's ratings are shown.
  const [index, setIndex] = useState(() => {
    const open = dims.findIndex((d) => !heads.has(dimensionTarget(d.id)));
    if (revealed || open === -1) return dims.length;
    return dims.some((d) => heads.has(dimensionTarget(d.id))) ? open : -1;
  });
  const [noting, setNoting] = useState(false);
  const [noteAt, setNoteAt] = useState(0);
  const [playing, setPlaying] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  // Moment numbers handed out but maybe not saved yet, so two quick moments never share one.
  const issued = useRef(new Set<string>());
  const shownAt = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);

  // A reload (after the 18th rating) brings the server's saves and Brain 4.0's read.
  const [seen, setSeen] = useState(workspace);
  if (seen !== workspace) {
    setSeen(workspace);
    setHeads(headsByTarget(workspace.saved));
    if (workspace.revealed) setIndex(dims.length);
  }
  useEffect(() => {
    headsRef.current = heads;
  }, [heads]);
  useEffect(() => {
    shownAt.current = Date.now();
  }, []);

  const rated = dims.filter((d) => heads.has(dimensionTarget(d.id))).length;
  const moments = useMemo(
    () =>
      [...heads.values()]
        .filter(
          (row) =>
            row.target.startsWith("moment:") &&
            row.value?.moment &&
            !row.value.moment.removed,
        )
        .sort(
          (a, b) =>
            (a.value?.moment?.at_ms ?? 0) - (b.value?.moment?.at_ms ?? 0),
        ),
    [heads],
  );

  const persist = useCallback(
    (target: string, value: LineSave) => {
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
            value,
            headsRef.current.get(target)?.id ?? null,
            key,
          );
          const map = new Map(headsRef.current);
          map.set(target, row);
          headsRef.current = map;
          setHeads(map);
          // The 18th rating opens Brain 4.0's read.
          if (
            target.startsWith("brain4:") &&
            dims.every((d) => map.has(dimensionTarget(d.id)))
          )
            onReload();
        } catch (error) {
          notify({
            id: `review-save-${target}`,
            tone: "error",
            title: "A rating didn't save",
            message: (error as Error).message,
            action: { label: "Reload", run: onReload },
          });
        }
      });
    },
    [assignmentId, workspace.review_id, dims, onReload],
  );

  const go = useCallback(
    (next: number) => {
      setIndex(Math.max(-1, Math.min(next, dims.length)));
      setNoting(false);
      shownAt.current = Date.now();
      scroller.current?.scrollTo({ top: 0 });
    },
    [dims.length],
  );

  const seconds = () =>
    Math.min(900, Math.round((Date.now() - shownAt.current) / 1000));

  function rate(choice: number | DimensionSkip) {
    const dimension = dims[index];
    if (!dimension || revealed) return;
    const target = dimensionTarget(dimension.id);
    const current = mine(headsRef.current.get(target));
    const same =
      typeof choice === "number"
        ? current?.rating === choice
        : current?.skip === choice;
    if (!same)
      persist(
        target,
        typeof choice === "number"
          ? { rating: choice, seconds: seconds() }
          : { skip: choice, seconds: seconds() },
      );
    go(index + 1);
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

  function nextMoment(): string | null {
    const used = [...headsRef.current.keys(), ...issued.current]
      .filter((target) => target.startsWith("moment:"))
      .map((target) => Number(target.slice(7)));
    const next = Math.max(0, ...used) + 1;
    if (next > MAX_MOMENTS) return null;
    const target = `moment:${String(next).padStart(2, "0")}`;
    issued.current.add(target);
    return target;
  }

  function saveMoment(
    at: number,
    kind: MomentKind,
    dimension: string,
    text: string,
  ) {
    const target = nextMoment();
    if (!target) {
      notify({
        id: "review-moments-full",
        tone: "error",
        title: "Too many moments",
        message: `A call keeps up to ${MAX_MOMENTS} moments.`,
      });
      return;
    }
    persist(target, {
      opinion: text,
      moment: { at_ms: at, kind, dimension: dimension || null },
    });
    setNoting(false);
  }

  function updateMoment(
    row: SavedRow,
    change: { caught?: Caught; removed?: boolean },
  ) {
    const moment = row.value?.moment;
    if (!moment) return;
    persist(row.target, {
      opinion: row.value?.opinion ?? "",
      moment: { ...moment, ...change },
    });
  }

  // Keys for desktop reviewers: 1-5 rate, arrows move.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        noting
      )
        return;
      if (/^[1-5]$/.test(event.key) && index >= 0 && index < dims.length)
        rate(Number(event.key));
      else if (event.key === "ArrowRight") go(index + 1);
      else if (event.key === "ArrowLeft") go(index - 1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const total = dims.length;
  const dimension = index >= 0 && index < total ? dims[index] : undefined;
  const name = callName(
    workspace.context?.recorded_at ?? "",
    workspace.context?.duration_ms,
  );
  const ready = rated >= total && total > 0;

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
            Blind
          </span>
          <span className={styles.counter} aria-live="polite">
            {rated}/{total} rated
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
        <div
          className={styles.bar}
          role="progressbar"
          aria-label="Skills rated"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={rated}
        >
          <span style={{ width: `${(rated / Math.max(total, 1)) * 100}%` }} />
        </div>
      </div>

      <div className={styles.evidence} ref={scroller}>
        {index < 0 ? (
          <Intro total={total} />
        ) : dimension ? (
          <DimensionCard
            dimension={dimension}
            saved={mine(heads.get(dimensionTarget(dimension.id)))}
            locked={revealed}
          />
        ) : revealed ? (
          <Reveal
            dims={dims}
            heads={heads}
            reveal={workspace.brain4 ?? null}
            segments={segments}
            names={names}
            playing={playing}
            onPlay={playFrom}
          />
        ) : (
          <div className={styles.done}>
            <span className={styles.pill} data-tone={ready ? "good" : "warn"}>
              {rated}/{total} rated
            </span>
            <h2>
              {ready
                ? "Opening Brain 4.0's ratings"
                : "Some skills are not rated"}
            </h2>
            <p className={styles.muted}>
              {ready
                ? "Your ratings are saved. Brain 4.0's appear in a moment."
                : "Go back and rate every skill, or mark it with a reason. Brain 4.0's ratings appear once all are saved."}
            </p>
            {ready ? (
              <button
                type="button"
                className={styles.navBtn}
                onClick={onReload}
              >
                Show Brain 4.0&apos;s ratings
              </button>
            ) : null}
          </div>
        )}
        <Moments
          rows={moments}
          revealed={revealed}
          dims={dims}
          playing={playing}
          onPlay={playFrom}
          onUpdate={updateMoment}
        />
        <details className={styles.more}>
          <summary>Transcript</summary>
          <div style={{ display: "grid", gap: 4, marginTop: 6 }}>
            {segments.map((segment) => (
              <blockquote
                key={segment.id}
                className={styles.quote}
                data-near=""
              >
                <PlayChip
                  ms={segment.start_ms}
                  playing={playing}
                  onPlay={playFrom}
                />
                <span>
                  <span className={styles.speaker}>
                    {names.get(segment.speaker_id)}
                  </span>
                  {segment.text}
                </span>
              </blockquote>
            ))}
          </div>
        </details>
      </div>

      <div className={styles.choices}>
        {noting ? (
          <MomentForm
            at={noteAt}
            dims={dims}
            onSave={saveMoment}
            onCancel={() => setNoting(false)}
          />
        ) : (
          <>
            {dimension ? (
              <Ratings
                saved={mine(heads.get(dimensionTarget(dimension.id)))}
                locked={revealed}
                onRate={rate}
              />
            ) : null}
            <div className={styles.nav}>
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => go(index - 1)}
                disabled={index < 0}
              >
                <ChevronLeft size={16} aria-hidden="true" /> Back
              </button>
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => {
                  setNoteAt(
                    Math.round((audio.current?.currentTime ?? 0) * 1000),
                  );
                  setNoting(true);
                }}
              >
                <Plus size={16} aria-hidden="true" /> Moment
              </button>
              {index < 0 ? (
                <button
                  type="button"
                  className={styles.navBtn}
                  data-primary=""
                  onClick={() => go(0)}
                >
                  Start rating
                </button>
              ) : index >= total ? (
                <button
                  type="button"
                  className={styles.navBtn}
                  data-primary=""
                  onClick={onFinished}
                >
                  Next call
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

function Intro({ total }: { total: number }) {
  return (
    <div className={styles.done}>
      <span className={styles.pill} data-tone="accent">
        Blind rating · {total} skills
      </span>
      <h2>Listen first, then rate</h2>
      <p className={styles.muted}>
        Play the call above. Rate each skill 1 to 5 from what you heard, or say
        why it has no rating. You won&apos;t see Brain 4.0&apos;s ratings until
        all {total} are saved; after that your ratings are locked.
      </p>
      <p className={styles.muted}>
        Tap Moment whenever you hear something you would correct or praise. It
        keeps the time in the call.
      </p>
    </div>
  );
}

function DimensionCard({
  dimension,
  saved,
  locked,
}: {
  dimension: Dimension;
  saved: Mine | null;
  locked: boolean;
}) {
  return (
    <>
      <div className={styles.pointerHead}>
        <span className={styles.number}>{dimension.number}</span>
        <div>
          <h2>{dimension.label}</h2>
          <div className={styles.tags}>
            <span className={styles.pill}>{dimension.category_label}</span>
            {locked ? (
              <span className={styles.pill} data-tone="warn">
                Locked
              </span>
            ) : null}
          </div>
        </div>
        <div className={styles.score}>
          <b>{saved?.rating ?? (saved?.skip ? "–" : "")}</b>
          <span>{saved ? "Your rating" : ""}</span>
        </div>
      </div>
      <p className={styles.said}>{dimension.about}</p>
      {dimension.scale ? (
        <details className={styles.more} open>
          <summary>What each rating means</summary>
          <p className={styles.said}>{dimension.scale}</p>
        </details>
      ) : null}
    </>
  );
}

function Ratings({
  saved,
  locked,
  onRate,
}: {
  saved: Mine | null;
  locked: boolean;
  onRate: (choice: number | DimensionSkip) => void;
}) {
  return (
    <>
      <p className={styles.ask}>
        {locked
          ? "Locked: Brain 4.0's ratings are shown."
          : "Your rating, from what you heard"}
      </p>
      <div className={styles.ratings}>
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            className={styles.rating}
            aria-pressed={saved?.rating === value}
            disabled={locked}
            onClick={() => onRate(value)}
          >
            {value}
          </button>
        ))}
      </div>
      <div className={styles.chipRow}>
        {(Object.keys(DIMENSION_SKIP_WORDS) as DimensionSkip[]).map(
          (reason) => (
            <button
              key={reason}
              type="button"
              className={styles.chip}
              aria-pressed={saved?.skip === reason}
              disabled={locked}
              onClick={() => onRate(reason)}
            >
              – {DIMENSION_SKIP_WORDS[reason]}
            </button>
          ),
        )}
      </div>
    </>
  );
}

function Reveal({
  dims,
  heads,
  reveal,
  segments,
  names,
  playing,
  onPlay,
}: {
  dims: Dimension[];
  heads: Map<string, SavedRow>;
  reveal: Workspace["brain4"];
  segments: Segment[];
  names: Map<string, string>;
  playing: number | null;
  onPlay: (ms: number) => void;
}) {
  if (!reveal || reveal.status !== "read")
    return (
      <div className={styles.done}>
        <span className={styles.pill} data-tone="good">
          All rated
        </span>
        <h2>Brain 4.0 hasn&apos;t read this call yet</h2>
        <p className={styles.muted}>
          Your ratings are saved and will be compared when it has. You can still
          note moments.
        </p>
      </div>
    );
  const theirs = new Map<string, Brain4Dimension>(
    reveal.dimensions.map((item) => [item.id, item]),
  );
  const bySegment = new Map(segments.map((segment) => [segment.id, segment]));
  return (
    <>
      <div className={styles.pointerHead}>
        <span className={styles.number}>B4</span>
        <div>
          <h2>Your ratings and Brain 4.0&apos;s</h2>
          <div className={styles.tags}>
            <span className={styles.pill} data-tone="accent">
              Brain 4.0 {reveal.label ?? "beta"}
            </span>
          </div>
        </div>
        <span />
      </div>
      <ul className={styles.list}>
        {dims.map((dimension) => {
          const yours = mine(heads.get(dimensionTarget(dimension.id)));
          const read = theirs.get(dimension.id);
          const theirRating =
            typeof read?.rating === "number" ? read.rating : null;
          const yourRating = yours?.rating ?? null;
          return (
            <li key={dimension.id}>
              <details className={styles.more}>
                <summary className={styles.compare}>
                  <span>
                    {dimension.number}. {dimension.label}
                  </span>
                  <span
                    className={styles.vs}
                    data-tone={compareTone(yourRating, theirRating)}
                    aria-label={`You ${yourRating ?? "no rating"}, Brain 4.0 ${theirRating ?? "no rating"}`}
                  >
                    {yourRating ?? "–"} · {theirRating ?? "–"}
                  </span>
                </summary>
                {read?.observed ? (
                  <p className={styles.said}>{read.observed}</p>
                ) : null}
                {read?.coaching ? (
                  <p className={styles.said}>
                    <b>Coaching: </b>
                    {read.coaching}
                  </p>
                ) : null}
                {(read?.evidence ?? []).map((item, i) => {
                  const segment = bySegment.get(item.segment_id ?? "");
                  return (
                    <blockquote
                      key={`${item.segment_id ?? i}-${i}`}
                      className={styles.quote}
                    >
                      {typeof item.start_ms === "number" ? (
                        <PlayChip
                          ms={item.start_ms}
                          playing={playing}
                          onPlay={onPlay}
                        />
                      ) : (
                        <span />
                      )}
                      <span>
                        {segment ? (
                          <span className={styles.speaker}>
                            {names.get(segment.speaker_id)}
                          </span>
                        ) : null}
                        {item.quote}
                      </span>
                    </blockquote>
                  );
                })}
              </details>
            </li>
          );
        })}
      </ul>
      <p className={styles.muted}>
        First number: yours. Second: Brain 4.0&apos;s. Tap a skill for what it
        saw and its coaching.
      </p>
    </>
  );
}

function Moments({
  rows,
  revealed,
  dims,
  playing,
  onPlay,
  onUpdate,
}: {
  rows: SavedRow[];
  revealed: boolean;
  dims: Dimension[];
  playing: number | null;
  onPlay: (ms: number) => void;
  onUpdate: (
    row: SavedRow,
    change: { caught?: Caught; removed?: boolean },
  ) => void;
}) {
  if (!rows.length) return null;
  const labels = new Map(dims.map((d) => [d.id, `${d.number}. ${d.label}`]));
  return (
    <section aria-label="Your moments" style={{ display: "grid", gap: 6 }}>
      <p className={styles.ask}>
        {revealed
          ? "Your moments: did Brain 4.0's coaching catch each one?"
          : "Your moments"}
      </p>
      {rows.map((row) => {
        const moment = row.value?.moment;
        if (!moment) return null;
        return (
          <div key={row.target} className={styles.moment}>
            <div className={styles.inline}>
              <PlayChip ms={moment.at_ms} playing={playing} onPlay={onPlay} />
              <span
                className={styles.pill}
                data-tone={moment.kind === "criticism" ? "bad" : "good"}
              >
                {moment.kind === "criticism" ? "Would correct" : "Went well"}
              </span>
              {moment.dimension ? (
                <span className={styles.muted}>
                  {labels.get(moment.dimension)}
                </span>
              ) : null}
            </div>
            <p className={styles.said}>{row.value?.opinion}</p>
            <div className={styles.inline}>
              {revealed
                ? (Object.keys(CAUGHT_WORDS) as Caught[]).map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={styles.chip}
                      aria-pressed={moment.caught === value}
                      onClick={() => onUpdate(row, { caught: value })}
                    >
                      {CAUGHT_WORDS[value]}
                    </button>
                  ))
                : null}
              <button
                type="button"
                className={styles.chip}
                onClick={() => onUpdate(row, { removed: true })}
              >
                Remove
              </button>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function MomentForm({
  at,
  dims,
  onSave,
  onCancel,
}: {
  at: number;
  dims: Dimension[];
  onSave: (
    at: number,
    kind: MomentKind,
    dimension: string,
    text: string,
  ) => void;
  onCancel: () => void;
}) {
  const [time, setTime] = useState(clock(at));
  const [kind, setKind] = useState<MomentKind>("criticism");
  const [dimension, setDimension] = useState("");
  const [text, setText] = useState("");
  const ms = parseClock(time);
  const ok = ms !== null && text.trim().length > 0;
  return (
    <form
      className={styles.field}
      onSubmit={(event) => {
        event.preventDefault();
        if (ok && ms !== null) onSave(ms, kind, dimension, text.trim());
      }}
    >
      <p className={styles.ask}>A moment in the call</p>
      <div className={styles.chipRow}>
        <button
          type="button"
          className={styles.chip}
          aria-pressed={kind === "criticism"}
          onClick={() => setKind("criticism")}
        >
          Would correct
        </button>
        <button
          type="button"
          className={styles.chip}
          aria-pressed={kind === "praise"}
          onClick={() => setKind("praise")}
        >
          Went well
        </button>
      </div>
      <div className={styles.inline}>
        <input
          className={styles.note}
          style={{ width: 90 }}
          value={time}
          inputMode="numeric"
          aria-label="Time in the call (minutes:seconds)"
          onChange={(event) => setTime(event.target.value)}
        />
        <select
          className={styles.note}
          style={{ flex: 1, width: "auto" }}
          value={dimension}
          aria-label="Which skill (optional)"
          onChange={(event) => setDimension(event.target.value)}
        >
          <option value="">Which skill? (optional)</option>
          {dims.map((d) => (
            <option key={d.id} value={d.id}>
              {d.number}. {d.label}
            </option>
          ))}
        </select>
      </div>
      <input
        className={styles.note}
        value={text}
        maxLength={600}
        placeholder="What happened, and what should have"
        aria-label="What happened at this moment"
        onChange={(event) => setText(event.target.value)}
      />
      <div className={styles.nav}>
        <button type="button" className={styles.navBtn} onClick={onCancel}>
          Cancel
        </button>
        <span />
        <button
          type="submit"
          className={styles.navBtn}
          data-primary=""
          disabled={!ok}
        >
          Save moment
        </button>
      </div>
    </form>
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
