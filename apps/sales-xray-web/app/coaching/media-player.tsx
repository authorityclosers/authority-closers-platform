"use client";

import { Play, Pause, RefreshCw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { clipSource, type CoachingClip } from "./media-contract";
import { timeLabel } from "./evidence-player";
import styles from "./coaching.module.css";

function ClipPlayer({ clip }: { clip: CoachingClip }) {
  const identity = useId();
  const player = useRef<HTMLAudioElement>(null);
  const active = useRef(false);
  const [state, setState] = useState<
    "idle" | "loading" | "playing" | "paused" | "done" | "failed"
  >("idle");
  const [attempt, setAttempt] = useState(0);
  const [slide, setSlide] = useState(0);
  useEffect(() => {
    const stopOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail === identity) return;
      active.current = false;
      player.current?.pause();
      setState("paused");
    };
    window.addEventListener("sx-coaching-play", stopOther);
    return () => window.removeEventListener("sx-coaching-play", stopOther);
  }, [identity]);
  const start = () => {
    window.dispatchEvent(
      new CustomEvent("sx-coaching-play", { detail: identity }),
    );
    active.current = true;
    setState("loading");
    setSlide(0);
    if (attempt === 0 || state === "failed") {
      setAttempt((value) => value + 1);
      return;
    }
    if (player.current) {
      player.current.currentTime = clip.start_ms / 1000;
      void player.current
        .play()
        .then(() => {
          if (active.current) setState("playing");
        })
        .catch(() => {
          if (active.current) setState("failed");
        });
    }
  };
  const currentSlide = clip.slides[slide];
  return (
    <article className={styles.evidence}>
      <div className={styles.meta}>
        <span>Placeholder · neutral narration</span>
        <span>{timeLabel(clip.end_ms - clip.start_ms)}</span>
      </div>
      <h3>{clip.title}</h3>
      <p>
        <strong>Why this fits your focus</strong>
        {clip.reason}
      </p>
      {currentSlide ? (
        <div className={styles.mediaSlide} aria-live="polite">
          <h4>{currentSlide.title}</h4>
          <ul>
            {currentSlide.bullets.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.button}
              disabled={slide === 0}
              onClick={() => setSlide((value) => value - 1)}
            >
              Previous slide
            </button>
            <span>
              {slide + 1} / {clip.slides.length}
            </span>
            <button
              type="button"
              className={styles.button}
              disabled={slide === clip.slides.length - 1}
              onClick={() => setSlide((value) => value + 1)}
            >
              Next slide
            </button>
          </div>
        </div>
      ) : null}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.button}
          disabled={state === "loading"}
          onClick={start}
        >
          {state === "failed" ? (
            <RefreshCw size={15} aria-hidden="true" />
          ) : (
            <Play size={15} aria-hidden="true" />
          )}
          {state === "loading"
            ? "Loading clip…"
            : state === "failed"
              ? "Try clip again"
              : state === "done"
                ? "Play again"
                : "Play coaching clip"}
        </button>
        {state === "playing" ? (
          <button
            type="button"
            className={styles.button}
            onClick={() => {
              active.current = false;
              player.current?.pause();
              setState("paused");
            }}
          >
            <Pause size={15} aria-hidden="true" />
            Pause
          </button>
        ) : null}
      </div>
      {attempt > 0 ? (
        <audio
          key={attempt}
          ref={player}
          src={clipSource(clip)}
          preload="metadata"
          aria-label="Placeholder coaching narration"
          onLoadedMetadata={() => {
            if (!player.current || !active.current) return;
            player.current.currentTime = clip.start_ms / 1000;
            void player.current
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
              player.current &&
              player.current.currentTime >= clip.end_ms / 1000 &&
              active.current
            ) {
              player.current.pause();
              active.current = false;
              setState("done");
            }
          }}
          onEnded={() => {
            active.current = false;
            setState("done");
          }}
          onError={() => {
            active.current = false;
            setState("failed");
          }}
        />
      ) : null}
      {state === "failed" ? (
        <p role="status">
          Narration is unavailable. Try again or read the clip below.
        </p>
      ) : null}
      <details className={styles.disclosure}>
        <summary>Read this clip</summary>
        <p>{clip.transcript_excerpt}</p>
        <ul>
          {clip.takeaways.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </details>
      <p className={styles.muted}>
        Dipak’s script · placeholder voice. Full coaching access. Listening does
        not complete your mission.
      </p>
    </article>
  );
}

export function CoachingMedia({ clips }: { clips?: CoachingClip[] }) {
  if (!clips?.length) return null;
  return (
    <div className={styles.story}>
      {clips.map((clip) => (
        <ClipPlayer
          key={`${clip.topic_id}:${clip.revision}:${clip.review_id}`}
          clip={clip}
        />
      ))}
    </div>
  );
}
