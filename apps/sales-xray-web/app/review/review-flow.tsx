"use client";

/**
 * One call, one line at a time (owner, 19 Oct). Top half: what the AI said and
 * the lines it rests on, with play-from-here. Bottom half: Agree / Partly /
 * Disagree, the right status or score, reasons, an optional note, and Back,
 * Skip and Next. Agree saves and moves on at once; saves run in order behind
 * the screen, so the next line is already there.
 */

import { ArrowLeft, ChevronLeft, Pause, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { notify } from "../notice-center";
import { BlindFlow } from "./blind-flow";
import { ReportFlow } from "./report-flow";
import {
  REASONS,
  REASON_WORDS,
  SKIP_WORDS,
  STATUSES,
  STATUS_WORDS,
  asPointer,
  callName,
  clock,
  headsByTarget,
  readWorkspace,
  saveLine,
  type AiStatus,
  type LineSave,
  type Reason,
  type SavedRow,
  type Segment,
  type SkipReason,
  type Verdict,
  type Workspace,
} from "./review-client";
import styles from "./review.module.css";

type Draft = {
  verdict: Verdict | null;
  status: AiStatus | null;
  score: number | null;
  reasons: Reason[];
  note: string;
};

const EMPTY: Draft = {
  verdict: null,
  status: null,
  score: null,
  reasons: [],
  note: "",
};

export function toneOf(status: unknown): "good" | "warn" | "bad" | undefined {
  if (status === "excellent" || status === "good") return "good";
  if (status === "average") return "warn";
  if (status === "needs_improvement") return "bad";
  return undefined;
}

function draftFrom(row: SavedRow | undefined): Draft {
  const value = row?.value;
  if (!value || value.skip) return EMPTY;
  return {
    // "fix" belongs to the Report review; a line save never carries it.
    verdict: value.verdict === "fix" ? null : (value.verdict ?? null),
    status: value.status ?? null,
    score: value.score ?? null,
    reasons: value.reasons ?? [],
    note: value.opinion ?? "",
  };
}

function firstOpen(lines: Workspace["lines"], heads: Map<string, SavedRow>) {
  const index = lines.findIndex((line) => !heads.has(line.target));
  return index === -1 ? lines.length : index;
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

export function ReviewFlowSkeleton() {
  return (
    <div className={styles.flow} aria-busy="true" aria-label="Loading review">
      <div className={styles.top}>
        <div className={styles.topLine}>
          <span className={styles.skeleton} style={{ width: 32, height: 32 }} />
          <span className={styles.skeleton} style={{ flex: 1, height: 16 }} />
        </div>
        <div className={styles.bar} />
      </div>
      <div className={styles.evidence}>
        <span className={styles.skeleton} style={{ height: 30 }} />
        <span className={styles.skeleton} style={{ height: 48 }} />
        <span className={styles.skeleton} style={{ height: 64 }} />
      </div>
      <div className={styles.choices}>
        <span className={styles.skeleton} style={{ height: 52 }} />
        <span className={styles.skeleton} style={{ height: 44 }} />
      </div>
    </div>
  );
}

export function ReviewFlow({
  assignmentId,
  onFinished,
}: {
  assignmentId: string;
  onFinished: () => void;
}) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [heads, setHeads] = useState<Map<string, SavedRow>>(new Map());
  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [skipping, setSkipping] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const headsRef = useRef(heads);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const shownAt = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    const controller = new AbortController();
    readWorkspace(assignmentId, controller.signal)
      .then((data) => {
        const map = headsByTarget(data.saved);
        headsRef.current = map;
        setHeads(map);
        setWorkspace(data);
        setFailed(null);
        const start = firstOpen(data.lines, map);
        setIndex(start);
        setDraft(draftFrom(map.get(data.lines[start]?.target ?? "")));
        shownAt.current = Date.now();
      })
      .catch((error: Error) => {
        if (error.name !== "AbortError") setFailed(error.message);
      });
    return () => controller.abort();
  }, [assignmentId]);

  useEffect(() => load(), [load]);

  const lines = useMemo(() => workspace?.lines ?? [], [workspace]);
  const line = lines[index];
  const pointer = asPointer(line?.ai);
  const segments = useMemo(
    () => workspace?.transcript.segments ?? [],
    [workspace],
  );
  const names = useMemo(() => speakerNames(segments), [segments]);
  const handled = heads.size;

  const go = useCallback(
    (next: number) => {
      const bounded = Math.max(0, Math.min(next, lines.length));
      setIndex(bounded);
      setDraft(draftFrom(headsRef.current.get(lines[bounded]?.target ?? "")));
      setSkipping(false);
      shownAt.current = Date.now();
      scroller.current?.scrollTo({ top: 0 });
    },
    [lines],
  );

  const persist = useCallback(
    (target: string, value: LineSave) => {
      if (!workspace) return;
      const key =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;
      // Saves go one after another, each superseding the line's newest save.
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
        } catch (error) {
          notify({
            id: `review-save-${target}`,
            tone: "error",
            title: "A line didn't save",
            message: (error as Error).message,
            action: { label: "Reload", run: () => load() },
          });
        }
      });
    },
    [assignmentId, workspace, load],
  );

  const seconds = () =>
    Math.min(900, Math.round((Date.now() - shownAt.current) / 1000));

  const unchanged = (target: string) => {
    const saved = draftFrom(headsRef.current.get(target));
    return (
      headsRef.current.has(target) &&
      !headsRef.current.get(target)?.value?.skip &&
      JSON.stringify(saved) === JSON.stringify(draft)
    );
  };

  const commit = useCallback(
    (value: Draft) => {
      if (!line) return;
      if (!value.verdict && value.score === null) return;
      persist(line.target, {
        verdict: value.verdict,
        status: value.verdict === "agree" ? null : value.status,
        score: value.verdict === "agree" ? null : value.score,
        reasons: value.verdict === "agree" ? [] : value.reasons,
        opinion: value.note.trim(),
        seconds: seconds(),
      });
    },
    [line, persist],
  );

  function choose(verdict: Verdict) {
    const next = { ...draft, verdict };
    setDraft(next);
    if (verdict === "agree" && line) {
      if (!unchanged(line.target) || draft.verdict !== "agree") commit(next);
      go(index + 1);
    }
  }

  function next() {
    if (!line) return;
    if ((draft.verdict || draft.score !== null) && !unchanged(line.target))
      commit(draft);
    go(index + 1);
  }

  function skip(reason: SkipReason) {
    if (!line) return;
    persist(line.target, { skip: reason, seconds: seconds() });
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

  // Keys for desktop reviewers: 1 2 3 choose, arrows move, S skips.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        workspace?.mode === "brain4_blind" ||
        workspace?.mode === "report" ||
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      )
        return;
      if (event.key === "1") choose("agree");
      else if (event.key === "2") choose("partly");
      else if (event.key === "3") choose("disagree");
      else if (event.key === "ArrowRight") next();
      else if (event.key === "ArrowLeft") go(index - 1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (failed)
    return (
      <div className={styles.root}>
        <div className={styles.panel}>
          <h2>This review didn&apos;t open</h2>
          <p className={styles.muted}>{failed}</p>
          <div className={styles.inline}>
            <button type="button" className={styles.navBtn} onClick={load}>
              Try again
            </button>
            <button
              type="button"
              className={styles.navBtn}
              onClick={onFinished}
            >
              Back to the queue
            </button>
          </div>
        </div>
      </div>
    );
  if (!workspace) return <ReviewFlowSkeleton />;
  if (workspace.mode === "brain4_blind")
    return (
      <BlindFlow
        assignmentId={assignmentId}
        workspace={workspace}
        onFinished={onFinished}
        onReload={load}
      />
    );
  if (workspace.mode === "report")
    return (
      <ReportFlow
        assignmentId={assignmentId}
        workspace={workspace}
        onFinished={onFinished}
        onReload={load}
      />
    );

  const total = lines.length;
  const name = callName(
    workspace.context?.recorded_at ?? "",
    workspace.context?.duration_ms,
  );

  return (
    <div className={styles.flow}>
      <audio
        ref={audio}
        src={workspace.audio_source_url}
        preload="none"
        onPause={() => setPlaying(null)}
        onEnded={() => setPlaying(null)}
      />
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
          {playing !== null ? (
            <button
              type="button"
              onClick={() => audio.current?.pause()}
              aria-label="Pause the recording"
            >
              <Pause size={14} aria-hidden="true" />
            </button>
          ) : null}
          <span className={styles.counter} aria-live="polite">
            {Math.min(index + 1, total)}/{total} · {handled} done
          </span>
        </div>
        <div
          className={styles.bar}
          role="progressbar"
          aria-label="Lines reviewed"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={handled}
        >
          <span style={{ width: `${(handled / Math.max(total, 1)) * 100}%` }} />
        </div>
      </div>

      {index >= total ? (
        <div className={styles.evidence}>
          <div className={styles.done}>
            <span className={styles.pill} data-tone="good">
              {handled}/{total} lines
            </span>
            <h2>This call is reviewed</h2>
            <p className={styles.muted}>
              Every save is already in the gold set. You can go back to any line
              and change it; the newest answer counts.
            </p>
          </div>
        </div>
      ) : (
        <div className={styles.evidence} ref={scroller}>
          <Evidence
            line={line}
            pointer={pointer}
            segments={segments}
            names={names}
            playing={playing}
            onPlay={playFrom}
            context={index === 0 ? workspace.context : undefined}
          />
        </div>
      )}

      <div className={styles.choices}>
        {index >= total ? (
          <div className={styles.nav}>
            <button
              type="button"
              className={styles.navBtn}
              onClick={() => go(total - 1)}
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
            <p className={styles.ask}>Why skip this line?</p>
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
          <Choices
            draft={draft}
            setDraft={setDraft}
            aiStatus={pointer?.status}
            aiScore={typeof pointer?.score === "number" ? pointer.score : null}
            isPointer={pointer !== null}
            onChoose={choose}
            onBack={() => go(index - 1)}
            onSkip={() => setSkipping(true)}
            onNext={next}
            canBack={index > 0}
            savedSkip={heads.get(line?.target ?? "")?.value?.skip}
          />
        )}
      </div>
    </div>
  );
}

function Evidence({
  line,
  pointer,
  segments,
  names,
  playing,
  onPlay,
  context,
}: {
  line: Workspace["lines"][number] | undefined;
  pointer: ReturnType<typeof asPointer>;
  segments: Segment[];
  names: Map<string, string>;
  playing: number | null;
  onPlay: (ms: number) => void;
  context?: Workspace["context"];
}) {
  if (!line) return null;
  const about = context?.summary ? (
    <details className={styles.more}>
      <summary>About this call</summary>
      <p className={styles.said}>{context.summary}</p>
    </details>
  ) : null;
  if (!pointer)
    return (
      <>
        {about}
        <div className={styles.pointerHead}>
          <span className={styles.number}>
            {line.target === "coaching" ? "C" : "O"}
          </span>
          <div>
            <h2>{line.label}</h2>
            <div className={styles.tags}>
              <span className={styles.pill} data-tone="accent">
                AI draft
              </span>
            </div>
          </div>
          <span />
        </div>
        <OtherLine target={line.target} ai={line.ai} />
      </>
    );

  const quotes = (pointer.evidence ?? []).filter(
    (item) => typeof item.quote === "string" && item.quote,
  );
  const byId = new Map(segments.map((segment, i) => [segment.id, i]));
  const shown = new Set<string>();
  const status = typeof pointer.status === "string" ? pointer.status : null;
  return (
    <>
      {about}
      <div className={styles.pointerHead}>
        <span className={styles.number}>{pointer.number}</span>
        <div>
          <h2>{pointer.label}</h2>
          <div className={styles.tags}>
            <span className={styles.pill} data-tone="accent">
              AI draft
            </span>
            {status ? (
              <span className={styles.pill} data-tone={toneOf(status)}>
                {STATUS_WORDS[status as AiStatus] ?? status}
              </span>
            ) : null}
          </div>
        </div>
        <div className={styles.score}>
          <b>{typeof pointer.score === "number" ? pointer.score : "–"}</b>
          <span>AI score</span>
        </div>
      </div>
      {pointer.what_happened ? (
        <p className={styles.said}>{pointer.what_happened}</p>
      ) : null}
      {quotes.length ? (
        quotes.map((item, i) => {
          const at = byId.get(item.segment_id ?? "");
          const before = at !== undefined ? segments[at - 1] : undefined;
          const after = at !== undefined ? segments[at + 1] : undefined;
          const speaker =
            at !== undefined ? names.get(segments[at].speaker_id) : undefined;
          return (
            <div
              key={`${item.segment_id ?? i}-${i}`}
              style={{ display: "grid", gap: 4 }}
            >
              {before && !shown.has(before.id) && shown.add(before.id) ? (
                <Near
                  segment={before}
                  names={names}
                  onPlay={onPlay}
                  playing={playing}
                />
              ) : null}
              <blockquote className={styles.quote}>
                {typeof item.start_ms === "number" ? (
                  <PlayButton
                    ms={item.start_ms}
                    playing={playing}
                    onPlay={onPlay}
                  />
                ) : (
                  <span />
                )}
                <span>
                  {speaker ? (
                    <span className={styles.speaker}>{speaker}</span>
                  ) : null}
                  {item.quote}
                </span>
              </blockquote>
              {after && !shown.has(after.id) && shown.add(after.id) ? (
                <Near
                  segment={after}
                  names={names}
                  onPlay={onPlay}
                  playing={playing}
                />
              ) : null}
            </div>
          );
        })
      ) : (
        <p className={styles.muted}>
          The AI quoted no lines for this one. Judge it from the call; tap About
          this call or play the recording from a line you remember.
        </p>
      )}
      {pointer.how_to_improve?.length || pointer.why_it_matters ? (
        <details className={styles.more}>
          <summary>The AI&apos;s advice</summary>
          {pointer.why_it_matters ? (
            <p className={styles.said}>{pointer.why_it_matters}</p>
          ) : null}
          {pointer.how_to_improve?.length ? (
            <ul>
              {pointer.how_to_improve.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          ) : null}
        </details>
      ) : null}
    </>
  );
}

function PlayButton({
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

function Near({
  segment,
  names,
  playing,
  onPlay,
}: {
  segment: Segment;
  names: Map<string, string>;
  playing: number | null;
  onPlay: (ms: number) => void;
}) {
  return (
    <blockquote className={styles.quote} data-near="">
      <PlayButton ms={segment.start_ms} playing={playing} onPlay={onPlay} />
      <span>
        <span className={styles.speaker}>{names.get(segment.speaker_id)}</span>
        {segment.text}
      </span>
    </blockquote>
  );
}

function strings(value: unknown, key?: string): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) =>
      typeof item === "string"
        ? item
        : key && item && typeof item === "object"
          ? String((item as Record<string, unknown>)[key] ?? "")
          : "",
    )
    .filter(Boolean);
}

function OtherLine({ target, ai }: { target: string; ai: unknown }) {
  if (target === "coaching") {
    const items = Array.isArray(ai)
      ? (ai as { pointer?: string; tips?: string[]; topic?: string }[])
      : [];
    return (
      <ul className={styles.list}>
        {items.map((item, i) => (
          <li key={`${item.pointer}-${i}`} className={styles.row}>
            <span>
              <b>{item.pointer}</b>
              {item.topic ? (
                <span className={styles.muted}> · {item.topic}</span>
              ) : null}
              {item.tips?.[0] ? (
                <span className={styles.said} style={{ display: "block" }}>
                  {item.tips[0]}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  const outcome =
    ai && typeof ai === "object" ? (ai as Record<string, unknown>) : {};
  const parts: [string, string[]][] = [
    ["Why it ended this way", strings(outcome.reasons)],
    ["Next steps", strings(outcome.next_steps, "text")],
    ["Objections", strings(outcome.objections, "text")],
    ["Notes", strings(outcome.notes)],
  ];
  return (
    <>
      {parts
        .filter(([, items]) => items.length)
        .map(([title, items]) => (
          <div key={title} style={{ display: "grid", gap: 4 }}>
            <p className={styles.ask}>{title}</p>
            <ul className={styles.more} style={{ margin: 0, paddingLeft: 18 }}>
              {items.map((item) => (
                <li key={item} className={styles.said}>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </>
  );
}

function Choices({
  draft,
  setDraft,
  aiStatus,
  aiScore,
  isPointer,
  onChoose,
  onBack,
  onSkip,
  onNext,
  canBack,
  savedSkip,
}: {
  draft: Draft;
  setDraft: (draft: Draft) => void;
  aiStatus: string | undefined;
  aiScore: number | null;
  isPointer: boolean;
  onChoose: (verdict: Verdict) => void;
  onBack: () => void;
  onSkip: () => void;
  onNext: () => void;
  canBack: boolean;
  savedSkip: SkipReason | undefined;
}) {
  const detail = draft.verdict === "partly" || draft.verdict === "disagree";
  const score = draft.score ?? aiScore ?? 50;
  const verdicts: [Verdict, string, string, "good" | "warn" | "bad"][] = [
    ["agree", "Agree", "AI is right", "good"],
    ["partly", "Partly", "Close, not quite", "warn"],
    ["disagree", "Disagree", "AI is wrong", "bad"],
  ];
  return (
    <>
      <p className={styles.ask}>
        {savedSkip
          ? `Skipped (${SKIP_WORDS[savedSkip]}). Judge it now or move on.`
          : "Is the AI right about this?"}
      </p>
      <div className={styles.verdicts}>
        {verdicts.map(([value, label, hint, tone]) => (
          <button
            key={value}
            type="button"
            className={styles.verdict}
            data-tone={tone}
            aria-pressed={draft.verdict === value}
            onClick={() => onChoose(value)}
          >
            {label}
            <small>{hint}</small>
          </button>
        ))}
      </div>
      {detail ? (
        <>
          {isPointer ? (
            <div className={styles.field}>
              <span className={styles.ask}>The right status</span>
              <div className={styles.chipRow}>
                {STATUSES.map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={styles.chip}
                    data-ai={status === aiStatus ? "" : undefined}
                    aria-pressed={draft.status === status}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        status: draft.status === status ? null : status,
                      })
                    }
                  >
                    {STATUS_WORDS[status]}
                    {status === aiStatus ? " (AI)" : ""}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className={styles.inline}>
            <span className={styles.ask}>The right score</span>
            <div className={styles.stepper}>
              <button
                type="button"
                aria-label="Five points lower"
                onClick={() =>
                  setDraft({ ...draft, score: Math.max(0, score - 5) })
                }
              >
                −
              </button>
              <output aria-live="polite">{draft.score ?? "–"}</output>
              <button
                type="button"
                aria-label="Five points higher"
                onClick={() =>
                  setDraft({ ...draft, score: Math.min(100, score + 5) })
                }
              >
                +
              </button>
            </div>
            {aiScore !== null ? (
              <span className={styles.muted}>AI said {aiScore}</span>
            ) : null}
          </div>
          <div className={styles.field}>
            <span className={styles.ask}>Why</span>
            <div className={styles.chipRow}>
              {REASONS.map((reason) => {
                const on = draft.reasons.includes(reason);
                return (
                  <button
                    key={reason}
                    type="button"
                    className={styles.chip}
                    aria-pressed={on}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        reasons: on
                          ? draft.reasons.filter((item) => item !== reason)
                          : [...draft.reasons, reason].slice(0, 6),
                      })
                    }
                  >
                    {REASON_WORDS[reason]}
                  </button>
                );
              })}
            </div>
          </div>
          <input
            className={styles.note}
            value={draft.note}
            maxLength={4000}
            placeholder="A short note (optional)"
            aria-label="A short note (optional)"
            onChange={(event) =>
              setDraft({ ...draft, note: event.target.value })
            }
          />
        </>
      ) : null}
      <div className={styles.nav}>
        <button
          type="button"
          className={styles.navBtn}
          onClick={onBack}
          disabled={!canBack}
        >
          <ChevronLeft size={16} aria-hidden="true" /> Back
        </button>
        <button type="button" className={styles.navBtn} onClick={onSkip}>
          Skip
        </button>
        <button
          type="button"
          className={styles.navBtn}
          data-primary=""
          onClick={onNext}
        >
          {draft.verdict && draft.verdict !== "agree" ? "Save & next" : "Next"}
        </button>
      </div>
    </>
  );
}
