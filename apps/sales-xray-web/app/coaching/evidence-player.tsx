"use client";

import { Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import type { Evidence } from "./coaching-client";
import styles from "./coaching.module.css";

export function timeLabel(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function EvidencePlayer({ evidence }: { evidence: Evidence }) {
  const identity = useId();
  const audio = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">(
    "idle",
  );
  const [attempt, setAttempt] = useState(0);
  const active = useRef(false);
  const source = `/v1/conversation/acquisition/submissions/${evidence.submission_id}/source`;
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
  const play = () => {
    window.dispatchEvent(
      new CustomEvent("sx-coaching-play", { detail: identity }),
    );
    active.current = true;
    setState("loading");
    if (state === "idle" || state === "failed") {
      setAttempt((value) => value + 1);
      return;
    }
    const player = audio.current;
    if (player) {
      player.currentTime = evidence.start_ms / 1000;
      void player
        .play()
        .then(() => {
          if (active.current) setState("playing");
        })
        .catch(() => {
          if (active.current) setState("failed");
        });
    }
  };
  return (
    <article className={styles.evidence}>
      <div className={styles.meta}>
        <Link href={`/analysis/calls/${evidence.submission_id}`}>
          {evidence.call_label}
        </Link>
        <span>
          {new Date(evidence.created_at).toLocaleDateString(undefined, {
            dateStyle: "medium",
          })}
        </span>
      </div>
      <blockquote>{evidence.quote}</blockquote>
      <p>{evidence.observation}</p>
      {evidence.playable ? (
        <>
          <button
            type="button"
            className={styles.button}
            onClick={play}
            disabled={state === "loading"}
          >
            {state === "failed" ? (
              <RefreshCw size={15} aria-hidden="true" />
            ) : (
              <Play size={15} aria-hidden="true" />
            )}
            {state === "loading"
              ? "Loading audio…"
              : state === "failed"
                ? "Try audio again"
                : "Play evidence"}
            <span>
              {timeLabel(evidence.start_ms)}–{timeLabel(evidence.end_ms)}
            </span>
          </button>
          {attempt > 0 ? (
            <audio
              key={attempt}
              ref={audio}
              src={source}
              controls
              preload="metadata"
              aria-label={`Call evidence from ${timeLabel(evidence.start_ms)}`}
              onLoadedMetadata={() => {
                const player = audio.current;
                if (!player || !active.current) return;
                player.currentTime = evidence.start_ms / 1000;
                void player
                  .play()
                  .then(() => {
                    if (active.current) setState("playing");
                  })
                  .catch(() => {
                    if (active.current) setState("failed");
                  });
              }}
              onTimeUpdate={() => {
                if (
                  audio.current &&
                  audio.current.currentTime >= evidence.end_ms / 1000 &&
                  active.current
                ) {
                  audio.current.pause();
                  active.current = false;
                }
              }}
              onError={() => {
                active.current = false;
                setState("failed");
              }}
            />
          ) : null}
          {state === "failed" ? (
            <p role="status">
              Audio could not be played. The transcript and call remain
              inspectable.
            </p>
          ) : null}
        </>
      ) : (
        <p>Audio alignment is uncertain. Inspect the transcript above.</p>
      )}
    </article>
  );
}
