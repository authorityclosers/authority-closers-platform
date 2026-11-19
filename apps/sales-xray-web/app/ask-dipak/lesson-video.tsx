"use client";

/**
 * A lesson's video, where the studio has made one (owner's brand order, 19 Nov 2026: the Mac studio's lesson
 * videos, light theme, inside Ask Dipak). Each opens and closes on the Speech D intro and outro idents, which
 * are in the video itself, and Aman and Rohit carry its hook and payoff. It teaches the answer, so the lesson
 * shows it only once his answer is open (Dipak's report 228: the question first).
 *
 * The player: the poster frame first; a tap plays it with sound (never autoplay with sound); the phone's own
 * controls after that. Captions show when a lesson has a caption file; none has one yet, and the videos carry
 * their Hindi words on screen. Files are encoded for phones (540 x 960, about 1.1 to 1.4 MB each) and served
 * from the app's static media path; nothing loads before the tap but the poster.
 */
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import styles from "./lesson-video.module.css";

const BASE = "/media/ask-dipak/lessons";

export type LessonVideoFile = {
  src: string;
  poster: string;
  /** Whole seconds, for the time on the poster. */
  seconds: number;
  captions?: { src: string; lang: string; label: string };
};

export const LESSON_VIDEOS: Readonly<Record<string, LessonVideoFile>> = {
  // "Lesson 01 - PB03 with characters - Light" (Mac studio, 19 Nov 2026).
  PB03: {
    src: `${BASE}/pb03-lesson.mp4`,
    poster: `${BASE}/pb03-lesson-poster.jpg`,
    seconds: 61,
  },
  // "Lesson 02 - sochna-hai - Light" (मुझे सोचना है; Mac studio, 19 Nov 2026).
  OB03: {
    src: `${BASE}/ob03-lesson.mp4`,
    poster: `${BASE}/ob03-lesson-poster.jpg`,
    seconds: 55,
  },
};

export const VIDEO_COPY = {
  title: "The lesson in a minute",
  note: "AI voice · Hindi on screen",
  play: "Play the lesson video",
} as const;

export const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function LessonVideo({ id }: { id: string }) {
  const file = LESSON_VIDEOS[id];
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
