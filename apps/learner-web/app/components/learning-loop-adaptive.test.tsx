// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as adaptive from "../lib/adaptive-video";
import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
} from "../lib/learner-api";
import { DevelopmentMediaBridgeProvider } from "./development-media-bridge";
import {
  resolveApprovedMedia,
  VideoViewer,
  type VideoTelemetryEvent,
} from "./learning-loop-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2026-09-08T10:00:00Z");
const ORIGIN = "https://learner.authorityclosers.test";
const TENANT = "11111111-1111-4111-8111-111111111111";
const ASSET = "22222222-2222-4222-8222-222222222222";
const VERSION = "33333333-3333-4333-8333-333333333333";
const BINDING = "77777777-7777-4777-8777-777777777777";
const base: ActivityResponse = {
  id: "66666666-6666-4666-8666-666666666666",
  module_id: "module-1",
  program_version_id: "program-version-1",
  position: 1,
  kind: "video",
  title: "Synthetic adaptive lesson",
  prompt: "Watch the fixture",
  state: "available",
  revision: 4,
  required: true,
  allowed_actions: [],
  program_id: "program-1",
  enrollment_id: "88888888-8888-4888-8888-888888888888",
  draft_revision: 0,
  draft_payload: null,
  explanation: {
    activity_id: "66666666-6666-4666-8666-666666666666",
    state: "available",
    required: true,
    reason: "server_resolved_activity_state",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
};

// Synthetic envelope only; no real credential or signing key. The real client
// withholding predicate remains active, while server authorization is not mocked
// as proven by this component suite.
function fixture({
  origin = ORIGIN,
  activity = {},
  binding = BINDING,
  version = VERSION,
  issuedAt = NOW.getTime() / 1000,
  grant = "99999999-9999-4999-8999-999999999999",
  progressive = false,
  nonce = "synthetic-nonce",
}: {
  origin?: string;
  activity?: Partial<ActivityResponse>;
  binding?: string;
  version?: string;
  issuedAt?: number;
  grant?: string;
  progressive?: boolean;
  nonce?: string;
} = {}): ActivityResponse {
  const result = { ...base, ...activity };
  const prefix = `tenants/${TENANT}/media/video/${ASSET}/${version}/original/renditions`;
  const source = (relative: string, range: boolean) => {
    const key = `${prefix}/${relative}`;
    const claims = {
      typ: "AC-MEDIA",
      token_type: "playback",
      iat: issuedAt,
      exp: issuedAt + 120,
      nonce,
      tenant_id: TENANT,
      person_id: "44444444-4444-4444-8444-444444444444",
      session_id: "55555555-5555-4555-8555-555555555555",
      activity_id: result.id,
      activity_version: "published-v1",
      asset_id: ASSET,
      version_id: version,
      binding_id: binding,
      enrollment_id: result.enrollment_id,
      delivery_grant_id: grant,
      supports_range: range,
      key,
    };
    const payload = btoa(
      JSON.stringify(
        Object.fromEntries(
          Object.entries(claims).sort(([a], [b]) => a.localeCompare(b)),
        ),
      ),
    )
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    return `${origin}/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${payload}.${"A".repeat(43)}`;
  };
  return {
    ...result,
    media: {
      state: "approved",
      reason: "approved_media_delivery_available",
      binding_id: binding,
      media_id: ASSET,
      media_version_id: version,
      activity_version: "published-v1",
      content_type: "video/mp4",
      duration_seconds: 12,
      width: 3840,
      height: 2160,
      renditions: [],
      captions: [],
      playback_available: true,
      delivery: {
        protocol: progressive ? "progressive" : "hls",
        manifest_url: progressive ? null : source("hls/master.m3u8", false),
        progressive_url: source("progressive.mp4", true),
      },
    },
  };
}

type Attachment = {
  options: Parameters<typeof adaptive.attachAdaptiveVideo>[0];
  controller: adaptive.AdaptiveVideo;
};
const writes = [
  "startPlayback",
  "heartbeatPlayback",
  "finishPlayback",
  "submitEvidence",
  "saveDraft",
] as const;
let root: Root;
let container: HTMLDivElement;
let current: ActivityResponse;
let api: LearnerApi;
let online: boolean;
let unmounted: boolean;
let trackedCase: boolean;
let attachments: Attachment[];
let committed: ReturnType<typeof vi.fn<() => void>>;
let telemetry: ReturnType<typeof vi.fn<(event: VideoTelemetryEvent) => void>>;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  online = true;
  unmounted = false;
  trackedCase = false;
  attachments = [];
  committed = vi.fn<() => void>();
  telemetry = vi.fn<(event: VideoTelemetryEvent) => void>();
  vi.spyOn(window.location, "origin", "get").mockReturnValue(ORIGIN);
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
  const paused = new WeakMap<HTMLMediaElement, boolean>();
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(
    function (this: HTMLMediaElement) {
      return paused.get(this) !== false;
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(
    async function (this: HTMLMediaElement) {
      paused.set(this, false);
      this.dispatchEvent(new Event("play"));
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    if (paused.get(this) === false) {
      paused.set(this, true);
      this.dispatchEvent(new Event("pause"));
    }
  });
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(
    () => undefined,
  );
  vi.spyOn(adaptive, "attachAdaptiveVideo").mockImplementation((options) => {
    const controller: adaptive.AdaptiveVideo = {
      ready: Promise.resolve(),
      selectQuality: vi.fn(() => true),
      destroy: vi.fn(),
    };
    attachments.push({ options, controller });
    return controller;
  });
  current = fixture();
  api = {
    activity: vi.fn(async () => current),
    ...Object.fromEntries(
      writes.map((name) => [name, vi.fn(async () => ({}))]),
    ),
  } as unknown as LearnerApi;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  for (const name of writes) {
    if (
      trackedCase &&
      (name === "startPlayback" || name === "heartbeatPlayback")
    )
      continue;
    expect(api[name], name).not.toHaveBeenCalled();
  }
  expect(committed).not.toHaveBeenCalled();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

async function mount(activity = current, bridgeOrigin?: string) {
  current = activity;
  await act(async () => {
    const viewer = (
      <VideoViewer
        activity={activity}
        api={api}
        moduleHref="/learn/module-1"
        onPlaybackCommitted={committed}
        onTelemetryEvent={telemetry}
      />
    );
    root.render(
      bridgeOrigin ? (
        <DevelopmentMediaBridgeProvider browserOrigin={bridgeOrigin}>
          {viewer}
        </DevelopmentMediaBridgeProvider>
      ) : (
        viewer
      ),
    );
  });
  const video = container.querySelector("video");
  if (video) {
    Object.defineProperty(video, "duration", { configurable: true, value: 12 });
    Object.defineProperty(video, "readyState", {
      configurable: true,
      value: 4,
    });
    await fire(video, "loadedmetadata");
  }
  return video;
}
async function fire(video: HTMLVideoElement, event: string, time?: number) {
  await act(async () => {
    if (time !== undefined) video.currentTime = time;
    video.dispatchEvent(new Event(event, { bubbles: true }));
  });
}
async function connection(value: boolean) {
  await act(async () => {
    online = value;
    window.dispatchEvent(new Event(value ? "online" : "offline"));
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

it("resolves the valid HLS descriptor and delegates decoding instead of assigning a manifest src", async () => {
  const manifest = current.media!.delivery!.manifest_url!;
  expect(adaptive.authorizedHlsRequestPredicate(manifest)(manifest)).toBe(true);
  expect(resolveApprovedMedia(current).media).toMatchObject({
    protocol: "hls",
    src: manifest,
    fallback: {
      protocol: "progressive",
      src: current.media!.delivery!.progressive_url,
    },
  });
  const video = (await mount())!;
  expect(attachments).toHaveLength(1);
  expect(attachments[0].options.video).toBe(video);
  expect(attachments[0].options.manifestUrl).toBe(manifest);
  expect(attachments[0].options.fallbackUrl).toBe(
    current.media!.delivery!.progressive_url,
  );
  expect(video.getAttribute("src")).toBeNull();
  expect(
    container.querySelector('[data-playback-mode="read-only"]'),
  ).not.toBeNull();
  expect(
    container.querySelector('[data-delivery-mode="loading"]'),
  ).not.toBeNull();
  await act(async () => attachments[0].options.onMode("hls"));
  expect(container.querySelector('[data-delivery-mode="hls"]')).not.toBeNull();
});

it.each(["native-hls", "progressive"] as const)(
  "reflects the adapter's actual %s mode without bypassing it",
  async (mode) => {
    await mount();
    await act(async () => attachments[0].options.onMode(mode));
    expect(
      container.querySelector(`[data-delivery-mode="${mode}"]`),
    ).not.toBeNull();
    expect(attachments).toHaveLength(1);
  },
);

it("shows only adapter-derived qualities and routes the native select to the existing controller", async () => {
  const video = (await mount())!;
  const { options, controller } = attachments[0];
  expect(
    container.querySelector('select[aria-label="Video quality"]'),
  ).toBeNull();
  await act(async () => {
    options.onMode("hls");
    options.onQualities([
      { id: "hls-0", label: "360p" },
      { id: "hls-2", label: "2160p" },
    ]);
    options.onQuality("hls-0");
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Open playback settings"]',
      )!
      .click();
  });
  const select = container.querySelector<HTMLSelectElement>(
    'select[aria-label="Video quality"]',
  )!;
  expect(
    [...select.options].map((option) => [option.value, option.textContent]),
  ).toEqual([
    ["auto", "Auto · 360p"],
    ["hls-0", "360p"],
    ["hls-2", "2160p"],
  ]);
  await fire(video, "timeupdate", 5.25);
  video.playbackRate = 1.5;
  video.volume = 0.3;
  video.muted = true;
  await act(async () => {
    select.value = "hls-2";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(controller.selectQuality).toHaveBeenCalledExactlyOnceWith("hls-2");
  expect(select.value).toBe("hls-2");
  expect(video.currentTime).toBe(5.25);
  expect(video.playbackRate).toBe(1.5);
  expect(video.volume).toBe(0.3);
  expect(video.muted).toBe(true);
  expect(attachments).toHaveLength(1);
  expect(controller.destroy).not.toHaveBeenCalled();
});

it("does not recreate the decoder on time, buffering, volume or settings state updates", async () => {
  const video = (await mount())!;
  const first = attachments[0];
  await act(async () => first.options.onMode("hls"));
  for (const time of [1, 2, 3, 4]) await fire(video, "timeupdate", time);
  await fire(video, "waiting");
  await fire(video, "canplay");
  await fire(video, "volumechange");
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Open playback settings"]',
      )!
      .click(),
  );
  await fire(video, "timeupdate", 5);
  expect(attachments).toHaveLength(1);
  expect(first.controller.destroy).not.toHaveBeenCalled();
  // Error handling must use current render state without becoming an effect
  // dependency that destroys the engine on each timeupdate.
  await act(async () => first.options.onError());
  expect(container.textContent).toContain(
    "Approved lesson media could not be loaded",
  );
  expect(attachments).toHaveLength(1);
});

it.each([
  { activity: { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" } },
  { binding: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" },
  { version: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" },
])(
  "destroys the previous adapter when pinned playback scope changes %#",
  async (change) => {
    await mount();
    const first = attachments[0];
    const replacement = fixture(change);
    await mount(replacement);
    expect(first.controller.destroy).toHaveBeenCalled();
    expect(attachments).toHaveLength(2);
    expect(attachments[1].options.manifestUrl).toBe(
      replacement.media!.delivery!.manifest_url,
    );
  },
);

it("destroys delivery and withholds video when the original grant expires", async () => {
  await mount();
  const first = attachments[0];
  await act(async () => vi.advanceTimersByTimeAsync(120_001));
  expect(first.controller.destroy).toHaveBeenCalled();
  expect(container.querySelector("video")).toBeNull();
  expect(attachments).toHaveLength(1);
});

it.each([false, true])(
  "renews %s delivery in place and retains a paused presentation beyond the old deadline",
  async (progressive) => {
    const video = (await mount(fixture({ progressive })))!;
    await fire(video, "timeupdate", 5.25);
    video.playbackRate = 1.5;
    video.muted = true;
    video.volume = 0.3;
    const original = current;
    const replacement = fixture({
      progressive,
      issuedAt: NOW.getTime() / 1000 + 100,
      grant: "renewal-one",
    });
    vi.mocked(api.activity).mockResolvedValue(replacement);
    await act(async () => vi.advanceTimersByTimeAsync(100_001));
    expect(api.activity).toHaveBeenCalledTimes(1);
    expect(container.querySelector("video")).toBe(video);
    if (!progressive) {
      expect(attachments).toHaveLength(2);
      expect(attachments[0].controller.destroy).toHaveBeenCalled();
      expect(attachments[1].options.manifestUrl).toBe(
        replacement.media!.delivery!.manifest_url,
      );
    } else expect(video.src).toBe(replacement.media!.delivery!.progressive_url);
    video.currentTime = 0;
    await fire(video, "loadedmetadata");
    await fire(video, "seeked");
    await fire(video, "canplay");
    expect(video.currentTime).toBe(5.25);
    expect(video.playbackRate).toBe(1.5);
    expect(video.muted).toBe(true);
    expect(video.volume).toBe(0.3);
    expect(video.paused).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(25_000));
    // A parent render carrying the old descriptor must not undo the renewal.
    await mount(original);
    expect(container.querySelector("video")).toBe(video);
    expect(container.textContent).not.toContain("Reopen this lesson");
  },
);

it("preserves active playback across a delivery rotation without autoplaying a paused lesson", async () => {
  const video = (await mount())!;
  await act(async () => video.play());
  await fire(video, "timeupdate", 3);
  vi.mocked(api.activity).mockResolvedValue(
    fixture({ issuedAt: NOW.getTime() / 1000 + 100, grant: "renewal-playing" }),
  );
  await act(async () => vi.advanceTimersByTimeAsync(100_001));
  await act(async () => video.pause());
  video.currentTime = 0;
  await fire(video, "loadedmetadata");
  expect(video.currentTime).toBe(3);
  await fire(video, "canplay");
  expect(video.paused).toBe(false);
});

it("honors an explicit Pause and speed change while a renewed decoder is loading", async () => {
  const video = (await mount())!;
  await act(async () => video.play());
  await fire(video, "timeupdate", 3);
  vi.mocked(api.activity).mockResolvedValue(
    fixture({
      issuedAt: NOW.getTime() / 1000 + 100,
      grant: "pause-during-renewal",
    }),
  );
  await act(async () => vi.advanceTimersByTimeAsync(100_001));
  await act(async () => video.pause()); // decoder teardown, not user intent
  video.currentTime = 0;
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Open playback settings"]',
      )!
      .click(),
  );
  await act(async () => {
    container
      .querySelector<HTMLButtonElement>('[aria-label="Pause lesson"]')!
      .click();
    const rate = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Playback speed"]',
    )!;
    rate.value = "0.75";
    rate.dispatchEvent(new Event("change", { bubbles: true }));
    container
      .querySelector<HTMLButtonElement>('[aria-label="Mute lesson"]')!
      .click();
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Skip forward 10 seconds (L)"]',
      )!
      .click();
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Skip back 10 seconds (J)"]',
      )!
      .click();
  });
  video.currentTime = 0;
  await fire(video, "loadedmetadata");
  await fire(video, "canplay");
  expect(video.currentTime).toBe(2); // saved3 -> forward12 -> back2, never reset0
  expect(video.paused).toBe(true);
  expect(video.playbackRate).toBe(0.75);
  expect(video.muted).toBe(true);
});

it("reconciles a pending heartbeat after the predecessor expires without replacing the watch session", async () => {
  trackedCase = true;
  api.startPlayback = vi.fn<LearnerApi["startPlayback"]>(async (id) => ({
    activity_id: id,
    session_id: "continuous-session",
    session_token: "synthetic-watch-token",
    revision: 1,
    expires_at: new Date(NOW.getTime() + 3_600_000).toISOString(),
    duration_seconds: 12,
  }));
  const pending =
    deferred<Awaited<ReturnType<LearnerApi["heartbeatPlayback"]>>>();
  api.heartbeatPlayback = vi
    .fn<LearnerApi["heartbeatPlayback"]>(async (_id, event) => ({
      session_id: event.session_id,
      sequence: event.sequence,
      revision: event.sequence + 1,
      interval_id: `interval-${event.sequence}`,
      observed_at: new Date().toISOString(),
    }))
    .mockImplementationOnce(() => pending.promise);
  const video = (await mount(
    fixture({ activity: { allowed_actions: ["complete_video"] } }),
  ))!;
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click(),
  );
  await fire(video, "timeupdate", 5);
  expect(api.heartbeatPlayback).toHaveBeenCalledTimes(1);
  vi.mocked(api.activity).mockResolvedValue(
    fixture({
      activity: { allowed_actions: ["complete_video"] },
      issuedAt: NOW.getTime() / 1000 + 100,
      grant: "during-heartbeat",
    }),
  );
  await act(async () => vi.advanceTimersByTimeAsync(100_001));
  await fire(video, "loadedmetadata");
  await fire(video, "canplay");
  await act(async () => vi.advanceTimersByTimeAsync(25_000));
  await act(async () =>
    pending.resolve({
      session_id: "continuous-session",
      sequence: 1,
      revision: 2,
      interval_id: "interval-1",
      observed_at: new Date().toISOString(),
    }),
  );
  await fire(video, "timeupdate", 10);
  expect(api.startPlayback).toHaveBeenCalledTimes(1);
  expect(api.heartbeatPlayback).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.heartbeatPlayback).mock.calls[1][1]).toMatchObject({
    session_id: "continuous-session",
    sequence: 2,
    start_seconds: 5,
    end_seconds: 10,
    kind: "watch",
  });
  expect(attachments).toHaveLength(2);
  expect(container.textContent).not.toContain("Restart lesson");
});

it("never attaches a pending or denied renewal and ignores a late response after expiry", async () => {
  await mount();
  const pending = deferred<ActivityResponse>();
  vi.mocked(api.activity).mockImplementationOnce(() => pending.promise);
  await act(async () => vi.advanceTimersByTimeAsync(100_001));
  expect(attachments).toHaveLength(1);
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(container.querySelector("video")).toBeNull();
  await act(async () =>
    pending.resolve(
      fixture({ issuedAt: NOW.getTime() / 1000 + 100, grant: "too-late" }),
    ),
  );
  expect(attachments).toHaveLength(1);
  expect(container.querySelector("video")).toBeNull();
});

it("does not reload twice when concurrent authenticated reads re-sign the same successor grant", async () => {
  trackedCase = true;
  api.startPlayback = vi.fn<LearnerApi["startPlayback"]>(async (id) => ({
    activity_id: id,
    session_id: "one-session",
    session_token: "synthetic-token",
    revision: 1,
    expires_at: new Date(NOW.getTime() + 3_600_000).toISOString(),
    duration_seconds: 12,
  }));
  const pendingStartRead = deferred<ActivityResponse>();
  const successor = {
    activity: { allowed_actions: ["complete_video" as const] },
    issuedAt: NOW.getTime() / 1000 + 100,
    grant: "one-successor",
  };
  api.activity = vi
    .fn<LearnerApi["activity"]>()
    .mockImplementationOnce(() => pendingStartRead.promise)
    .mockResolvedValue(fixture(successor));
  const video = (await mount(
    fixture({ activity: { allowed_actions: ["complete_video"] } }),
  ))!;
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click(),
  );
  expect(api.activity).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(100_001));
  expect(api.activity).toHaveBeenCalledTimes(2);
  expect(attachments).toHaveLength(2);
  await fire(video, "loadedmetadata");
  await act(async () =>
    pendingStartRead.resolve(
      fixture({ ...successor, nonce: "same-grant-different-signature-input" }),
    ),
  );
  expect(attachments).toHaveLength(2);
  expect(attachments[1].controller.destroy).not.toHaveBeenCalled();
  expect(api.startPlayback).toHaveBeenCalledTimes(1);
});

it.each([401, 403, 404, 410])(
  "stops on renewal denial %i without repeated requests",
  async (status) => {
    await mount();
    vi.mocked(api.activity).mockRejectedValue(new ApiError(status, "Denied"));
    await act(async () => vi.advanceTimersByTimeAsync(119_000));
    expect(api.activity).toHaveBeenCalledTimes(1);
    expect(attachments).toHaveLength(1);
    expect(container.querySelector("video")).toBeNull();
  },
);

it("destroys the adapter on unmount and starts no replacement", async () => {
  await mount();
  const first = attachments[0];
  await act(async () => root.unmount());
  unmounted = true;
  expect(first.controller.destroy).toHaveBeenCalled();
  expect(container.querySelector("video")).toBeNull();
  expect(attachments).toHaveLength(1);
});

it("waits for same-scope authorization refresh before recreating an offline decoder", async () => {
  await mount();
  const first = attachments[0];
  const pending = deferred<ActivityResponse>();
  vi.mocked(api.activity).mockImplementationOnce(() => pending.promise);
  await connection(false);
  expect(first.controller.destroy).toHaveBeenCalled();
  expect(attachments).toHaveLength(1);
  await connection(true);
  expect(api.activity).toHaveBeenCalledExactlyOnceWith(current.id);
  expect(attachments).toHaveLength(1);
  await act(async () => pending.resolve(current));
  expect(attachments).toHaveLength(2);
  expect(attachments[1].options.manifestUrl).toBe(
    current.media!.delivery!.manifest_url,
  );
});

it("does not recreate delivery when reconnect authorization is denied", async () => {
  await mount();
  const pending = deferred<ActivityResponse>();
  vi.mocked(api.activity).mockImplementationOnce(() => pending.promise);
  await connection(false);
  await connection(true);
  expect(attachments).toHaveLength(1);
  await act(async () => pending.reject(new ApiError(403, "Access changed")));
  expect(attachments).toHaveLength(1);
  expect(container.querySelector("video")).toBeNull();
});

it("captures position before fatal decoder cleanup and restores only after retry authorization succeeds", async () => {
  const video = (await mount())!;
  const first = attachments[0];
  await act(async () => first.options.onMode("hls"));
  await fire(video, "timeupdate", 5.25);
  vi.mocked(video.load).mockImplementation(() => {
    video.currentTime = 0;
  });
  await act(async () => {
    // The real adapter now notifies the viewer before its finally block clears
    // the media element. Exercise that exact order at the mocked boundary.
    first.options.onError();
    video.load();
  });
  expect(video.currentTime).toBe(0);
  expect(first.controller.destroy).toHaveBeenCalled();
  expect(attachments).toHaveLength(1);
  const pending = deferred<ActivityResponse>();
  vi.mocked(api.activity).mockImplementationOnce(() => pending.promise);
  const retry = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find((button) => button.textContent?.trim() === "Retry media");
  expect(retry).toBeDefined();
  await act(async () => retry!.click());
  expect(api.activity).toHaveBeenCalledExactlyOnceWith(current.id);
  expect(attachments).toHaveLength(1);
  expect(video.currentTime).toBe(0);
  await act(async () => pending.resolve(current));
  expect(attachments).toHaveLength(2);
  await act(async () => attachments[1].options.onMode("hls"));
  await fire(video, "loadedmetadata");
  expect(video.currentTime).toBe(5.25);
  expect(video.paused).toBe(true);
  expect(attachments[1].controller.destroy).not.toHaveBeenCalled();
});

it("restores local playback controls and reapplies the selected quality after authorized reconnect", async () => {
  const video = (await mount())!;
  const qualities = [
    { id: "hls-0", label: "360p" },
    { id: "hls-2", label: "2160p" },
  ];
  await act(async () => {
    attachments[0].options.onMode("hls");
    attachments[0].options.onQualities(qualities);
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Open playback settings"]',
      )!
      .click();
  });
  const quality = container.querySelector<HTMLSelectElement>(
    'select[aria-label="Video quality"]',
  )!;
  const rate = container.querySelector<HTMLSelectElement>(
    'select[aria-label="Playback speed"]',
  )!;
  await act(async () => {
    quality.value = "hls-2";
    quality.dispatchEvent(new Event("change", { bubbles: true }));
    rate.value = "1.5";
    rate.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await fire(video, "timeupdate", 5.25);
  video.volume = 0.3;
  video.muted = true;
  await connection(false);
  // Model the media element being cleared by the real destroyed decoder. The
  // saved snapshot must come from before that disposal, not these reset values.
  video.currentTime = 0;
  video.playbackRate = 1;
  video.volume = 1;
  video.muted = false;
  await connection(true);
  expect(attachments).toHaveLength(2);
  const replacement = attachments[1];
  expect(replacement.controller.selectQuality).not.toHaveBeenCalled();
  await act(async () => {
    replacement.options.onMode("hls");
    replacement.options.onQualities(qualities);
  });
  await fire(video, "loadedmetadata");
  expect(replacement.controller.selectQuality).toHaveBeenCalledExactlyOnceWith(
    "hls-2",
  );
  expect(quality.value).toBe("hls-2");
  expect(video.currentTime).toBe(5.25);
  expect(video.playbackRate).toBe(1.5);
  expect(rate.value).toBe("1.5");
  expect(video.volume).toBe(0.3);
  expect(video.muted).toBe(true);
  expect(video.paused).toBe(true);
});

it("retains the existing tracked session across reconnect instead of inventing a new clock at an offset", async () => {
  trackedCase = true;
  let sessionNumber = 0;
  api.startPlayback = vi.fn<LearnerApi["startPlayback"]>(
    async (activityId) => ({
      activity_id: activityId,
      session_id: `synthetic-session-${++sessionNumber}`,
      session_token: "synthetic-playback-token",
      revision: 1,
      expires_at: new Date(NOW.getTime() + 120_000).toISOString(),
      duration_seconds: 12,
    }),
  );
  api.heartbeatPlayback = vi.fn<LearnerApi["heartbeatPlayback"]>(
    async (_id, event) => ({
      session_id: event.session_id,
      sequence: event.sequence,
      revision: event.sequence + 1,
      interval_id: `synthetic-interval-${event.sequence}`,
      observed_at: NOW.toISOString(),
    }),
  );
  const video = (await mount(
    fixture({ activity: { allowed_actions: ["complete_video"] } }),
  ))!;
  expect(
    container.querySelector('[data-playback-mode="tracked"]'),
  ).not.toBeNull();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click(),
  );
  expect(api.startPlayback).toHaveBeenCalledTimes(1);
  await fire(video, "timeupdate", 4);
  expect(api.heartbeatPlayback).not.toHaveBeenCalled();
  await connection(false);
  video.currentTime = 0;
  await connection(true);
  expect(attachments).toHaveLength(2);
  await fire(video, "loadedmetadata");
  expect(video.currentTime).toBe(4);
  expect(video.paused).toBe(true);
  expect(api.heartbeatPlayback).not.toHaveBeenCalled();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click(),
  );
  expect(api.startPlayback).toHaveBeenCalledTimes(1);
  await fire(video, "timeupdate", 10);
  expect(api.heartbeatPlayback).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api.heartbeatPlayback).mock.calls[0][1]).toMatchObject({
    session_id: "synthetic-session-1",
    kind: "watch",
    start_seconds: 0,
    end_seconds: 10,
  });
});

it("ignores a reconnect read that finishes after the viewer unmounts", async () => {
  await mount();
  const pending = deferred<ActivityResponse>();
  vi.mocked(api.activity).mockImplementationOnce(() => pending.promise);
  await connection(false);
  await connection(true);
  await act(async () => root.unmount());
  unmounted = true;
  await act(async () => pending.resolve(current));
  expect(attachments).toHaveLength(1);
  expect(container.querySelector("video")).toBeNull();
});

it("keeps read-only adaptive viewing separate from watch sessions and evidence", async () => {
  const video = (await mount())!;
  await act(async () => attachments[0].options.onMode("hls"));
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click(),
  );
  await fire(video, "timeupdate", 6);
  await fire(video, "seeked", 9);
  await fire(video, "ended", 12);
  expect(video.currentTime).toBe(12);
  expect(container.textContent).toContain("Video preview");
  expect(attachments).toHaveLength(1);
});

it("preserves the progressive-only staging development bridge even for a valid HLS descriptor", async () => {
  const bridgeOrigin = "http://learner.localhost:3100";
  vi.stubEnv("NODE_ENV", "development");
  vi.mocked(
    Object.getOwnPropertyDescriptor(window.location, "origin")!.get!,
  ).mockReturnValue(bridgeOrigin);
  const activity = fixture({ origin: "https://staging.authorityclosers.com" });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_input, init) => {
      const sources = (JSON.parse(String(init?.body)) as { sources: string[] })
        .sources;
      expect(sources).toEqual([activity.media!.delivery!.progressive_url]);
      return Response.json({
        items: [
          {
            path: `/v1/dev-bridge/media/${"b".repeat(43)}`,
            expires_at: NOW.getTime() + 120_000,
          },
        ],
      });
    });
  const video = (await mount(activity, bridgeOrigin))!;
  expect(fetcher).toHaveBeenCalledOnce();
  expect(video.src).toBe(
    `${bridgeOrigin}/v1/dev-bridge/media/${"b".repeat(43)}`,
  );
  expect(
    container.querySelector('[data-delivery-mode="progressive"]'),
  ).not.toBeNull();
  expect(attachments).toHaveLength(0);
});
