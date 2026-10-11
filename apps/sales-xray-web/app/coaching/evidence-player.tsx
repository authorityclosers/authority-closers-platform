"use client";

import { Pause, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { kitStyles } from "../ui/kit";
import type { Evidence } from "./coaching-client";
import { callDate, timeLabel } from "./coaching-format";
import styles from "./coaching.module.css";

export { timeLabel } from "./coaching-format";

/** One playable moment from the learner's own call, as a compact row. */
export function EvidencePlayer({
  evidence,
  showCall = true,
  extra = false,
}: {
  evidence: Evidence;
  /** Off when every moment on the page belongs to the same call. */
  showCall?: boolean;
  /** Folded on one-column screens until the learner asks for all moments. */
  extra?: boolean;
}) {
  const identity = useId();
  const audio = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">(
    "idle",
  );
  const [attempt, setAttempt] = useState(0);
  const active = useRef(false);
  const source = `/v1/conversation/acquisition/submissions/${evidence.submission_id}/source`;
  const span = `${timeLabel(evidence.start_ms)}–${timeLabel(evidence.end_ms)}`;
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
      {evidence.playable ? (
        <button
          type="button"
          className={styles.time}
          onClick={play}
          disabled={state === "loading"}
          data-state={state}
          aria-label={
            state === "playing"
              ? `Pause moment ${span}`
              : state === "failed"
                ? `Try audio again ${span}`
                : `Play evidence ${span}`
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
          <span>{span}</span>
          {state === "loading" ? <span>Loading audio…</span> : null}
          {!evidence.playable ? (
            <span>Audio alignment is uncertain; read the quote.</span>
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
          aria-label={`Call evidence from ${timeLabel(evidence.start_ms)}`}
          onLoadedMetadata={() => {
            if (audio.current && active.current) start(audio.current);
          }}
          onTimeUpdate={() => {
            if (
              audio.current &&
              audio.current.currentTime >= evidence.end_ms / 1000 &&
              active.current
            ) {
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
 * The moments behind a focus, every one inspectable (spec 5.5). One-column
 * screens open with one moment; the rest stay one tap away (spec 9, 12.7).
 */
export function MomentList({
  evidence,
  showCall = true,
  label = "Moments from your calls",
}: {
  evidence: Evidence[];
  showCall?: boolean;
  label?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
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
          />
        ))}
      </ul>
      {evidence.length > 1 && !expanded ? (
        <button
          type="button"
          className={`${kitStyles.button} ${styles.moreMoments}`}
          onClick={() => setExpanded(true)}
        >
          Show all {evidence.length} moments
        </button>
      ) : null}
    </>
  );
}
