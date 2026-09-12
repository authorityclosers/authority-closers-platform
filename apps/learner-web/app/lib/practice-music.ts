/** Optional presentation-only music. It never carries progress or reward state. */
export const PRACTICE_MUSIC_KEY = "ac-practice-music";
export const PRACTICE_MUSIC_EVENT = "ac-practice-music-change";
export const PRACTICE_MUSIC_ASSET = "/audio/practice/overworld-loop.mp3";
export const PRACTICE_MUSIC_VOLUME = 0.16;

let sessionChoice: boolean | undefined;

export function readPracticeMusic(): boolean {
  if (typeof window === "undefined") return false;
  if (sessionChoice !== undefined) return sessionChoice;
  try {
    return window.localStorage.getItem(PRACTICE_MUSIC_KEY) === "on";
  } catch {
    return false;
  }
}

export function savePracticeMusic(enabled: boolean) {
  try {
    window.localStorage.setItem(PRACTICE_MUSIC_KEY, enabled ? "on" : "off");
    sessionChoice = undefined;
  } catch {
    sessionChoice = enabled;
  }
  window.dispatchEvent(new Event(PRACTICE_MUSIC_EVENT));
}

export function subscribePracticeMusic(changed: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key === PRACTICE_MUSIC_KEY || event.key === null) changed();
  };
  window.addEventListener(PRACTICE_MUSIC_EVENT, changed);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(PRACTICE_MUSIC_EVENT, changed);
    window.removeEventListener("storage", storage);
  };
}

type LifecycleTarget = {
  addEventListener(type: string, listener: EventListener): void;
  removeEventListener(type: string, listener: EventListener): void;
};

/**
 * A bounded, gesture-started loop. Hidden/page-exited audio stops and never
 * resumes itself; the learner must tap play again after returning.
 */
export function createPracticeMusicPlayer({
  createAudio = () => new Audio(),
  visible = () =>
    typeof document !== "undefined" && document.visibilityState === "visible",
  lifecycle = typeof document === "undefined"
    ? undefined
    : (document as unknown as LifecycleTarget),
  startTimeoutMs = 4000,
  onPlayingChange = () => {},
}: {
  createAudio?: () => HTMLAudioElement;
  visible?: () => boolean;
  lifecycle?: LifecycleTarget;
  startTimeoutMs?: number;
  onPlayingChange?: (playing: boolean) => void;
} = {}) {
  let audio: HTMLAudioElement | undefined;
  let disposed = false;
  let generation = 0;
  let playing = false;
  let pending: Promise<boolean> | undefined;

  const setPlaying = (value: boolean) => {
    if (playing === value) return;
    playing = value;
    onPlayingChange(value);
  };
  const stop = () => {
    generation += 1;
    pending = undefined;
    if (audio) {
      audio.pause();
      try {
        audio.currentTime = 0;
      } catch {
        /* Reset is optional on media implementations that reject seeking. */
      }
    }
    setPlaying(false);
  };
  const stopWhenHidden: EventListener = () => {
    if (!visible()) stop();
  };
  const stopForPageExit: EventListener = () => stop();
  lifecycle?.addEventListener("visibilitychange", stopWhenHidden);
  lifecycle?.addEventListener("pagehide", stopForPageExit);

  const player = {
    /** Must be called directly from a user gesture; construction never loads audio. */
    start(): Promise<boolean> {
      if (disposed || !visible()) return Promise.resolve(false);
      if (playing) return Promise.resolve(true);
      if (pending) return pending;
      const requestedGeneration = ++generation;
      let play: Promise<void>;
      try {
        audio ??= createAudio();
        audio.src = PRACTICE_MUSIC_ASSET;
        audio.preload = "none";
        audio.loop = true;
        audio.volume = PRACTICE_MUSIC_VOLUME;
        play = audio.play();
      } catch {
        stop();
        return Promise.resolve(false);
      }
      const request = new Promise<boolean>((resolve) => {
        const timer = setTimeout(() => resolve(false), startTimeoutMs);
        void Promise.resolve(play).then(
          () => {
            clearTimeout(timer);
            resolve(true);
          },
          () => {
            clearTimeout(timer);
            resolve(false);
          },
        );
      }).then((started) => {
        if (
          !started ||
          disposed ||
          requestedGeneration !== generation ||
          !visible()
        ) {
          if (requestedGeneration === generation) stop();
          return false;
        }
        setPlaying(true);
        return true;
      });
      const settled = request.finally(() => {
        if (pending === settled) pending = undefined;
      });
      pending = settled;
      return settled;
    },
    stop,
    isPlaying: () => playing,
    dispose() {
      if (disposed) return;
      disposed = true;
      lifecycle?.removeEventListener("visibilitychange", stopWhenHidden);
      lifecycle?.removeEventListener("pagehide", stopForPageExit);
      stop();
      if (audio) audio.removeAttribute("src");
      audio = undefined;
    },
  };
  return player;
}

export type PracticeMusicPlayer = ReturnType<typeof createPracticeMusicPlayer>;
