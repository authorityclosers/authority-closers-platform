"use client";

import { Lock, Pause, Play, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Badge, kitStyles } from "../ui/kit";
import {
  clipSource,
  FULL_COACHING_HREF,
  type CoachingClip,
} from "./media-contract";
import { MEDIA } from "./coaching-copy";
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

/**
 * Where the learner stopped a reviewed clip, on this device only (spec 3.4,
 * "resume playback if learner returns"). A position, never progress.
 */
/** Stable identity of one reviewed clip (also the "Hear Dipak's take" target). */
export const clipKey = (clip: CoachingClip) =>
  `${clip.topic_id}:${clip.revision}:${clip.review_id}`;

/** Asks the page's card for this clip to come into view and play. */
export function requestClip(clip: CoachingClip) {
  window.dispatchEvent(
    new CustomEvent("sx-coaching-clip-request", { detail: clipKey(clip) }),
  );
}

const resumeKey = (clip: CoachingClip) =>
  `sx-coaching-clip:${clip.topic_id}:${clip.revision}:${clip.review_id}`;
function readResume(key: string): number {
  try {
    const saved = Number(window.localStorage.getItem(key));
    return Number.isFinite(saved) && saved > 0 ? Math.floor(saved) : 0;
  } catch {
    return 0;
  }
}
const noSubscription = () => () => {};
function writeResume(key: string, offset: number | null) {
  try {
    if (offset === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, String(offset));
  } catch {
    // Storage may be unavailable (private mode); resuming is optional.
  }
}

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
          >
            {offer.academy.label}
          </a>
        ) : null}
      </div>
    </div>
  );
}

function ClipCard({
  clip,
  recommended,
  headingLevel = 3,
}: {
  clip: CoachingClip;
  recommended: boolean;
  headingLevel?: 3 | 4;
}) {
  const Title = headingLevel === 4 ? "h4" : "h3";
  const identity = useId();
  const card = useRef<HTMLElement>(null);
  const player = useRef<HTMLAudioElement>(null);
  const active = useRef(false);
  const [playState, setState] = useState<ClipState>("idle");
  const [attempt, setAttempt] = useState(0);
  const [slide, setSlide] = useState(0);
  const [playPosition, setPosition] = useState(0);
  const resumeFrom = useRef(0);
  const saved = useRef(0);
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
  // A stored position shows after hydration (the server renders 0), and only
  // inside the window the server allows; before the first play it reads as
  // a paused clip.
  const key = resumeKey(clip);
  const stored = useSyncExternalStore(
    noSubscription,
    () => (locked ? 0 : readResume(key)),
    () => 0,
  );
  const fresh =
    attempt === 0 &&
    playState === "idle" &&
    stored > 0 &&
    clip.start_ms + stored < stopAt - 1000;
  const state: ClipState = fresh ? "paused" : playState;
  const position = fresh ? stored : playPosition;
  const remember = (offset: number | null, force = false) => {
    if (force || offset === null || Math.abs(offset - saved.current) >= 2000) {
      saved.current = offset ?? 0;
      writeResume(key, offset);
    }
  };
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
      remember(position, true);
      setState("paused");
      return;
    }
    window.dispatchEvent(
      new CustomEvent("sx-coaching-play", { detail: identity }),
    );
    active.current = true;
    const resume =
      state === "paused" && position > 0 && clip.start_ms + position < stopAt;
    if (attempt === 0 || state === "failed") {
      resumeFrom.current = resume ? position : 0;
      setState("loading");
      setPosition(resume ? position : 0);
      setAttempt((value) => value + 1);
      return;
    }
    const audio = player.current;
    if (!audio) return;
    setState("loading");
    if (!resume) setPosition(0);
    begin(audio, resume ? clip.start_ms + position : clip.start_ms);
  };
  // "Hear Dipak's take" in pillar 1: bring this card into view and play it.
  const latestToggle = useRef(toggle);
  useEffect(() => {
    latestToggle.current = toggle;
  });
  const playing = state === "playing";
  useEffect(() => {
    const onRequest = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== clipKey(clip)) return;
      card.current?.scrollIntoView({ block: "center", behavior: "smooth" });
      if (!playing) latestToggle.current();
    };
    window.addEventListener("sx-coaching-clip-request", onRequest);
    return () =>
      window.removeEventListener("sx-coaching-clip-request", onRequest);
  }, [clip, playing]);
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
      ref={card}
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
            {recommended ? MEDIA.recommended : MEDIA.other}
          </span>
          <Title>{clip.title}</Title>
          <span className={styles.note}>
            {MEDIA.byline} · {MEDIA.kind(clip.kind === "video")} · {MEDIA.voice}{" "}
            · {timeLabel(length)}
          </span>
        </div>
        {clip.access === "preview" && preview ? (
          <Badge tone="accent">
            {MEDIA.freePreview} · {timeLabel(preview)}
          </Badge>
        ) : locked ? (
          <Badge>{MEDIA.locked}</Badge>
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
      {locked ? (
        <p className={styles.note}>{clip.reason}</p>
      ) : (
        <>
          <p>
            <span className={styles.label}>{MEDIA.why}</span>
            {clip.reason}
          </p>
          <ul className={styles.takeaways}>
            {clip.takeaways.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
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
          <summary>{MEDIA.takeaways}</summary>
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
            <p className={styles.note}>{MEDIA.narrationNote}</p>
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
            begin(player.current, clip.start_ms + resumeFrom.current);
          }}
          onTimeUpdate={() => {
            const audio = player.current;
            if (!audio || !active.current) return;
            const at = Math.round(audio.currentTime * 1000);
            const offset = Math.max(0, Math.min(length, at - clip.start_ms));
            setPosition(offset);
            if (at >= stopAt) {
              audio.pause();
              active.current = false;
              remember(null);
              setState(stopAt < clip.end_ms ? "limit" : "done");
            } else remember(offset);
          }}
          onEnded={() => {
            active.current = false;
            remember(null);
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
export function CoachingMedia({
  clips,
  headingLevel = 3,
}: {
  clips?: CoachingClip[];
  /** 4 inside the Report, where the pillars are h3. */
  headingLevel?: 3 | 4;
}) {
  if (!clips?.length) return null;
  return (
    <div className={styles.clips}>
      {clips.map((clip, index) => (
        <ClipCard
          key={clipKey(clip)}
          clip={clip}
          recommended={index === 0}
          headingLevel={headingLevel}
        />
      ))}
    </div>
  );
}
