// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { createPracticeSoundPlayer } from "./practice-sounds";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
function fixture() {
  const sources: {
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    connect: ReturnType<typeof vi.fn>;
    buffer?: { duration: number };
    onended?: () => void;
  }[] = [];
  const context = {
    state: "running",
    currentTime: 0,
    destination: {},
    resume: vi.fn(async () => {}),
    close: vi.fn(async () => {}),
    decodeAudioData: vi.fn(async () => ({ duration: 0.2 })),
    createBufferSource: vi.fn(() => {
      const source = {
        start: vi.fn(),
        stop: vi.fn(),
        disconnect: vi.fn(),
        connect: vi.fn(),
      };
      sources.push(source);
      return source;
    }),
    createGain: vi.fn(() => ({
      gain: { setValueAtTime: vi.fn(), setTargetAtTime: vi.fn() },
      connect: vi.fn(),
      disconnect: vi.fn(),
    })),
  };
  const createContext = vi.fn(() => context as unknown as AudioContext);
  const fetcher = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input;
      void _init;
      return new Response(new Uint8Array([1, 2, 3]), {
        headers: { "content-type": "audio/wav" },
      });
    },
  );
  let time = 0;
  let visible = true;
  const player = createPracticeSoundPlayer({
    createContext,
    fetcher,
    visible: () => visible,
    now: () => time,
  });
  return {
    player,
    context,
    createContext,
    fetcher,
    sources,
    tick: () => (time += 100),
    hide: () => (visible = false),
  };
}
async function ready(f: ReturnType<typeof fixture>) {
  f.player.setEnabled(true);
  f.player.prepare();
  await vi.waitFor(() =>
    expect(f.context.decodeAudioData).toHaveBeenCalledTimes(3),
  );
}
it("creates no audio context or requests before an enabled explicit gesture", async () => {
  const f = fixture();
  f.player.prepare();
  f.player.play("reward", "old");
  expect(f.createContext).not.toHaveBeenCalled();
  expect(f.fetcher).not.toHaveBeenCalled();
  await ready(f);
  expect(f.sources).toHaveLength(0);
  expect(f.fetcher).toHaveBeenCalledTimes(3);
  expect(f.fetcher.mock.calls[0]).toEqual([
    "/audio/practice/select.wav",
    expect.objectContaining({
      mode: "same-origin",
      credentials: "omit",
      redirect: "error",
    }),
  ]);
  f.player.play("reward", "old");
  expect(f.sources).toHaveLength(0);
  f.player.dispose();
});
it("does not queue an unloaded cue; deduplicates confirmed receipts and throttles selection", async () => {
  const f = fixture();
  f.player.setEnabled(true);
  f.player.play("reward", "early");
  await ready(f);
  f.player.play("reward", "early");
  expect(f.sources).toHaveLength(0);
  expect(f.player.play("reward", "receipt-1")).toBe(true);
  f.player.play("reward", "receipt-1");
  expect(f.sources).toHaveLength(1);
  expect(f.player.play("select")).toBe(false);
  expect(f.player.play("confirm")).toBe(false);
  expect(f.sources).toHaveLength(1);
  expect(f.sources[0].stop).not.toHaveBeenCalled();
  f.sources[0].onended?.();
  f.player.play("select");
  f.player.play("select");
  expect(f.sources).toHaveLength(2);
  f.tick();
  f.player.play("select");
  expect(f.sources).toHaveLength(3);
  expect(f.sources[1].stop).toHaveBeenCalledOnce();
  f.player.dispose();
});
it("mute stops active audio; hidden, suspended and disposed contexts cannot play", async () => {
  const f = fixture();
  await ready(f);
  f.player.play("confirm", "response-1");
  f.player.setEnabled(false);
  expect(f.sources[0].stop).toHaveBeenCalledOnce();
  f.player.play("confirm", "response-2");
  expect(f.sources).toHaveLength(1);
  f.player.setEnabled(true);
  f.player.play("confirm", "response-2");
  expect(f.sources).toHaveLength(1);
  f.context.state = "suspended";
  f.player.prepare();
  expect(f.context.resume).toHaveBeenCalledOnce();
  f.player.play("select");
  expect(f.sources).toHaveLength(1);
  f.context.state = "running";
  f.hide();
  f.player.play("select");
  expect(f.sources).toHaveLength(1);
  f.player.dispose();
  f.player.prepare();
  expect(f.context.close).toHaveBeenCalledOnce();
});
it("abort on dispose suppresses a late decoder completion", async () => {
  const f = fixture();
  const resolvers: ((value: { duration: number }) => void)[] = [];
  f.context.decodeAudioData.mockImplementation(
    () =>
      new Promise((done) => {
        resolvers.push(done);
      }),
  );
  f.player.setEnabled(true);
  f.player.prepare();
  await vi.waitFor(() =>
    expect(f.context.decodeAudioData).toHaveBeenCalledTimes(3),
  );
  f.player.dispose();
  for (const resolve of resolvers) resolve({ duration: 0.2 });
  await Promise.resolve();
  expect(f.player.play("reward")).toBe(false);
  expect(f.sources).toHaveLength(0);
});
it.each(["text/html", "audio/mpeg"])(
  "rejects unexpected content type %s",
  async (contentType) => {
    const f = fixture();
    f.fetcher.mockImplementation(
      async () =>
        new Response("not wave", { headers: { "content-type": contentType } }),
    );
    f.player.setEnabled(true);
    f.player.prepare();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(f.context.decodeAudioData).not.toHaveBeenCalled();
    f.player.dispose();
  },
);
it("bounds sample bytes and decoded duration", async () => {
  const f = fixture();
  f.fetcher.mockImplementation(
    async () =>
      new Response(new Uint8Array(262145), {
        headers: { "content-type": "audio/wav" },
      }),
  );
  f.player.setEnabled(true);
  f.player.prepare();
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(f.context.decodeAudioData).not.toHaveBeenCalled();
  f.fetcher.mockImplementation(
    async () =>
      new Response(new Uint8Array([1]), {
        headers: { "content-type": "audio/wav" },
      }),
  );
  f.context.decodeAudioData.mockResolvedValue({ duration: 3 });
  f.player.prepare();
  await vi.waitFor(() =>
    expect(f.context.decodeAudioData).toHaveBeenCalledTimes(3),
  );
  expect(f.player.play("reward")).toBe(false);
  f.player.dispose();
});
it("unsupported audio is a no-op, never a practice failure", () => {
  const player = createPracticeSoundPlayer({
    createContext: () => {
      throw new Error("unsupported");
    },
  });
  player.setEnabled(true);
  expect(() => player.prepare()).not.toThrow();
  expect(player.play("select")).toBe(false);
  player.dispose();
});

it("applies bounded volume to new and already-playing cues without muting progress", async () => {
  const f = fixture();
  await ready(f);
  f.player.setVolume(0.5);
  f.player.play("confirm");
  const gain = f.context.createGain.mock.results[0].value.gain;
  expect(gain.setValueAtTime).toHaveBeenLastCalledWith(0.35, 0);
  f.player.setVolume(0);
  expect(gain.setTargetAtTime).toHaveBeenLastCalledWith(0, 0, 0.015);
  f.player.setVolume(20);
  expect(gain.setTargetAtTime).toHaveBeenLastCalledWith(0.7, 0, 0.015);
  f.player.dispose();
});

it("a labelled preview waits for its gesture-started load but does not record a reward", async () => {
  const f = fixture();
  f.player.setEnabled(true);
  expect(await f.player.preview("reward")).toBe(true);
  expect(f.sources).toHaveLength(1);
  expect(f.fetcher).toHaveBeenCalledTimes(3);
  // A real receipt is independent of preview playback and is still eligible once.
  expect(f.player.play("reward", "real-receipt")).toBe(true);
  expect(f.player.play("reward", "real-receipt")).toBeUndefined();
  f.player.dispose();
});

it("closing or muting during a preview load prevents delayed playback", async () => {
  const f = fixture();
  const decoded: ((value: { duration: number }) => void)[] = [];
  f.context.decodeAudioData.mockImplementation(
    () => new Promise((resolve) => decoded.push(resolve)),
  );
  f.player.setEnabled(true);
  const preview = f.player.preview("reward");
  await vi.waitFor(() => expect(decoded).toHaveLength(3));
  f.player.stop();
  decoded.forEach((resolve) => resolve({ duration: 0.4 }));
  expect(await preview).toBe(false);
  expect(f.sources).toHaveLength(0);
  f.player.dispose();
});

it("concurrent previews reuse one decode and only the latest preview can play", async () => {
  const f = fixture();
  f.player.setEnabled(true);
  const first = f.player.preview("confirm");
  const latest = f.player.preview("reward");
  expect(await first).toBe(false);
  expect(await latest).toBe(true);
  expect(f.sources).toHaveLength(1);
  expect(f.fetcher).toHaveBeenCalledTimes(3);
  f.player.dispose();
});

it("bounds a stalled audio resume and never plays its timed-out preview later", async () => {
  vi.useFakeTimers();
  const f = fixture();
  let resume!: () => void;
  f.context.state = "suspended";
  f.context.resume.mockImplementation(
    () => new Promise<void>((resolve) => (resume = resolve)),
  );
  f.player.setEnabled(true);
  const preview = f.player.preview("reward");
  await vi.advanceTimersByTimeAsync(0);
  expect(f.context.decodeAudioData).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(4000);
  expect(await preview).toBe(false);
  expect(f.sources).toHaveLength(0);

  f.context.state = "running";
  resume();
  await vi.advanceTimersByTimeAsync(0);
  expect(f.sources).toHaveLength(0);
  // Only a new explicit preview can play once audio is available.
  expect(await f.player.preview("reward")).toBe(true);
  expect(f.fetcher).toHaveBeenCalledTimes(3);
  f.player.dispose();
});

it("bounds stalled decoding, permits a fresh retry and ignores late stale buffers", async () => {
  vi.useFakeTimers();
  const f = fixture();
  const finishOld: ((buffer: { duration: number }) => void)[] = [];
  f.context.decodeAudioData.mockImplementation(
    () => new Promise((resolve) => finishOld.push(resolve)),
  );
  f.player.setEnabled(true);
  const preview = f.player.preview("reward");
  await vi.advanceTimersByTimeAsync(0);
  expect(finishOld).toHaveLength(3);
  await vi.advanceTimersByTimeAsync(4000);
  expect(await preview).toBe(false);
  expect(f.sources).toHaveLength(0);
  for (const [, init] of f.fetcher.mock.calls)
    expect(init?.signal?.aborted).toBe(true);

  f.context.decodeAudioData.mockResolvedValue({ duration: 0.2 });
  expect(await f.player.preview("reward")).toBe(true);
  expect(f.fetcher).toHaveBeenCalledTimes(6);
  finishOld.forEach((finish) => finish({ duration: 0.9 }));
  await vi.advanceTimersByTimeAsync(0);
  expect(f.sources).toHaveLength(1);
  expect(f.player.play("reward", "fresh-server-receipt")).toBe(true);
  expect(f.sources[1].buffer?.duration).toBe(0.2);
  f.player.dispose();
});

it.each(["stop", "mute", "dispose"] as const)(
  "%s promptly cancels a preview even when audio resume never settles",
  async (action) => {
    vi.useFakeTimers();
    const f = fixture();
    f.context.state = "suspended";
    f.context.resume.mockImplementation(() => new Promise<void>(() => {}));
    f.player.setEnabled(true);
    const preview = f.player.preview("confirm");
    await vi.advanceTimersByTimeAsync(0);
    if (action === "mute") f.player.setEnabled(false);
    else f.player[action]();
    expect(await preview).toBe(false);
    expect(f.sources).toHaveLength(0);
    f.player.dispose();
  },
);
