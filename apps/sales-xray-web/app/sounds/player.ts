/**
 * Plays the library's sounds (brand kit sound/, round-2 board 4, 20 Nov 2026),
 * their MP3s (sounds.ts soundFiles). One sound at a time: a new
 * one stops the last. Quiet where the browser refuses sound before a first tap,
 * and never an error the person sees.
 */
import type { SxEventId } from "./library";
import { playsFor, refreshSoundsLater } from "./prefs";
import { loops, soundFiles, type SoundChoice } from "./sounds";
import { soundPlayed } from "./telemetry";

type Playing = { audio: HTMLAudioElement; choice: SoundChoice };

let playing: Playing | null = null;
/** Stops whatever plays now. */
export function stopSound(): void {
  const was = playing;
  playing = null;
  if (!was) return;
  try {
    was.audio.pause();
    was.audio.currentTime = 0;
  } catch {
    // Already gone.
  }
}

/**
 * Plays one library sound; "none" and "system" play nothing here (on a
 * computer there is no phone sound to hand over to). The ringtone loops only
 * when asked (an incoming call); a preview plays it once. `ended` runs when
 * it stops by itself or is stopped by the next sound.
 */
export function playSound(
  choice: SoundChoice,
  options: { loop?: boolean; ended?: () => void } = {},
): boolean {
  const files = soundFiles(choice);
  stopSound();
  if (!files || typeof window === "undefined" || typeof Audio !== "function")
    return false;
  try {
    const audio = new Audio();
    audio.preload = "auto";
    audio.loop = options.loop === true && loops(choice);
    const mine: Playing = { audio, choice };
    let over = false;
    // Once: an end fires "pause" and "ended" both.
    const done = () => {
      if (over) return;
      over = true;
      if (playing === mine) playing = null;
      options.ended?.();
    };
    audio.addEventListener("ended", done);
    audio.addEventListener("pause", done);
    audio.addEventListener("error", done);
    audio.src = files.mp3;
    playing = mine;
    const started = audio.play();
    // Refused before a first tap on the page: quiet, no error.
    if (started && typeof started.catch === "function") started.catch(done);
    return true;
  } catch {
    return false;
  }
}

/** Whether this sound plays now (a row's ▶ turns into ❚❚). */
export function isPlaying(choice: SoundChoice): boolean {
  return playing?.choice === choice;
}

let lastEventAt = 0;
/** Two moments at once ring once: the bell's banner shows the rest. */
const EVENT_GAP_MS = 1_500;

/** The picked sound for this moment, as the bell hears of it. */
export function playEvent(id: SxEventId): SoundChoice | null {
  const now = Date.now();
  if (now - lastEventAt < EVENT_GAP_MS) return null;
  const choice = playsFor(id);
  if (!soundFiles(choice)) return null;
  if (!playSound(choice)) return null;
  lastEventAt = now;
  soundPlayed(id, choice);
  refreshSoundsLater();
  return choice;
}

/** Tests only. */
export function resetPlayer() {
  stopSound();
  lastEventAt = 0;
}
