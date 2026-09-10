// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  attachAdaptiveVideo,
  authorizedHlsRequestPredicate,
} from "./adaptive-video";

const loader = vi.hoisted(() => ({
  create: vi.fn(),
  implementation: class AuthorizedLoader {},
}));
vi.mock("./authorized-hls-loader", () => ({
  createAuthorizedHlsLoader: loader.create,
}));

const origin = "https://learn.authorityclosers.test";
const now = Date.parse("2026-09-08T10:00:00Z");
const tenant = "11111111-1111-4111-8111-111111111111";
const asset = "22222222-2222-4222-8222-222222222222";
const version = "33333333-3333-4333-8333-333333333333";
const prefix = `tenants/${tenant}/media/video/${asset}/${version}/original/renditions`;
const masterKey = `${prefix}/hls/master.m3u8`;
const claims = {
  typ: "AC-MEDIA",
  token_type: "playback",
  tenant_id: tenant,
  person_id: "44444444-4444-4444-8444-444444444444",
  session_id: "55555555-5555-4555-8555-555555555555",
  activity_id: "66666666-6666-4666-8666-666666666666",
  activity_version: "activity-v1",
  asset_id: asset,
  version_id: version,
  binding_id: "77777777-7777-4777-8777-777777777777",
  enrollment_id: "88888888-8888-4888-8888-888888888888",
  delivery_grant_id: "99999999-9999-4999-8999-999999999999",
  iat: now / 1000 - 1,
  exp: now / 1000 + 299,
  supports_range: false,
};

// Deliberately synthetic signed-shaped data, not a credential or signature proof.
function mediaUrl(
  key = masterKey,
  changes: Record<string, unknown> = {},
  selectedOrigin = origin,
) {
  const body = Buffer.from(
    JSON.stringify({ ...claims, key, ...changes }),
  ).toString("base64url");
  return `${selectedOrigin}/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${body}.${"A".repeat(43)}`;
}

const events = {
  MANIFEST_PARSED: "manifestParsed",
  LEVEL_SWITCHED: "levelSwitched",
  ERROR: "hlsError",
} as const;
type Listener = (...args: unknown[]) => void;
class FakeHls {
  static isSupported = vi.fn(() => true);
  static instances: FakeHls[] = [];
  readonly listeners = new Map<string, Listener>();
  levels = [{ height: 360 }, { height: 1080 }, { height: 2160 }];
  currentLevel = -1;
  attachMedia = vi.fn();
  loadSource = vi.fn();
  destroy = vi.fn();
  on = vi.fn((name: string, callback: Listener) => {
    this.listeners.set(name, callback);
  });
  constructor(readonly config: Record<string, unknown>) {
    FakeHls.instances.push(this);
  }
  emit(name: string, payload: unknown = {}) {
    this.listeners.get(name)?.(name, payload);
  }
}
const fakeModule = {
  default: FakeHls,
  Events: events,
} as unknown as typeof import("hls.js");
const active: ReturnType<typeof attachAdaptiveVideo>[] = [];

function setup(
  overrides: Partial<Parameters<typeof attachAdaptiveVideo>[0]> = {},
) {
  const video = {
    src: "",
    currentTime: 6.25,
    playbackRate: 1.5,
    volume: 0.35,
    muted: true,
    paused: true,
    pause: vi.fn(),
    play: vi.fn(),
    load: vi.fn(),
    removeAttribute: vi.fn((name: string) => {
      if (name === "src") video.src = "";
    }),
    canPlayType: vi.fn(() => ""),
  };
  const options = {
    video: video as unknown as HTMLVideoElement,
    manifestUrl: mediaUrl(),
    fallbackUrl: mediaUrl(`${prefix}/progressive.mp4`, {
      supports_range: true,
    }),
    onMode: vi.fn(),
    onQualities: vi.fn(),
    onQuality: vi.fn(),
    onError: vi.fn(),
    onDenied: vi.fn(),
    ...overrides,
  };
  const importer = vi.fn(async () => fakeModule);
  return { video, options, importer };
}
function attach(
  options: Parameters<typeof attachAdaptiveVideo>[0],
  importer: NonNullable<Parameters<typeof attachAdaptiveVideo>[1]>,
) {
  const result = attachAdaptiveVideo(options, importer);
  active.push(result);
  return result;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(now);
  vi.stubGlobal("window", { location: { origin } });
  loader.create.mockReset().mockReturnValue(loader.implementation);
  FakeHls.instances = [];
  FakeHls.isSupported.mockReset().mockReturnValue(true);
});
afterEach(() => {
  active.splice(0).forEach((item) => item.destroy());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("signed HLS request withholding", () => {
  it("accepts exact master, rendition, segment and caption children of one grant", () => {
    const allowed = authorizedHlsRequestPredicate(mediaUrl(), () => now);
    for (const key of [
      masterKey,
      `${prefix}/hls/360p/index.m3u8`,
      `${prefix}/hls/2160p/segment-00000.ts`,
      `${prefix}/hls/captions/en.m3u8`,
      `${prefix}/hls/captions/en.vtt`,
    ]) {
      expect(allowed(mediaUrl(key))).toBe(true);
    }
  });

  it.each([
    "tenant_id",
    "person_id",
    "session_id",
    "activity_id",
    "activity_version",
    "asset_id",
    "version_id",
    "binding_id",
    "enrollment_id",
    "delivery_grant_id",
  ])("rejects a child with changed %s", (field) => {
    expect(
      authorizedHlsRequestPredicate(
        mediaUrl(),
        () => now,
      )(
        mediaUrl(`${prefix}/hls/360p/index.m3u8`, {
          [field]: "different-scope",
        }),
      ),
    ).toBe(false);
  });

  it.each([
    { iat: claims.iat - 1 },
    { exp: claims.exp + 1 },
    { exp: now / 1000 },
    { exp: claims.iat },
    { exp: claims.iat + 3601 },
    { iat: now / 1000 + 31 },
    { iat: -1 },
    { iat: 1.25 },
    { exp: "9999999999" },
    { exp: Number.MAX_SAFE_INTEGER },
    { person_id: null },
    { session_id: "bad session" },
    { binding_id: "" },
    { token_type: "read" },
    { typ: "OTHER" },
  ])("rejects malformed or changed claims %#", (changes) => {
    expect(
      authorizedHlsRequestPredicate(
        mediaUrl(),
        () => now,
      )(mediaUrl(masterKey, changes)),
    ).toBe(false);
  });

  it("rechecks the original expiry on every child, including after waiting", () => {
    let clock = now;
    const allowed = authorizedHlsRequestPredicate(mediaUrl(), () => clock);
    expect(allowed(mediaUrl())).toBe(true);
    clock = claims.exp * 1000;
    expect(allowed(mediaUrl())).toBe(false);
  });

  it("never accepts children when the initial master was invalid", () => {
    expect(
      authorizedHlsRequestPredicate("not-a-url", () => now)(mediaUrl()),
    ).toBe(false);
  });

  it.each([
    (url: string) => url.replace(origin, "https://elsewhere.example"),
    (url: string) => url.replace(origin, "http://learn.authorityclosers.test"),
    (url: string) => url.replace("https://", "https://user@"),
    (url: string) => `${url}#fragment`,
    (url: string) => `${url}&other=1`,
    (url: string) => `${url}&token=duplicate`,
    (url: string) => url.replace("/playback/", "/read/"),
    (url: string) => url.replace(/token=.*/, "token=AC-MEDIA.e30.A"),
    (url: string) =>
      url.replace(/token=.*/, `token=AC-MEDIA._w.${"A".repeat(43)}`),
    (url: string) =>
      url.replace(/token=.*/, `token=AC-MEDIA.W10.${"A".repeat(43)}`),
    (url: string) =>
      url.replace(
        /token=.*/,
        `token=AC-MEDIA.${"A".repeat(4100)}.${"A".repeat(43)}`,
      ),
  ])("rejects unsafe URL shapes %#", (mutate) => {
    expect(
      authorizedHlsRequestPredicate(mediaUrl(), () => now)(mutate(mediaUrl())),
    ).toBe(false);
  });

  it("requires the exact canonical encoded key from the claims", () => {
    const allowed = authorizedHlsRequestPredicate(mediaUrl(), () => now);
    expect(allowed(mediaUrl(masterKey, { key: `${prefix}/other.m3u8` }))).toBe(
      false,
    );
    expect(allowed(mediaUrl().replace(/%2F/g, "/"))).toBe(false);
    expect(allowed(mediaUrl(`${prefix}/../other.m3u8`))).toBe(false);
  });

  it.each([
    `tenants/other-tenant/media/video/${asset}/${version}/original/renditions/a.ts`,
    `tenants/${tenant}/media/video/other-asset/${version}/original/renditions/a.ts`,
    `tenants/${tenant}/media/video/${asset}/other-version/original/renditions/a.ts`,
    `tenants/${tenant}/media/avatar/${asset}/${version}/original/renditions/a.ts`,
  ])("requires object namespace to match the pinned media scope %#", (key) => {
    expect(
      authorizedHlsRequestPredicate(mediaUrl(), () => now)(mediaUrl(key)),
    ).toBe(false);
  });
});

describe("adaptive decoder lifecycle", () => {
  it("creates the guarded engine and binds only the authorized master", async () => {
    const { options, importer, video } = setup();
    await attach(options, importer).ready;
    const engine = FakeHls.instances[0];
    expect(importer).toHaveBeenCalledOnce();
    expect(engine.config).toMatchObject({
      debug: false,
      loader: loader.implementation,
      lowLatencyMode: false,
      maxBufferLength: 20,
      maxMaxBufferLength: 30,
    });
    expect(engine.attachMedia).toHaveBeenCalledExactlyOnceWith(video);
    expect(engine.loadSource).toHaveBeenCalledExactlyOnceWith(
      options.manifestUrl,
    );
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("hls");
    expect(video.play).not.toHaveBeenCalled();
    const guarded = loader.create.mock.calls[0][0];
    expect(guarded.allowedUrl(mediaUrl(`${prefix}/hls/360p/index.m3u8`))).toBe(
      true,
    );
    expect(
      guarded.allowedUrl(mediaUrl(masterKey, { person_id: "another-person" })),
    ).toBe(false);
  });

  it("cancels an asynchronous import without attaching or reporting late events", async () => {
    const { options } = setup();
    const imported = deferred<typeof fakeModule>();
    const controller = attach(options, () => imported.promise);
    controller.destroy();
    imported.resolve(fakeModule);
    await controller.ready;
    expect(FakeHls.instances).toHaveLength(0);
    expect(options.onMode).not.toHaveBeenCalled();
    expect(options.onError).not.toHaveBeenCalled();
    expect(options.onDenied).not.toHaveBeenCalled();
  });

  it("denies an invalid master before import or decoder creation", async () => {
    const { options, importer } = setup({
      manifestUrl: "https://invalid.example/file.m3u8",
    });
    await attach(options, importer).ready;
    expect(importer).not.toHaveBeenCalled();
    expect(options.onDenied).toHaveBeenCalledExactlyOnceWith();
    expect(FakeHls.instances).toHaveLength(0);
  });

  it("rejects even a well-shaped foreign-origin master before decoder construction", async () => {
    const { options, importer } = setup({
      manifestUrl: mediaUrl(masterKey, {}, "https://foreign.example"),
    });
    await attach(options, importer).ready;
    expect(options.onDenied).toHaveBeenCalledExactlyOnceWith();
    expect(FakeHls.instances).toHaveLength(0);
    expect(options.onMode).not.toHaveBeenCalled();
  });

  it("reports import failure without silently falling back or exposing the error", async () => {
    const { options, video } = setup();
    await attach(options, async () => {
      throw new Error("synthetic-private-locator");
    }).ready;
    expect(options.onError).toHaveBeenCalledExactlyOnceWith();
    expect(options.onMode).not.toHaveBeenCalled();
    expect(video.src).toBe("");
  });

  it("offers only real valid rendition indices and leaves media control state intact", async () => {
    const { options, importer, video } = setup();
    const controller = attach(options, importer);
    await controller.ready;
    const engine = FakeHls.instances[0];
    engine.levels = [{ height: 360 }, { height: NaN }, { height: 2160 }];
    engine.emit(events.MANIFEST_PARSED);
    expect(options.onQualities).toHaveBeenCalledExactlyOnceWith([
      { id: "hls-0", label: "360p" },
      { id: "hls-2", label: "2160p" },
    ]);
    expect(controller.selectQuality("hls-2")).toBe(true);
    expect(engine.currentLevel).toBe(2);
    expect(controller.selectQuality("hls-1")).toBe(false);
    expect(controller.selectQuality("hls-99")).toBe(false);
    expect(controller.selectQuality("2160p")).toBe(false);
    expect(engine.currentLevel).toBe(2);
    expect(controller.selectQuality("auto")).toBe(true);
    expect(engine.currentLevel).toBe(-1);
    expect(video).toMatchObject({
      currentTime: 6.25,
      playbackRate: 1.5,
      volume: 0.35,
      muted: true,
      paused: true,
    });
    expect(video.pause).not.toHaveBeenCalled();
    expect(video.load).not.toHaveBeenCalled();
    expect(video.play).not.toHaveBeenCalled();
    engine.emit(events.LEVEL_SWITCHED, { level: 2 });
    expect(options.onQuality).toHaveBeenCalledExactlyOnceWith("hls-2");
  });

  it.each([
    { levels: [] },
    { levels: Array.from({ length: 17 }, () => ({ height: 360 })) },
  ])(
    "rejects an empty or excessive quality inventory %#",
    async ({ levels }) => {
      const { options, importer } = setup();
      await attach(options, importer).ready;
      const engine = FakeHls.instances[0];
      engine.levels = levels;
      engine.emit(events.MANIFEST_PARSED);
      expect(engine.destroy).toHaveBeenCalledOnce();
      expect(options.onError).toHaveBeenCalledExactlyOnceWith();
      expect(options.onQualities).not.toHaveBeenCalled();
    },
  );

  it("ignores unrecognized level events rather than forwarding raw event values", async () => {
    const { options, importer } = setup();
    await attach(options, importer).ready;
    const engine = FakeHls.instances[0];
    engine.emit(events.MANIFEST_PARSED);
    for (const level of [
      undefined,
      -1,
      3,
      0.5,
      "synthetic-private-locator",
      { url: "private" },
    ]) {
      engine.emit(events.LEVEL_SWITCHED, { level, details: "do not forward" });
    }
    expect(options.onQuality).not.toHaveBeenCalled();
  });

  it.each([401, 403, 410])(
    "denies HTTP %s without progressive fallback or raw event leakage",
    async (code) => {
      const { options, importer, video } = setup();
      const controller = attach(options, importer);
      await controller.ready;
      const engine = FakeHls.instances[0];
      engine.emit(events.ERROR, {
        fatal: false,
        response: { code, url: "synthetic-private-locator" },
        details: "private",
      });
      engine.emit(events.ERROR, { fatal: true, response: { code } });
      engine.emit(events.MANIFEST_PARSED);
      engine.emit(events.LEVEL_SWITCHED, { level: 1 });
      expect(options.onDenied).toHaveBeenCalledExactlyOnceWith();
      expect(options.onError).not.toHaveBeenCalled();
      expect(options.onMode).toHaveBeenCalledExactlyOnceWith("hls");
      expect(options.onQualities).not.toHaveBeenCalled();
      expect(options.onQuality).not.toHaveBeenCalled();
      expect(engine.destroy).toHaveBeenCalledOnce();
      expect(video.src).toBe("");
      expect(controller.selectQuality("auto")).toBe(false);
    },
  );

  it("stops on a fatal decode/network error, ignores its late events, and does not fallback", async () => {
    const { options, importer } = setup();
    const controller = attach(options, importer);
    await controller.ready;
    const engine = FakeHls.instances[0];
    engine.emit(events.ERROR, {
      fatal: false,
      response: { code: 500 },
      details: "private",
    });
    expect(options.onError).not.toHaveBeenCalled();
    engine.emit(events.ERROR, {
      fatal: true,
      response: { code: 500 },
      details: "private",
    });
    engine.emit(events.MANIFEST_PARSED);
    engine.emit(events.LEVEL_SWITCHED, { level: 1 });
    expect(options.onError).toHaveBeenCalledExactlyOnceWith();
    expect(options.onDenied).not.toHaveBeenCalled();
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("hls");
    expect(options.onQuality).not.toHaveBeenCalled();
    expect(options.onQualities).not.toHaveBeenCalled();
    expect(controller.selectQuality("auto")).toBe(false);
  });

  it("destroys exactly once and ignores a loader denial and engine events after disposal", async () => {
    const { options, importer, video } = setup();
    const controller = attach(options, importer);
    await controller.ready;
    const engine = FakeHls.instances[0];
    controller.destroy();
    controller.destroy();
    loader.create.mock.calls[0][0].onDenied();
    engine.emit(events.ERROR, { fatal: true, response: { code: 403 } });
    expect(engine.destroy).toHaveBeenCalledOnce();
    expect(video.pause).toHaveBeenCalledOnce();
    expect(video.removeAttribute).toHaveBeenCalledExactlyOnceWith("src");
    expect(options.onError).not.toHaveBeenCalled();
    expect(options.onDenied).not.toHaveBeenCalled();
  });

  it("reports a fatal error before media reset and completes terminal cleanup exactly once", async () => {
    const { options, importer, video } = setup();
    const observedPositions: number[] = [];
    video.load.mockImplementation(() => {
      video.currentTime = 0;
    });
    const controller = attach(options, importer);
    options.onError = vi.fn(() => {
      observedPositions.push(video.currentTime);
      // A viewer cleanup can re-enter destroy during notification. The adapter
      // is already terminal, but must still clear its decoder in finally.
      controller.destroy();
    });
    await controller.ready;
    const engine = FakeHls.instances[0];
    engine.emit(events.ERROR, { fatal: true, response: { code: 500 } });
    expect(observedPositions).toEqual([6.25]);
    expect(video.currentTime).toBe(0);
    engine.emit(events.ERROR, { fatal: true, response: { code: 500 } });
    engine.emit(events.LEVEL_SWITCHED, { level: 0 });
    controller.destroy();
    expect(options.onError).toHaveBeenCalledExactlyOnceWith();
    expect(engine.destroy).toHaveBeenCalledOnce();
    expect(video.load).toHaveBeenCalledOnce();
    expect(video.pause).toHaveBeenCalledOnce();
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("hls");
    expect(options.onDenied).not.toHaveBeenCalled();
    expect(options.onQuality).not.toHaveBeenCalled();
    expect(controller.selectQuality("auto")).toBe(false);
  });

  it("still clears the decoder when the viewer's error callback throws", async () => {
    const { options, importer, video } = setup();
    const controller = attach(options, importer);
    await controller.ready;
    const engine = FakeHls.instances[0];
    options.onError = vi.fn(() => {
      throw new Error("Synthetic viewer failure");
    });
    expect(() => engine.emit(events.ERROR, { fatal: true })).toThrow(
      "Synthetic viewer failure",
    );
    expect(engine.destroy).toHaveBeenCalledOnce();
    expect(video.pause).toHaveBeenCalledOnce();
    expect(video.removeAttribute).toHaveBeenCalledExactlyOnceWith("src");
    expect(video.load).toHaveBeenCalledOnce();
    expect(() => engine.emit(events.ERROR, { fatal: true })).not.toThrow();
    controller.destroy();
    expect(options.onError).toHaveBeenCalledExactlyOnceWith();
    expect(engine.destroy).toHaveBeenCalledOnce();
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("hls");
  });

  it("turns a live guarded-loader denial into one terminal denial", async () => {
    const { options, importer } = setup();
    await attach(options, importer).ready;
    const deny = loader.create.mock.calls[0][0].onDenied;
    deny();
    deny();
    expect(options.onDenied).toHaveBeenCalledExactlyOnceWith();
    expect(FakeHls.instances[0].destroy).toHaveBeenCalledOnce();
    expect(options.onError).not.toHaveBeenCalled();
  });

  it("uses native HLS only when MSE HLS is unsupported, before progressive fallback", async () => {
    FakeHls.isSupported.mockReturnValue(false);
    const { options, importer, video } = setup();
    video.canPlayType.mockReturnValue("probably");
    const controller = attach(options, importer);
    await controller.ready;
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("native-hls");
    expect(video.src).toBe(options.manifestUrl);
    expect(video.load).toHaveBeenCalledOnce();
    expect(FakeHls.instances).toHaveLength(0);
    expect(loader.create).not.toHaveBeenCalled();
    expect(controller.selectQuality("auto")).toBe(false);
  });

  it("uses an authorized progressive fallback only when both HLS paths are unsupported", async () => {
    FakeHls.isSupported.mockReturnValue(false);
    const { options, importer, video } = setup();
    await attach(options, importer).ready;
    expect(options.onMode).toHaveBeenCalledExactlyOnceWith("progressive");
    expect(video.src).toBe(options.fallbackUrl);
    expect(FakeHls.instances).toHaveLength(0);
    expect(video.play).not.toHaveBeenCalled();
  });

  it.each([
    undefined,
    mediaUrl(`${prefix}/progressive.mp4`, { session_id: "different-session" }),
  ])(
    "does not use a missing or differently scoped fallback",
    async (fallbackUrl) => {
      FakeHls.isSupported.mockReturnValue(false);
      const { options, importer, video } = setup({ fallbackUrl });
      await attach(options, importer).ready;
      expect(options.onError).toHaveBeenCalledExactlyOnceWith();
      expect(options.onMode).not.toHaveBeenCalled();
      expect(video.src).toBe("");
    },
  );
});
