// @vitest-environment happy-dom

import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
} from "../lib/learner-api";
import {
  approvedDeliveryExpiresAt,
  resolveApprovedMedia,
  VideoViewer,
  type AuthorizedVideoMedia,
} from "./learning-loop-runtime";
import { DevelopmentMediaBridgeProvider } from "./development-media-bridge";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2026-09-07T16:00:00Z");
const baseActivity: ActivityResponse = {
  id: "video-1",
  module_id: "module-1",
  program_version_id: "version-1",
  position: 1,
  kind: "video",
  title: "Approved lesson",
  prompt: "Watch the lesson",
  state: "available",
  revision: 4,
  required: true,
  allowed_actions: [],
  program_id: "program-1",
  enrollment_id: "enrollment-1",
  draft_revision: 0,
  draft_payload: null,
  explanation: {
    activity_id: "video-1",
    state: "available",
    required: true,
    reason: "server_resolved_activity_state",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
};

// Synthetic envelope only: no real signing material or session/URL is copied.
// The client reads expiry bounds; tests do not claim server authentication.
function activityFixture(
  overrides: Partial<ActivityResponse> = {},
  claimsOverride: Record<string, unknown> = {},
): ActivityResponse {
  const activity = { ...baseActivity, ...overrides };
  const key = "synthetic/lesson.mp4";
  const claims = {
    typ: "AC-MEDIA",
    token_type: "playback",
    iat: NOW.getTime() / 1000,
    exp: NOW.getTime() / 1000 + 120,
    activity_id: activity.id,
    activity_version: "published-1",
    asset_id: "asset-1",
    version_id: "media-version-1",
    binding_id: "binding-1",
    enrollment_id: activity.enrollment_id,
    delivery_grant_id: "synthetic-grant",
    key,
    ...claimsOverride,
  };
  const token = `AC-MEDIA.${btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.${"a".repeat(43)}`;
  return {
    ...activity,
    media: {
      state: "approved",
      reason: "approved_media_delivery_available",
      binding_id: "binding-1",
      media_id: "asset-1",
      media_version_id: "media-version-1",
      activity_version: "published-1",
      content_type: "video/mp4",
      duration_seconds: 12,
      width: 1920,
      height: 1080,
      renditions: [],
      captions: [],
      playback_available: true,
      delivery: {
        protocol: "hls",
        manifest_url: "https://learner.example.invalid/master.m3u8",
        progressive_url: `https://learner.example.invalid/v1/media/playback/${encodeURIComponent(key)}?token=${token}`,
      },
    },
  };
}

let root: Root;
let container: HTMLDivElement;
let api: LearnerApi;
let online: boolean;
let current: ActivityResponse;
const writes = [
  "startPlayback",
  "heartbeatPlayback",
  "finishPlayback",
  "submitEvidence",
  "saveDraft",
] as const;
let onCommitted: () => void;
let unmounted: boolean;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  online = true;
  unmounted = false;
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
  current = activityFixture();
  onCommitted = vi.fn();
  api = {
    activity: vi.fn(async () => current),
    startPlayback: vi.fn(async () => ({
      session_id: "synthetic-session",
      session_token: "synthetic-token",
      revision: 1,
      expires_at: new Date(NOW.getTime() + 120_000).toISOString(),
      duration_seconds: 12,
    })),
    heartbeatPlayback: vi.fn(async (_id, event) => ({
      session_id: "synthetic-session",
      sequence: event.sequence,
      revision: event.sequence + 1,
    })),
    finishPlayback: vi.fn(async () => ({
      session_id: "synthetic-session",
      revision: 4,
    })),
    submitEvidence: vi.fn(async () => ({})),
    saveDraft: vi.fn(async () => ({})),
  } as unknown as LearnerApi;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

async function mount(
  activity = current,
  media?: AuthorizedVideoMedia,
  bridgeOrigin?: string | null,
) {
  current = activity;
  await act(async () => {
    const viewer = (
      <VideoViewer
        activity={activity}
        api={api}
        moduleHref="/learn/module-1"
        media={media}
        onPlaybackCommitted={onCommitted}
      />
    );
    root.render(
      bridgeOrigin === undefined ? (
        viewer
      ) : (
        <DevelopmentMediaBridgeProvider browserOrigin={bridgeOrigin}>
          {viewer}
        </DevelopmentMediaBridgeProvider>
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
async function play() {
  await act(async () => {
    container
      .querySelector<HTMLButtonElement>('[aria-label="Play lesson"]')!
      .click();
  });
}
async function connection(connected: boolean) {
  await act(async () => {
    online = connected;
    window.dispatchEvent(new Event(connected ? "online" : "offline"));
  });
}
function noWrites() {
  for (const name of writes) expect(api[name], name).not.toHaveBeenCalled();
  expect(onCommitted).not.toHaveBeenCalled();
}

const BRIDGE_ORIGIN = "http://learner.localhost:3100";
const STAGING_ORIGIN = "https://staging.authorityclosers.com";
const BRIDGE_KEY =
  "tenants/tenant-1/media/lesson_video/asset-1/media-version-1/original/lesson.mp4";

function stagingFixture(tracked = false): ActivityResponse {
  const result = activityFixture(
    { allowed_actions: tracked ? ["complete_video"] : [] },
    { key: BRIDGE_KEY },
  );
  const query = new URL(result.media!.delivery!.progressive_url!).search;
  result.media!.delivery!.progressive_url = `${STAGING_ORIGIN}/v1/media/playback/${encodeURIComponent(BRIDGE_KEY)}${query}`;
  return result;
}

function enableBridgeOrigin() {
  vi.stubEnv("NODE_ENV", "development");
  vi.spyOn(window.location, "origin", "get").mockReturnValue(BRIDGE_ORIGIN);
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      expect(String(input)).toBe(`${BRIDGE_ORIGIN}/v1/dev-bridge/media`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("same-origin");
      expect(init?.redirect).toBe("error");
      expect(init?.cache).toBe("no-store");
      const { sources } = JSON.parse(String(init?.body)) as {
        sources: string[];
      };
      return Response.json({
        items: sources.map((_, index) => ({
          path: `/v1/dev-bridge/media/${String.fromCharCode(97 + index).repeat(43)}`,
          expires_at: NOW.getTime() + 120_000,
        })),
      });
    });
}

describe("post-validation native media transport", () => {
  it("maps video and captions while preserving HTTPS scope across reconnect and making no writes", async () => {
    enableBridgeOrigin();
    const activity = stagingFixture();
    const original = activity.media!.delivery!.progressive_url!;
    const captionKey = BRIDGE_KEY.replace(
      "lesson.mp4",
      "captions/en/caption-1",
    );
    const captionClaims = activityFixture({}, { key: captionKey });
    const captionQuery = new URL(
      captionClaims.media!.delivery!.progressive_url!,
    ).search;
    const captionSource = `${STAGING_ORIGIN}/v1/media/playback/${encodeURIComponent(captionKey)}${captionQuery}`;
    activity.media!.captions = [
      {
        id: "caption-1",
        language: "en",
        kind: "captions",
        state: "ready",
        source_url: captionSource,
        media_version_id: "media-version-1",
        content_type: "text/vtt",
        is_default: true,
        created_at: NOW.toISOString(),
      },
    ];
    const video = (await mount(activity, undefined, BRIDGE_ORIGIN))!;
    expect(video.src).toBe(
      `${BRIDGE_ORIGIN}/v1/dev-bridge/media/${"a".repeat(43)}`,
    );
    expect(container.querySelector("track")?.src).toBe(
      `${BRIDGE_ORIGIN}/v1/dev-bridge/media/${"b".repeat(43)}`,
    );
    expect(activity.media!.delivery!.progressive_url).toBe(original);
    expect(
      [...container.querySelectorAll("[src]")].every(
        (element) => !element.getAttribute("src")?.includes("token="),
      ),
    ).toBe(true);
    expect(approvedDeliveryExpiresAt(activity)).toBeGreaterThan(Date.now());
    await play();
    await connection(false);
    await connection(true);
    await play();
    const reconnectedVideo = container.querySelector("video")!;
    expect(reconnectedVideo).not.toBe(video);
    expect(reconnectedVideo.src).toBe(
      `${BRIDGE_ORIGIN}/v1/dev-bridge/media/${"a".repeat(43)}`,
    );
    expect(api.activity).toHaveBeenCalled();
    await fire(reconnectedVideo, "ended", 12);
    noWrites();
  });

  it("withholds invalid local transport without a remote fallback", async () => {
    enableBridgeOrigin();
    await mount(stagingFixture(), undefined, "http://localhost:3100");
    expect(container.querySelector("video")).toBeNull();
    expect(container.textContent).toContain("Video preview unavailable");
    expect(container.querySelector("[src]")).toBeNull();
    expect(container.querySelector("a")?.href).toBe(
      `${STAGING_ORIGIN}/activity/video-1`,
    );
    noWrites();
  });

  it("does not rescue an expired original descriptor by mapping its transport", async () => {
    enableBridgeOrigin();
    vi.setSystemTime(new Date(NOW.getTime() + 121_000));
    await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
    expect(container.querySelector("video")).toBeNull();
    noWrites();
  });

  it("preserves tracked completion using original descriptors, not rewritten scope", async () => {
    enableBridgeOrigin();
    const video = (await mount(
      stagingFixture(true),
      undefined,
      BRIDGE_ORIGIN,
    ))!;
    await play();
    expect(api.startPlayback).toHaveBeenCalledOnce();
    await fire(video, "timeupdate", 12);
    await fire(video, "ended", 12);
    expect(api.finishPlayback).toHaveBeenCalledOnce();
    expect(api.submitEvidence).toHaveBeenCalledOnce();
    expect(onCommitted).toHaveBeenCalledOnce();
  });

  it("does not rewrite production media even if a context value is present", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const activity = stagingFixture();
    const video = (await mount(activity, undefined, BRIDGE_ORIGIN))!;
    expect(video.src).toBe(activity.media!.delivery!.progressive_url);
    await play();
    noWrites();
  });

  it("withholds pending registration and never attaches a late source after the activity changes", async () => {
    const fetcher = enableBridgeOrigin();
    const pending = deferred<Response>();
    fetcher.mockImplementationOnce(async () => pending.promise);
    await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
    expect(container.querySelector("video")).toBeNull();
    expect(container.textContent).toContain("Preparing video preview");
    const signal = fetcher.mock.calls[0][1]?.signal;
    await mount(
      activityFixture({ id: "other-activity" }),
      undefined,
      BRIDGE_ORIGIN,
    );
    expect(signal?.aborted).toBe(true);
    await act(async () =>
      pending.resolve(
        Response.json({
          items: [
            {
              path: `/v1/dev-bridge/media/${"a".repeat(43)}`,
              expires_at: NOW.getTime() + 120_000,
            },
          ],
        }),
      ),
    );
    expect(container.querySelector("video")).toBeNull();
    noWrites();
  });

  it("stops a denied or expired registration without native src or canonical writes", async () => {
    const fetcher = enableBridgeOrigin();
    fetcher.mockResolvedValueOnce(new Response(null, { status: 401 }));
    await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
    expect(container.querySelector("[src]")).toBeNull();
    expect(container.textContent).toContain("Video preview unavailable");
    noWrites();
  });

  it("cancels an unmounted registration and rejects completion after original expiry", async () => {
    const fetcher = enableBridgeOrigin();
    const pending = deferred<Response>();
    fetcher.mockImplementationOnce(async () => pending.promise);
    await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
    const signal = fetcher.mock.calls[0][1]?.signal;
    await act(async () => root.unmount());
    unmounted = true;
    expect(signal?.aborted).toBe(true);
    vi.setSystemTime(new Date(NOW.getTime() + 121_000));
    await act(async () =>
      pending.resolve(
        Response.json({
          items: [
            {
              path: `/v1/dev-bridge/media/${"a".repeat(43)}`,
              expires_at: NOW.getTime() + 120_000,
            },
          ],
        }),
      ),
    );
    expect(container.querySelector("[src]")).toBeNull();
    noWrites();
  });

  it("survives StrictMode setup/cleanup without accepting the first late registration", async () => {
    const fetcher = enableBridgeOrigin();
    const pending = deferred<Response>();
    fetcher.mockImplementationOnce(async () => pending.promise);
    const activity = stagingFixture();
    await act(async () =>
      root.render(
        <StrictMode>
          <DevelopmentMediaBridgeProvider browserOrigin={BRIDGE_ORIGIN}>
            <VideoViewer
              activity={activity}
              api={api}
              moduleHref="/learn/module-1"
              onPlaybackCommitted={onCommitted}
            />
          </DevelopmentMediaBridgeProvider>
        </StrictMode>,
      ),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(container.querySelector("video")?.src).toBe(
      `${BRIDGE_ORIGIN}/v1/dev-bridge/media/${"a".repeat(43)}`,
    );
    await act(async () =>
      pending.resolve(
        Response.json({
          items: [
            {
              path: `/v1/dev-bridge/media/${"z".repeat(43)}`,
              expires_at: NOW.getTime() + 120_000,
            },
          ],
        }),
      ),
    );
    expect(container.querySelector("video")?.src).toBe(
      `${BRIDGE_ORIGIN}/v1/dev-bridge/media/${"a".repeat(43)}`,
    );
    noWrites();
  });

  it("removes native media when an established mapping expires", async () => {
    enableBridgeOrigin();
    await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
    expect(container.querySelector("video")).not.toBeNull();
    await act(async () => vi.advanceTimersByTimeAsync(120_001));
    expect(container.querySelector("[src]")).toBeNull();
    noWrites();
  });

  it.each([
    { items: [] },
    {
      items: [
        {
          path: "https://staging.authorityclosers.com/unsafe",
          expires_at: NOW.getTime() + 120_000,
        },
      ],
    },
    {
      items: [
        {
          path: `/v1/dev-bridge/media/${"a".repeat(43)}?token=fixture`,
          expires_at: NOW.getTime() + 120_000,
        },
      ],
    },
    {
      items: [
        {
          path: `/v1/dev-bridge/media/${"a".repeat(43)}`,
          expires_at: NOW.getTime() + 121_000,
        },
      ],
    },
    {
      items: [
        {
          path: `/v1/dev-bridge/media/${"a".repeat(43)}`,
          expires_at: NOW.getTime(),
        },
      ],
    },
  ])(
    "rejects invalid registration response shape or widened authority %#",
    async (payload) => {
      const fetcher = enableBridgeOrigin();
      fetcher.mockResolvedValueOnce(Response.json(payload));
      await mount(stagingFixture(), undefined, BRIDGE_ORIGIN);
      expect(container.querySelector("[src]")).toBeNull();
      expect(container.textContent).toContain("Video preview unavailable");
      noWrites();
    },
  );
});
function deferred<T>() {
  let resolve!: (result: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("mounted approved playback without completion policy", () => {
  it("retains its delivery source through StrictMode's effect cleanup replay", async () => {
    await act(async () =>
      root.render(
        <StrictMode>
          <VideoViewer
            activity={current}
            api={api}
            moduleHref="/learn/module-1"
          />
        </StrictMode>,
      ),
    );
    const video = container.querySelector("video")!;
    expect(video.getAttribute("src")).toBe(
      current.media!.delivery!.progressive_url,
    );
    await play();
    expect(video.paused).toBe(false);
    noWrites();
  });
  it.each(["available", "in_progress"])(
    "plays HLS-primary's validated MP4 fallback in %s without any learning writes",
    async (state) => {
      const video = (await mount(activityFixture({ state })))!;
      expect(video.src).not.toContain("m3u8");
      expect(
        container.querySelector('[data-playback-mode="read-only"]'),
      ).not.toBeNull();
      expect(container.textContent).toContain(
        "Playback only — progress is not recorded for this lesson.",
      );
      await play();
      expect(video.paused).toBe(false);
      await fire(video, "timeupdate", 6);
      await fire(video, "seeked", 10);
      await fire(video, "pause");
      await fire(video, "play"); // Native/fullscreen play, not just the custom button.
      await fire(video, "ended", 12);
      expect(container.textContent).toContain("Progress has not been recorded");
      expect(container.textContent).not.toContain("Processing watch evidence");
      await act(async () => root.unmount());
      unmounted = true;
      noWrites();
    },
  );

  it("refreshes reads on reconnect and media retry, without inventing a session", async () => {
    const video = (await mount())!;
    await play();
    await connection(false);
    expect(video.paused).toBe(true);
    await connection(true);
    expect(api.activity).toHaveBeenCalledTimes(1);
    await play();
    await fire(video, "error");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Retry media")!
        .click();
    });
    expect(api.activity).toHaveBeenCalledTimes(2);
    expect(container.textContent).not.toContain("Retry server save");
    noWrites();
  });

  it("uses native playing to recover buffering and does not mislabel fetch suspension", async () => {
    const video = (await mount())!;
    await play();
    await fire(video, "waiting");
    expect(
      container
        .querySelector("[data-media-state]")
        ?.getAttribute("data-media-state"),
    ).toBe("buffering");
    await fire(video, "playing");
    await fire(video, "suspend");
    expect(
      container
        .querySelector("[data-media-state]")
        ?.getAttribute("data-media-state"),
    ).toBe("playing");
    noWrites();
  });

  it.each([401, 403, 404])(
    "stops and drops buffered media on a %s reconnect denial",
    async (status) => {
      const video = (await mount())!;
      await play();
      api.activity = vi.fn(async () => {
        throw new ApiError(status, "Synthetic denied");
      });
      await connection(false);
      await connection(true);
      expect(video.paused).toBe(true);
      expect(video.getAttribute("src")).toBeNull();
      expect(container.querySelector("video")).toBeNull();
      expect(container.textContent).toContain("Reopen this lesson");
      noWrites();
    },
  );

  it("expires buffered read-only media and cannot replay via native events", async () => {
    const video = (await mount())!;
    await play();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(video.paused).toBe(true);
    expect(video.getAttribute("src")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
    expect(container.textContent).toContain("Reopen this lesson");
    await fire(video, "play");
    await fire(video, "ended", 12);
    noWrites();
  });

  it("does not promote a read-only mount when reconnect returns complete_video", async () => {
    await mount();
    await play();
    api.activity = vi.fn(async () =>
      activityFixture({ allowed_actions: ["complete_video"] }),
    );
    await connection(false);
    await connection(true);
    expect(container.querySelector("video")).toBeNull();
    noWrites();
  });

  it("ignores a stale reconnect response after newer enrollment replaces the player", async () => {
    const pending = deferred<ActivityResponse>();
    await mount();
    await connection(false);
    api.activity = vi.fn(() => pending.promise);
    await connection(true);
    const newer = activityFixture({ enrollment_id: "enrollment-2" });
    const newVideo = await mount(newer);
    await act(async () =>
      pending.resolve({
        ...activityFixture(),
        allowed_actions: ["complete_video"],
      }),
    );
    expect(container.querySelector("video")).toBe(newVideo);
    expect(
      container.querySelector('[data-playback-mode="read-only"]'),
    ).not.toBeNull();
    noWrites();
  });

  it.each(["locked", "completed", "blocked"])(
    "fails closed for %s even with an approved descriptor",
    async (state) => {
      expect(await mount(activityFixture({ state }))).toBeNull();
      noWrites();
    },
  );
  it("does not allow another activity kind or explicit local props to open playback", async () => {
    const explicit: AuthorizedVideoMedia = {
      protocol: "progressive",
      contentType: "video/mp4",
      src: "https://local.example.invalid/other.mp4",
    };
    expect(await mount({ ...baseActivity, media: null }, explicit)).toBeNull();
    expect(await mount(activityFixture({ kind: "reflection" }))).toBeNull();
    const approved = activityFixture();
    const video = await mount(approved, explicit);
    expect(video!.src).toBe(approved.media!.delivery!.progressive_url);
    expect(
      await mount(
        {
          ...approved,
          allowed_actions: ["complete_video"],
          media: {
            ...approved.media!,
            state: "blocked",
            playback_available: false,
          },
        },
        explicit,
      ),
    ).toBeNull();
    noWrites();
  });

  it.each([
    { exp: NOW.getTime() / 1000 },
    { exp: "later" },
    { exp: NOW.getTime() / 1000 + 3601 },
    { iat: NOW.getTime() / 1000 + 60 },
    { activity_id: "other-activity" },
    { asset_id: "other-asset" },
    { binding_id: "other-binding" },
    { enrollment_id: "other-enrollment" },
    { token_type: "upload" },
    { key: "other.mp4" },
  ])("rejects invalid delivery envelope metadata %#", async (claims) => {
    expect(await mount(activityFixture({}, claims))).toBeNull();
    noWrites();
  });

  it("rejects missing, manifest, and malformed progressive fallbacks", async () => {
    for (const source of [
      null,
      "https://learner.example.invalid/master.m3u8",
      "https://learner.example.invalid/master%2Em3u8",
      "javascript:alert(1)",
      "https://learner.example.invalid/v1/media/playback/lesson.mp4?token=invalid",
    ]) {
      const fixture = activityFixture();
      fixture.media!.delivery!.progressive_url = source;
      expect(await mount(fixture)).toBeNull();
    }
    expect(approvedDeliveryExpiresAt(activityFixture())).toBe(
      NOW.getTime() + 120_000,
    );
    expect(resolveApprovedMedia(activityFixture()).media?.protocol).toBe(
      "progressive",
    );
    noWrites();
  });
});

describe("existing server-tracked completion and mode races", () => {
  it("retains start, heartbeat, finish, refreshed revision and submit only for complete_video", async () => {
    const video = (await mount(
      activityFixture({ allowed_actions: ["complete_video"] }),
    ))!;
    await play();
    await fire(video, "timeupdate", 6);
    await fire(video, "ended", 12);
    expect(api.startPlayback).toHaveBeenCalledTimes(1);
    expect(api.heartbeatPlayback).toHaveBeenCalledTimes(2);
    expect(api.finishPlayback).toHaveBeenCalledTimes(1);
    expect(api.submitEvidence).toHaveBeenCalledWith(
      "video-1",
      "video_watch",
      {},
      4,
      "synthetic-session",
      "synthetic-token",
    );
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it.each(["read-only", "unmount"])(
    "drops a late tracked start after %s",
    async (target) => {
      const pending =
        deferred<Awaited<ReturnType<LearnerApi["startPlayback"]>>>();
      api.startPlayback = vi.fn(() => pending.promise);
      await mount(activityFixture({ allowed_actions: ["complete_video"] }));
      await play();
      if (target === "unmount") {
        await act(async () => root.unmount());
        unmounted = true;
      } else await mount(activityFixture());
      await act(async () =>
        pending.resolve({
          session_id: "late-session",
          session_token: "synthetic-token",
          revision: 1,
          activity_id: "video-1",
          expires_at: new Date(NOW.getTime() + 120_000).toISOString(),
          duration_seconds: 12,
        }),
      );
      expect(api.activity).not.toHaveBeenCalled();
      expect(api.heartbeatPlayback).not.toHaveBeenCalled();
      expect(api.finishPlayback).not.toHaveBeenCalled();
      expect(api.submitEvidence).not.toHaveBeenCalled();
    },
  );

  it("cannot submit evidence after a tracked finish resolves into a read-only context", async () => {
    const pending =
      deferred<Awaited<ReturnType<LearnerApi["finishPlayback"]>>>();
    api.finishPlayback = vi.fn(() => pending.promise);
    const video = (await mount(
      activityFixture({ allowed_actions: ["complete_video"] }),
    ))!;
    await play();
    await fire(video, "ended", 12);
    expect(api.finishPlayback).toHaveBeenCalledTimes(1);
    await mount(activityFixture());
    await act(async () =>
      pending.resolve({
        session_id: "synthetic-session",
        revision: 4,
        activity_id: "video-1",
        status: "closed",
        closed_at: NOW.toISOString(),
      }),
    );
    expect(api.submitEvidence).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
  });

  it("does not submit when the final authoritative refresh removes complete_video", async () => {
    const video = (await mount(
      activityFixture({ allowed_actions: ["complete_video"] }),
    ))!;
    await play();
    api.activity = vi.fn(async () => activityFixture());
    await fire(video, "ended", 12);
    expect(api.finishPlayback).toHaveBeenCalledTimes(1);
    expect(api.submitEvidence).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Reopen this lesson");
  });
});
