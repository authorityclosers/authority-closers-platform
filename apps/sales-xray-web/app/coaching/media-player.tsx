"use client";

import { Lock, Pause, Play, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Badge, kitStyles } from "../ui/kit";
import {
  clipSource,
  FULL_COACHING_HREF,
  type CoachingClip,
} from "./media-contract";
import { timeLabel } from "./coaching-format";
import styles from "./coaching.module.css";

type ClipState =
  | "idle"
  | "loading"
  | "playing"
  | "paused"
  | "done"
  | "limit"
  | "failed";

const PLAY_LABEL: Record<ClipState, string> = {
  idle: "Play coaching clip",
  loading: "Loading clip…",
  playing: "Pause",
  paused: "Resume clip",
  done: "Play again",
  limit: "Preview finished",
  failed: "Try clip again",
};

/** The funnel to Dipak's full coaching: credits and entitlements only. */
export function ClipOfferCard({
  clip,
  finished,
}: {
  clip: CoachingClip;
  finished: boolean;
}) {
  const offer = clip.offer;
  return (
    <div className={styles.offer} role="group" aria-label="Full coaching">
      <div className={styles.offerHead}>
        <span className={styles.offerIcon} aria-hidden="true">
          <Lock size={14} />
        </span>
        <div>
          <strong>
            {finished
              ? "That’s the free preview"
              : "Part of Dipak’s full coaching"}
          </strong>
          <p>
            Hear the complete lesson and every clip for this skill with full
            coaching.
          </p>
        </div>
      </div>
      <div className={styles.actions}>
        <Link
          href={offer?.full_coaching_href ?? FULL_COACHING_HREF}
          className={kitStyles.button}
          data-variant="primary"
        >
          Get the full coaching
        </Link>
        {offer?.academy ? (
          <a
            href={offer.academy.href}
            className={kitStyles.button}
            target="_blank"
            rel="noopener noreferrer"
            title={offer.academy.label}
          >
            Open the course on the Learner’s Academy
          </a>
        ) : null}
      </div>
    </div>
  );
}

function ClipCard({
  clip,
  recommended,
}: {
  clip: CoachingClip;
  recommended: boolean;
}) {
  const identity = useId();
  const player = useRef<HTMLAudioElement>(null);
  const active = useRef(false);
  const [state, setState] = useState<ClipState>("idle");
  const [attempt, setAttempt] = useState(0);
  const [slide, setSlide] = useState(0);
  const [position, setPosition] = useState(0);
  const locked = clip.access === "locked";
  const length = clip.end_ms - clip.start_ms;
  // The server decides the window; the player only stops where it was told.
  const stopAt =
    clip.access === "preview" && clip.preview_end_ms
      ? clip.preview_end_ms
      : clip.end_ms;
  useEffect(() => {
    const stopOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail === identity) return;
      if (!active.current) return;
      active.current = false;
      player.current?.pause();
      setState("paused");
    };
    window.addEventListener("sx-coaching-play", stopOther);
    return () => window.removeEventListener("sx-coaching-play", stopOther);
  }, [identity]);
  const begin = (audio: HTMLAudioElement, from: number) => {
    audio.currentTime = from / 1000;
    void audio
      .play()
      .then(() => {
        if (active.current) setState("playing");
      })
      .catch(() => {
        if (active.current) setState("failed");
      });
  };
  const toggle = () => {
    if (locked || state === "limit") return;
    if (state === "playing") {
      active.current = false;
      player.current?.pause();
      setState("paused");
      return;
    }
    window.dispatchEvent(
      new CustomEvent("sx-coaching-play", { detail: identity }),
    );
    active.current = true;
    if (attempt === 0 || state === "failed") {
      setState("loading");
      setPosition(0);
      setAttempt((value) => value + 1);
      return;
    }
    const audio = player.current;
    if (!audio) return;
    const resume =
      state === "paused" && position > 0 && clip.start_ms + position < stopAt;
    setState("loading");
    if (!resume) setPosition(0);
    begin(audio, resume ? clip.start_ms + position : clip.start_ms);
  };
  const currentSlide = clip.slides[slide];
  const preview =
    clip.access === "preview" && clip.preview_end_ms
      ? clip.preview_end_ms - clip.start_ms
      : null;
  const Icon =
    state === "playing"
      ? Pause
      : state === "failed"
        ? RefreshCw
        : state === "done"
          ? RotateCcw
          : Play;
  return (
    <article
      className={styles.clip}
      data-recommended={recommended ? "" : undefined}
      data-access={clip.access}
    >
      <div className={styles.clipHead}>
        <button
          type="button"
          className={styles.clipPlay}
          onClick={toggle}
          disabled={state === "loading" || state === "limit"}
          data-locked={locked ? "" : undefined}
          aria-disabled={locked || undefined}
          title={locked ? "Part of the full coaching" : PLAY_LABEL[state]}
        >
          {locked ? (
            <Lock size={16} aria-hidden="true" />
          ) : (
            <Icon size={16} aria-hidden="true" />
          )}
          <span className={styles.srOnly}>
            {locked ? "Locked coaching clip" : PLAY_LABEL[state]}
          </span>
        </button>
        <div className={styles.clipTitle}>
          <span className={styles.eyebrow}>
            {recommended ? "Recommended for your focus" : "Also relevant"}
          </span>
          <h3>{clip.title}</h3>
          <span className={styles.note}>
            Dipak’s script · {clip.kind === "video" ? "video" : "audio"} lesson
            · placeholder voice · {timeLabel(length)}
          </span>
        </div>
        {clip.access === "preview" && preview ? (
          <Badge tone="accent">Free preview · {timeLabel(preview)}</Badge>
        ) : locked ? (
          <Badge>Full coaching</Badge>
        ) : null}
      </div>
      {locked ? null : (
        <div>
          <div
            className={styles.bar}
            role="progressbar"
            aria-label="Clip progress"
            aria-valuemin={0}
            aria-valuemax={Math.round(length / 1000)}
            aria-valuenow={Math.round(position / 1000)}
          >
            <i
              style={{ width: `${Math.min(100, (position / length) * 100)}%` }}
            />
            {preview ? (
              <b
                style={{ left: `${(preview / length) * 100}%` }}
                title="End of the free preview"
              />
            ) : null}
          </div>
          <div className={styles.barTimes}>
            <span>{timeLabel(position)}</span>
            <span>
              {state === "loading"
                ? "Loading…"
                : state === "playing"
                  ? "Playing"
                  : timeLabel(length)}
            </span>
          </div>
        </div>
      )}
      <p>
        <span className={styles.label}>Why this fits your focus</span>
        {clip.reason}
      </p>
      <ul className={styles.takeaways}>
        {clip.takeaways.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {locked || state === "limit" ? (
        <ClipOfferCard clip={clip} finished={state === "limit"} />
      ) : null}
      {state === "failed" ? (
        <p role="status" className={styles.status}>
          Narration is unavailable. Try again, or read the clip below.
        </p>
      ) : null}
      {locked ? null : (
        <details className={styles.more}>
          <summary>Read this clip</summary>
          <div className={styles.moreBody}>
            {currentSlide ? (
              <div className={styles.slide} aria-live="polite">
                <strong>{currentSlide.title}</strong>
                <ul className={styles.takeaways}>
                  {currentSlide.bullets.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <div className={styles.slideNav}>
                  <button
                    type="button"
                    className={kitStyles.button}
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
                    className={kitStyles.button}
                    disabled={slide === clip.slides.length - 1}
                    onClick={() => setSlide((value) => value + 1)}
                  >
                    Next slide
                  </button>
                </div>
              </div>
            ) : null}
            <p>{clip.transcript_excerpt}</p>
            <p className={styles.note}>
              Placeholder · neutral narration of Dipak’s script. Listening does
              not complete your mission.
            </p>
          </div>
        </details>
      )}
      {attempt > 0 && !locked ? (
        <audio
          key={attempt}
          ref={player}
          src={clipSource(clip)}
          preload="metadata"
          aria-label="Placeholder coaching narration"
          onLoadedMetadata={() => {
            if (!player.current || !active.current) return;
            begin(player.current, clip.start_ms);
          }}
          onTimeUpdate={() => {
            const audio = player.current;
            if (!audio || !active.current) return;
            const at = Math.round(audio.currentTime * 1000);
            setPosition(Math.max(0, Math.min(length, at - clip.start_ms)));
            if (at >= stopAt) {
              audio.pause();
              active.current = false;
              setState(stopAt < clip.end_ms ? "limit" : "done");
            }
          }}
          onEnded={() => {
            active.current = false;
            setState(stopAt < clip.end_ms ? "limit" : "done");
          }}
          onError={() => {
            active.current = false;
            setState("failed");
          }}
        />
      ) : null}
    </article>
  );
}

/** One recommended clip first; any others stay secondary (spec 6.2, 6.3). */
export function CoachingMedia({ clips }: { clips?: CoachingClip[] }) {
  if (!clips?.length) return null;
  return (
    <div className={styles.clips}>
      {clips.map((clip, index) => (
        <ClipCard
          key={`${clip.topic_id}:${clip.revision}:${clip.review_id}`}
          clip={clip}
          recommended={index === 0}
        />
      ))}
    </div>
  );
}
