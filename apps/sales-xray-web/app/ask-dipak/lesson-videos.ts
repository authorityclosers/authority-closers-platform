/**
 * Ask Dipak's approved lesson videos, as the server's switch allows (owner, 19 Nov 2026
 * 23:36 IST: "the videos are not approved for Ask Dipak, so make sure they won't go live on
 * the app in the next update").
 *
 * GET /v1/sales-xray/ask-dipak/videos
 *     {videos: {<lesson id>: {src, poster, seconds}}}: empty while the switch is off
 *     (ask_dipak/videos.py; scripts/data-changes/admin.py ask-dipak videos on|off,
 *     add-video, remove-video). No file ships with the app.
 *
 * Asked once per visit and never kept on the phone, so switching off takes effect at the next
 * visit. No answer, a failed one or one not understood: no video.
 */
import { useEffect, useState } from "react";

export const VIDEOS_PATH = "/v1/sales-xray/ask-dipak/videos";

export type LessonVideoFile = {
  src: string;
  poster: string;
  /** Whole seconds, for the time on the poster. */
  seconds: number;
  captions?: { src: string; lang: string; label: string };
};

type Videos = Readonly<Record<string, LessonVideoFile>>;

const NONE: Videos = Object.freeze({});
// A same-origin path or an https address, as the server allows.
const URL_OK = /^(\/(?!\/)[\w.~/-]+|https:\/\/[\w.-]+(\/[\w.~%/-]*)?)$/;

const address = (value: unknown, ends: RegExp): string | null =>
  typeof value === "string" &&
  URL_OK.test(value) &&
  !value.includes("..") &&
  ends.test(value.toLowerCase())
    ? value
    : null;

/** The server's answer in the app's shape; anything unreadable is left out. */
export function fromServed(raw: unknown): Videos {
  if (typeof raw !== "object" || raw === null) return NONE;
  const videos = (raw as { videos?: unknown }).videos;
  if (typeof videos !== "object" || videos === null) return NONE;
  const out: Record<string, LessonVideoFile> = {};
  for (const [id, value] of Object.entries(videos)) {
    if (typeof value !== "object" || value === null) continue;
    const item = value as Record<string, unknown>;
    const src = address(item.src, /\.mp4$/);
    const poster = address(item.poster, /\.(jpe?g|png|webp)$/);
    const seconds = item.seconds;
    if (
      !src ||
      !poster ||
      typeof seconds !== "number" ||
      !Number.isInteger(seconds) ||
      seconds < 1
    )
      continue;
    out[id] = { src, poster, seconds };
  }
  return out;
}

let asked: Promise<Videos> | null = null;

/** The approved videos, asked of the server once per visit. */
export function loadVideos(): Promise<Videos> {
  if (!asked) {
    asked = (async () => {
      try {
        const response = await fetch(VIDEOS_PATH, {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: { accept: "application/json" },
        });
        return response.ok ? fromServed(await response.json()) : NONE;
      } catch {
        return NONE;
      }
    })();
  }
  return asked;
}

/** Forget this visit's answer (tests). */
export function forgetVideos() {
  asked = null;
}

/** A lesson's approved video, or null: while asking, when off, or when it has none. */
export function useLessonVideoFile(id: string): LessonVideoFile | null {
  const [videos, setVideos] = useState<Videos | null>(null);
  useEffect(() => {
    let live = true;
    void loadVideos().then((found) => {
      if (live) setVideos(found);
    });
    return () => {
      live = false;
    };
  }, []);
  return videos?.[id] ?? null;
}
