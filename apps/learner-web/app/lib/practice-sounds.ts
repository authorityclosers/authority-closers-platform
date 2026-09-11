/** Optional presentation-only audio. No answers, identity or reward state are stored here. */
export type PracticeSound = "select" | "confirm" | "retry" | "reward";
export const PRACTICE_SOUND_KEY = "ac-practice-sounds";
export const PRACTICE_SOUND_EVENT = "ac-practice-sounds-change";
export const PRACTICE_VOLUME_KEY = "ac-practice-volume";
export const DEFAULT_PRACTICE_VOLUME = 0.65;
export const PRACTICE_SOUND_ASSETS: Record<PracticeSound, string> = {
  select: "/audio/practice/select.wav",
  confirm: "/audio/practice/confirm.wav",
  retry: "/audio/practice/retry.wav",
  reward: "/audio/practice/reward.wav",
};
let sessionChoice: boolean | undefined;
let sessionVolume: number | undefined;
const boundedVolume = (value: number) =>
  Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : DEFAULT_PRACTICE_VOLUME;

/** Web Audio promises do not themselves accept AbortSignal. Ignore late results. */
async function whileAudioActive<T>(
  work: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  let abort: (() => void) | undefined;
  const cancelled = new Promise<never>((_, reject) => {
    abort = () =>
      reject(new DOMException("Audio preparation ended", "AbortError"));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  });
  try {
    return await Promise.race([work, cancelled]);
  } finally {
    if (abort) signal.removeEventListener("abort", abort);
  }
}

export function readPracticeVolume(): number {
  if (sessionVolume !== undefined) return sessionVolume;
  if (typeof window === "undefined") return DEFAULT_PRACTICE_VOLUME;
  try {
    const stored = window.localStorage.getItem(PRACTICE_VOLUME_KEY);
    return stored === null || stored.trim() === ""
      ? DEFAULT_PRACTICE_VOLUME
      : boundedVolume(Number(stored));
  } catch {
    return DEFAULT_PRACTICE_VOLUME;
  }
}
export function savePracticeVolume(value: number) {
  const volume = boundedVolume(value);
  try {
    window.localStorage.setItem(PRACTICE_VOLUME_KEY, String(volume));
    sessionVolume = undefined;
  } catch {
    sessionVolume = volume;
  }
  window.dispatchEvent(new Event(PRACTICE_SOUND_EVENT));
}
export function readPracticeSounds(): boolean {
  if (typeof window === "undefined") return false;
  if (sessionChoice !== undefined) return sessionChoice;
  try {
    return window.localStorage.getItem(PRACTICE_SOUND_KEY) === "on";
  } catch {
    return false;
  }
}
export function savePracticeSounds(enabled: boolean) {
  try {
    window.localStorage.setItem(PRACTICE_SOUND_KEY, enabled ? "on" : "off");
    sessionChoice = undefined;
  } catch {
    sessionChoice = enabled;
  }
  window.dispatchEvent(new Event(PRACTICE_SOUND_EVENT));
}
export function subscribePracticeSounds(changed: () => void) {
  const storage = (event: StorageEvent) => {
    if (
      event.key === PRACTICE_SOUND_KEY ||
      event.key === PRACTICE_VOLUME_KEY ||
      event.key === null
    )
      changed();
  };
  window.addEventListener(PRACTICE_SOUND_EVENT, changed);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(PRACTICE_SOUND_EVENT, changed);
    window.removeEventListener("storage", storage);
  };
}

export function createPracticeSoundPlayer({
  createContext = () => new AudioContext(),
  fetcher = globalThis.fetch,
  visible = () =>
    typeof document !== "undefined" && document.visibilityState === "visible",
  now = () => performance.now(),
}: {
  createContext?: () => AudioContext;
  fetcher?: typeof fetch;
  visible?: () => boolean;
  now?: () => number;
} = {}) {
  let context: AudioContext | undefined;
  let enabled = false;
  let disposed = false;
  let generation = 0;
  let lastClick = -Infinity;
  let volume = DEFAULT_PRACTICE_VOLUME;
  const buffers = new Map<PracticeSound, AudioBuffer>();
  const pending = new Map<PracticeSound, Promise<void>>();
  const requests = new Set<AbortController>();
  const preparations = new Set<AbortController>();
  const sources = new Map<
    AudioBufferSourceNode,
    { kind: PracticeSound; gain: GainNode }
  >();
  const seen = new Set<string>();
  const stop = () => {
    generation += 1;
    for (const preparation of preparations) preparation.abort();
    for (const source of sources.keys()) {
      try {
        source.stop();
      } catch {
        /* Already ended. */
      }
    }
    sources.clear();
  };
  const loadSample = async (
    kind: PracticeSound,
    audioContext: AudioContext,
  ) => {
    const controller = new AbortController();
    requests.add(controller);
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await whileAudioActive(
        fetcher(PRACTICE_SOUND_ASSETS[kind], {
          mode: "same-origin",
          credentials: "omit",
          redirect: "error",
          signal: controller.signal,
        }),
        controller.signal,
      );
      if (
        !response.ok ||
        !/^(audio\/(wav|wave|x-wav)|application\/octet-stream)(;|$)/i.test(
          response.headers.get("content-type") ?? "",
        )
      )
        return;
      const size = Number(response.headers.get("content-length"));
      if (size > 262144) return;
      const reader = response.body?.getReader();
      if (!reader) return;
      const chunks: Uint8Array[] = [];
      let length = 0;
      try {
        while (true) {
          const next = await whileAudioActive(reader.read(), controller.signal);
          if (next.done) break;
          length += next.value.length;
          if (length > 262144) {
            await reader.cancel();
            return;
          }
          chunks.push(next.value);
        }
      } finally {
        reader.releaseLock();
      }
      if (disposed || controller.signal.aborted) return;
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      const buffer = await whileAudioActive(
        audioContext.decodeAudioData(bytes.buffer),
        controller.signal,
      );
      if (!disposed && !controller.signal.aborted && buffer.duration <= 2)
        buffers.set(kind, buffer);
    } catch {
      /* Optional sound must never block practice or delay an action. */
    } finally {
      clearTimeout(timer);
      requests.delete(controller);
    }
  };
  const load = (kind: PracticeSound, audioContext: AudioContext) => {
    if (buffers.has(kind)) return Promise.resolve();
    const current = pending.get(kind);
    if (current) return current;
    const request = loadSample(kind, audioContext).finally(() =>
      pending.delete(kind),
    );
    pending.set(kind, request);
    return request;
  };
  const prepareAudio = async (): Promise<boolean> => {
    if (disposed || !enabled) return false;
    const controller = new AbortController();
    preparations.add(controller);
    // This deadline includes resume and decoding, not only network activity.
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
      context ??= createContext();
      const resumed =
        context.state === "suspended" ? context.resume() : Promise.resolve();
      await whileAudioActive(
        Promise.all([
          resumed,
          ...Object.keys(PRACTICE_SOUND_ASSETS).map((kind) =>
            load(kind as PracticeSound, context!),
          ),
        ]),
        controller.signal,
      );
      return !disposed && enabled && context.state === "running";
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
      preparations.delete(controller);
    }
  };
  const player = {
    setEnabled(value: boolean) {
      if (enabled === value) return;
      enabled = value;
      generation += 1;
      if (!value) stop();
    },
    setVolume(value: number) {
      volume = boundedVolume(value);
      if (context) {
        for (const { kind, gain } of sources.values()) {
          gain.gain.setTargetAtTime(
            volume * (kind === "select" ? 0.45 : 0.7),
            context.currentTime,
            0.015,
          );
        }
      }
    },
    /** Call synchronously from an explicit user gesture; never autoplay on mount. */
    async prepare() {
      await prepareAudio();
    },
    play(kind: PracticeSound, eventId?: string) {
      if (eventId) {
        if (seen.has(eventId)) return;
        seen.add(eventId);
        // This player belongs to one bounded attempt, not a global event log.
        if (seen.size > 512) seen.delete(seen.values().next().value!);
      }
      if (disposed || !enabled || !visible() || context?.state !== "running")
        return false;
      const buffer = buffers.get(kind);
      if (!buffer) return false; // Never queue a late click or old reward sound.
      // Let acknowledged feedback finish. A low-priority click must not chop
      // off a musical reward; no sound queues are created by rapid tapping.
      const priority = { select: 0, retry: 1, confirm: 1, reward: 2 };
      if (
        [...sources.values()].some(
          (active) => priority[active.kind] > priority[kind],
        )
      )
        return false;
      if (kind === "select" && now() - lastClick < 70) return false;
      if (kind === "select") lastClick = now();
      try {
        stop();
        const source = context.createBufferSource();
        const gain = context.createGain();
        source.buffer = buffer;
        gain.gain.setValueAtTime(
          volume * (kind === "select" ? 0.45 : 0.7),
          context.currentTime,
        );
        source.connect(gain);
        gain.connect(context.destination);
        const startedGeneration = generation;
        source.onended = () => {
          sources.delete(source);
          source.disconnect();
          gain.disconnect();
        };
        if (!enabled || startedGeneration !== generation) return false;
        sources.set(source, { kind, gain });
        source.start();
        return true;
      } catch {
        return false;
      }
    },
    /** Only a labelled preview button may wait for audio; real feedback never queues. */
    async preview(kind: PracticeSound) {
      stop();
      const requestedGeneration = generation;
      const ready = await prepareAudio();
      if (!ready || requestedGeneration !== generation || disposed || !enabled)
        return false;
      return player.play(kind);
    },
    stop,
    dispose() {
      disposed = true;
      enabled = false;
      generation += 1;
      stop();
      for (const request of requests) request.abort();
      buffers.clear();
      if (context && context.state !== "closed")
        void context.close().catch(() => {});
    },
  };
  return player;
}
export type PracticeSoundPlayer = ReturnType<typeof createPracticeSoundPlayer>;
