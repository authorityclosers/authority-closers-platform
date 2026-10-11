"use client";

import { Pause, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";

import { ClipPlayState } from "../source-waveform";
import { kitStyles } from "../ui/kit";
import type { Evidence } from "./coaching-client";
import { callDate, timeLabel } from "./coaching-format";
import styles from "./coaching.module.css";

export { timeLabel } from "./coaching-format";

/** "15 s" or "1 min 5 s": how long the cut from the call is. */
export function clipLength(ms: number) {
  const seconds = Math.max(1, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  const rest = seconds % 60;
  return rest
    ? `${Math.floor(seconds / 60)} min ${rest} s`
    : `${seconds / 60} min`;
}

/** Plays a moment in the Report's own player, where the call is already open. */
export type PlayInReport = (evidence: Evidence, title: string) => void;

/** The Report's "With context": the moment with the lines around it. */
export type ContextPlay = {
  range: { start_ms: number; end_ms: number };
  play: () => void;
};

function ContextButton({ context }: { context: ContextPlay }) {
  return (
    <ClipPlayState
      startMs={context.range.start_ms}
      endMs={context.range.end_ms}
    >
      {(playing) => (
        <button
          type="button"
          className={styles.withContext}
          aria-pressed={playing}
          aria-label={`${playing ? "Pause context playback" : "Play with context"}, ${timeLabel(context.range.start_ms)}–${timeLabel(context.range.end_ms)}`}
          onClick={context.play}
        >
          {playing ? "Pause" : "With context"}
        </button>
      )}
    </ClipPlayState>
  );
}

/** The play pill when the Report's player plays the moment. */
function ReportPlay({
  evidence,
  span,
  onPlay,
}: {
  evidence: Evidence;
  span: string;
  onPlay: PlayInReport;
}) {
  return (
    <ClipPlayState startMs={evidence.start_ms} endMs={evidence.end_ms}>
      {(playing) => (
        <button
          type="button"
          className={styles.time}
          data-state={playing ? "playing" : "idle"}
          aria-pressed={playing}
          aria-label={`${playing ? "Pause" : "Play"} moment ${span}`}
          onClick={() => onPlay(evidence, "Coaching for this call")}
        >
          {playing ? (
            <Pause size={13} aria-hidden="true" />
          ) : (
            <Play size={13} aria-hidden="true" />
          )}
          {timeLabel(evidence.start_ms)}
        </button>
      )}
    </ClipPlayState>
  );
}

/** One playable moment from the learner's own call, as a compact row. */
export function EvidencePlayer({
  evidence,
  showCall = true,
  extra = false,
  fictional = false,
  onPlay,
  context,
}: {
  evidence: Evidence;
  /** Off when every moment on the page belongs to the same call. */
  showCall?: boolean;
  /** A fictional AC Sandbox call: text with estimated timing, no audio. */
  fictional?: boolean;
  /** Folded on one-column screens until the learner asks for all moments. */
  extra?: boolean;
  /** Inside a Report: play in its player instead of a separate audio. */
  onPlay?: PlayInReport;
  /** Inside a Report: also play the moment with the lines around it. */
  context?: ContextPlay | null;
}) {
  const identity = useId();
  const audio = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">(
    "idle",
  );
  const [attempt, setAttempt] = useState(0);
  // Where playback is inside this clip of the call, 0–1.
  const [progress, setProgress] = useState(0);
  const active = useRef(false);
  const source = `/v1/conversation/acquisition/submissions/${evidence.submission_id}/source`;
  const span = `${timeLabel(evidence.start_ms)}–${timeLabel(evidence.end_ms)}`;
  const length = Math.max(1, evidence.end_ms - evidence.start_ms);
  useEffect(() => {
    const stopOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail === identity) return;
      active.current = false;
      audio.current?.pause();
      setState("idle");
    };
    window.addEventListener("sx-coaching-play", stopOther);
    return () => window.removeEventListener("sx-coaching-play", stopOther);
  }, [identity]);
  const start = (player: HTMLAudioElement) => {
    player.currentTime = evidence.start_ms / 1000;
    setProgress(0);
    void player
      .play()
      .then(() => {
        if (active.current) setState("playing");
      })
      .catch(() => {
        if (active.current) setState("failed");
      });
  };
  const play = () => {
    if (state === "playing") {
      active.current = false;
      audio.current?.pause();
      setState("idle");
      return;
    }
    window.dispatchEvent(
      new CustomEvent("sx-coaching-play", { detail: identity }),
    );
    active.current = true;
    setState("loading");
    if (attempt === 0 || state === "failed") {
      setAttempt((value) => value + 1);
      return;
    }
    if (audio.current) start(audio.current);
  };
  const Icon =
    state === "playing" ? Pause : state === "failed" ? RefreshCw : Play;
  return (
    <li className={styles.moment} data-extra={extra ? "" : undefined}>
      {evidence.playable && onPlay ? (
        <ReportPlay evidence={evidence} span={span} onPlay={onPlay} />
      ) : evidence.playable ? (
        <button
          type="button"
          className={styles.time}
          onClick={play}
          disabled={state === "loading"}
          data-state={state}
          style={
            state === "playing"
              ? ({
                  "--clip": `${Math.round(progress * 100)}%`,
                } as CSSProperties)
              : undefined
          }
          aria-label={
            state === "playing"
              ? `Pause moment ${span}`
              : state === "failed"
                ? `Try audio again ${span}`
                : `Play moment ${span}`
          }
        >
          <Icon size={13} aria-hidden="true" />
          {timeLabel(evidence.start_ms)}
        </button>
      ) : (
        <span className={styles.time} aria-label={`Moment at ${span}`}>
          {timeLabel(evidence.start_ms)}
        </span>
      )}
      <div className={styles.momentBody}>
        <blockquote className={styles.quote}>{evidence.quote}</blockquote>
        <p className={styles.momentNote}>{evidence.observation}</p>
        <span className={styles.momentMeta}>
          {showCall ? (
            <>
              <Link href={`/coaching?call=${evidence.submission_id}`}>
                {evidence.call_label}
              </Link>
              <span>{callDate(evidence.created_at)}</span>
            </>
          ) : null}
          <span>
            {span}
            {evidence.playable ? ` · ${clipLength(length)} clip` : ""}
          </span>
          {state === "loading" ? <span>Loading audio…</span> : null}
          {context && onPlay ? <ContextButton context={context} /> : null}
          {!evidence.playable ? (
            <span>
              {fictional
                ? "Fictional call text; no audio."
                : "We couldn’t match this to the audio. Read the quote."}
            </span>
          ) : null}
        </span>
        {state === "failed" ? (
          <p role="status" className={styles.status}>
            Audio could not be played. Try audio again; the quote stays here.
          </p>
        ) : null}
      </div>
      {attempt > 0 ? (
        <audio
          key={attempt}
          ref={audio}
          src={source}
          preload="metadata"
          aria-label={`Moment from ${timeLabel(evidence.start_ms)}`}
          onLoadedMetadata={() => {
            if (audio.current && active.current) start(audio.current);
          }}
          onTimeUpdate={() => {
            if (!audio.current || !active.current) return;
            const at = audio.current.currentTime * 1000 - evidence.start_ms;
            setProgress(Math.min(1, Math.max(0, at / length)));
            if (audio.current.currentTime >= evidence.end_ms / 1000) {
              audio.current.pause();
              active.current = false;
              setState("idle");
            }
          }}
          onError={() => {
            active.current = false;
            setState("failed");
          }}
        />
      ) : null}
    </li>
  );
}

/**
 * The moments behind a focus, every one inspectable (spec 5.5). Wide screens
 * open with two moments and one-column screens with one; the rest stay one
 * tap away (spec 9, 12.7).
 */
export function MomentList({
  evidence,
  showCall = true,
  label = "Moments from your calls",
  heading,
  fictional = false,
  onPlay,
  contextFor,
}: {
  evidence: Evidence[];
  showCall?: boolean;
  label?: string;
  /** A visible label line above the list, with the moment count. */
  heading?: string;
  fictional?: boolean;
  onPlay?: PlayInReport;
  contextFor?: (evidence: Evidence) => ContextPlay | null;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      {heading ? (
        <p className={styles.listHead}>
          {heading}
          <span>
            {evidence.length} moment{evidence.length === 1 ? "" : "s"}
          </span>
        </p>
      ) : null}
      <ul
        className={styles.moments}
        aria-label={label}
        data-expanded={expanded ? "" : undefined}
      >
        {evidence.map((moment, index) => (
          <EvidencePlayer
            key={`${moment.submission_id}:${moment.segment_id}:${moment.start_ms}`}
            evidence={moment}
            showCall={showCall}
            extra={index >= 1}
            fictional={fictional}
            onPlay={onPlay}
            context={contextFor?.(moment)}
          />
        ))}
      </ul>
      {evidence.length > 1 && !expanded ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.moreMoments}`}
          data-many={evidence.length > 2 ? "" : undefined}
          onClick={() => setExpanded(true)}
        >
          Show all {evidence.length} moments
        </button>
      ) : null}
    </>
  );
}
