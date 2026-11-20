"use client";

/**
 * A lesson's video, where the studio has made one (owner's brand order, 19 Nov 2026: the Mac studio's lesson
 * videos, light theme, inside Ask Dipak). Each opens and closes on the Speech D intro and outro idents, which
 * are in the video itself, and Aman and Rohit carry its hook and payoff. It teaches the answer, so the lesson
 * shows it only once his answer is open (Dipak's report 228: the question first).
 *
 * The player: the poster frame first; a tap plays it with sound (never autoplay with sound); the phone's own
 * controls after that. Captions show when a lesson has a caption file; none has one yet, and the videos carry
 * their Hindi words on screen. Nothing loads before the tap but the poster.
 *
 * Only an approved video shows (owner, 19 Nov 2026 23:36 IST: "the videos are not approved for Ask Dipak").
 * The server's switch says which (lesson-videos.ts): while it is off, or the lesson has no approved video,
 * this draws nothing at all. No video file ships with the app.
 */
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import styles from "./lesson-video.module.css";
import { useLessonVideoFile } from "./lesson-videos";

export type { LessonVideoFile } from "./lesson-videos";

export const VIDEO_COPY = {
  title: "The lesson in a minute",
  note: "AI voice · Hindi on screen",
  play: "Play the lesson video",
} as const;

export const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function LessonVideo({ id }: { id: string }) {
  const file = useLessonVideoFile(id);
  const [playing, setPlaying] = useState(false);
  const video = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    // The tap that asked for it lets it start with sound.
    if (!playing || !video.current) return;
    try {
      const started = video.current.play();
      if (started && typeof started.catch === "function")
        started.catch(() => undefined);
    } catch {
      // A browser without media playback keeps the controls to start it.
    }
  }, [playing]);
  if (!file) return null;
  return (
    <figure className={styles.video} data-lesson-video={id}>
      <div className={styles.frame}>
        {playing ? (
          <video
            ref={video}
            className={styles.media}
            src={file.src}
            poster={file.poster}
            controls
            playsInline
            preload="auto"
            controlsList="nodownload"
            disablePictureInPicture
          >
            {file.captions ? (
              <track
                kind="captions"
                src={file.captions.src}
                srcLang={file.captions.lang}
                label={file.captions.label}
                default
              />
            ) : null}
          </video>
        ) : (
          <button
            type="button"
            className={styles.start}
            aria-label={`${VIDEO_COPY.play}, ${clock(file.seconds)}`}
            onClick={() => setPlaying(true)}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- the video's own poster frame */}
            <img
              className={styles.media}
              src={file.poster}
              alt=""
              loading="lazy"
              decoding="async"
            />
            <span className={styles.play} aria-hidden="true">
              <Play size={26} strokeWidth={2.2} />
            </span>
            <span className={styles.time} aria-hidden="true">
              {clock(file.seconds)}
            </span>
          </button>
        )}
      </div>
      <figcaption className={styles.caption}>
        <strong>{VIDEO_COPY.title}</strong>
        <span>{VIDEO_COPY.note}</span>
      </figcaption>
    </figure>
  );
}
