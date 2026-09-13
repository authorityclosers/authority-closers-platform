import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ActivityResponse } from "../lib/learner-api";
import {
  BlockedMediaStage,
  canStartPlayback,
  CaptionsTranscriptPanel,
  formatMediaTime,
  isApprovedProgressiveMediaSource,
  isInteractiveShortcutTarget,
  isPlaybackConnectionCurrent,
  normalizePlaybackRates,
  normalizeQualityOptions,
  PlaybackSettingsPanel,
  resolveApprovedMedia,
  supportsPlayerFullscreen,
  VideoKeyboardShortcutsDialog,
  VideoViewer,
} from "./learning-loop-runtime";

const activity: ActivityResponse = {
  id: "activity-video",
  module_id: "module-1",
  program_version_id: "version-1",
  position: 1,
  kind: "video",
  title: "Make the next conversation clearer",
  prompt: null,
  state: "available",
  revision: 4,
  required: true,
  explanation: {
    activity_id: "activity-video",
    state: "available",
    required: true,
    reason: "server_resolved_activity_state",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
  allowed_actions: ["complete_video"],
  program_id: "program-1",
  enrollment_id: "enrollment-1",
  draft_revision: 0,
  draft_payload: null,
};

const api = {} as never;

const approvedActivityWithMedia: ActivityResponse = {
  ...activity,
  media: {
    state: "approved",
    reason: "Approved for standard curriculum playback.",
    binding_id: "bind-video-001",
    media_id: "med-video-001",
    media_version_id: "ver-1",
    activity_version: "4",
    content_type: "video/mp4",
    duration_seconds: 145,
    width: 1920,
    height: 1080,
    renditions: [
      {
        id: "rend-1",
        protocol: "progressive",
        content_type: "video/mp4",
        width: 1920,
        height: 1080,
        bitrate_kbps: 2400,
      },
    ],
    captions: [
      {
        id: "cap-en",
        media_version_id: "ver-1",
        language: "en",
        kind: "captions",
        state: "ready",
        content_type: "text/vtt",
        is_default: true,
        source_url: "https://media.example.test/approved-captions.vtt",
        created_at: "2026-03-01T00:00:00Z",
      },
      {
        id: "cap-old",
        media_version_id: "ver-1",
        language: "en",
        kind: "captions",
        state: "retired",
        content_type: "text/vtt",
        is_default: false,
        source_url: "https://media.example.test/old-captions.vtt",
        created_at: "2026-02-01T00:00:00Z",
      },
    ],
    delivery: {
      protocol: "progressive",
      manifest_url: null,
      progressive_url: "https://media.example.test/approved-lesson.mp4",
    },
    provenance: {
      label: "Technical playback test — not course instruction",
      title: "Big Buck Bunny — Sunflower",
      attribution:
        "Blender Foundation 2008, Janus Bager Kristensen 2013; Big Buck Bunny, Sunflower version",
      license: "Creative Commons Attribution 3.0",
      license_url: "https://creativecommons.org/licenses/by/3.0/",
    },
    playback_available: true,
  },
};

const blockedActivity: ActivityResponse = {
  ...activity,
  media: {
    state: "blocked",
    reason: "Lesson media blocked by licensing and compliance policy.",
    binding_id: "bind-video-002",
    media_id: "med-video-002",
    media_version_id: "ver-2",
    activity_version: "4",
    content_type: "video/mp4",
    duration_seconds: 200,
    width: 1920,
    height: 1080,
    renditions: [],
    captions: [],
    delivery: null,
    playback_available: false,
  },
};

describe("learning loop video runtime", () => {
  it("formats the player clock without inventing progress", () => {
    expect(formatMediaTime(0)).toBe("0:00");
    expect(formatMediaTime(65.9)).toBe("1:05");
    expect(formatMediaTime(Number.NaN)).toBe("0:00");
  });

  it("requires the server action and a writable activity state before playback", () => {
    expect(canStartPlayback(activity)).toBe(true);
    expect(canStartPlayback({ ...activity, allowed_actions: [] })).toBe(false);
    expect(canStartPlayback({ ...activity, state: "locked" })).toBe(false);
  });

  it("guards canonical writes across offline and reconnect epochs", () => {
    expect(isPlaybackConnectionCurrent(4, 4, true, false)).toBe(true);
    expect(isPlaybackConnectionCurrent(4, 5, true, false)).toBe(false);
    expect(isPlaybackConnectionCurrent(4, 4, false, false)).toBe(false);
    expect(isPlaybackConnectionCurrent(4, 4, true, true)).toBe(false);
    expect(isPlaybackConnectionCurrent(5, 4, true, false)).toBe(false);
  });

  it("does not hijack keyboard shortcuts from interactive targets", () => {
    const buttonTarget = {
      closest: (selector: string) =>
        selector.includes("button") ? ({} as Element) : null,
    } as unknown as EventTarget;
    const contentEditableTarget = {
      closest: () => null,
      isContentEditable: true,
    } as unknown as EventTarget;
    const playerRegionTarget = {
      closest: () => null,
    } as unknown as EventTarget;

    expect(isInteractiveShortcutTarget(buttonTarget)).toBe(true);
    expect(isInteractiveShortcutTarget(contentEditableTarget)).toBe(true);
    expect(isInteractiveShortcutTarget(playerRegionTarget)).toBe(false);
  });

  it("uses the player container as the fullscreen target", () => {
    const player = { requestFullscreen: vi.fn() } as unknown as HTMLElement;
    expect(supportsPlayerFullscreen(player)).toBe(true);
    expect(supportsPlayerFullscreen(null)).toBe(false);

    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        media: {
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.example.test/lesson.mp4",
        },
      }),
    );
    expect(html).toContain('data-fullscreen-target="player"');
  });

  it("requires explicit progressive video sources for media and quality", () => {
    expect(
      isApprovedProgressiveMediaSource({
        protocol: "progressive",
        contentType: "video/mp4",
        src: "https://media.test/lesson.mp4",
      }),
    ).toBe(true);
    expect(
      isApprovedProgressiveMediaSource({
        protocol: "progressive",
        contentType: "video/mp4",
        src: "https://media.test/lesson.m3u8",
      }),
    ).toBe(false);
    expect(
      isApprovedProgressiveMediaSource({
        protocol: "progressive",
        contentType: "video/mp4",
        src: "https://media.test/lesson.mp4?format=m3u8",
      }),
    ).toBe(false);
    expect(
      isApprovedProgressiveMediaSource({
        protocol: "hls" as unknown as "progressive",
        contentType: "application/vnd.apple.mpegurl",
        src: "https://media.test/lesson.m3u8",
      }),
    ).toBe(false);

    const rejected = resolveApprovedMedia(activity, {
      protocol: "progressive",
      contentType: "application/vnd.apple.mpegurl",
      src: "https://media.test/manifest.m3u8",
    });
    expect(rejected.state).toBe("unavailable");
    expect(rejected.media).toBeNull();
    expect(rejected.reason).toContain("video/mp4 or video/webm");
  });

  it("resolves approved media descriptors safely", () => {
    const explicit = {
      protocol: "progressive" as const,
      contentType: "video/mp4",
      src: "https://explicit.example.test/video.mp4",
    };
    const resolvedExplicit = resolveApprovedMedia(activity, explicit);
    expect(resolvedExplicit.state).toBe("approved");
    expect(resolvedExplicit.media?.src).toBe(
      "https://explicit.example.test/video.mp4",
    );

    const resolvedUnavail = resolveApprovedMedia(activity);
    expect(resolvedUnavail.state).toBe("unavailable");
    expect(resolvedUnavail.media).toBeNull();

    const resolvedBlocked = resolveApprovedMedia(blockedActivity);
    expect(resolvedBlocked.state).toBe("blocked");
    expect(resolvedBlocked.media).toBeNull();
    expect(resolvedBlocked.reason).toContain("licensing and compliance policy");

    const resolvedApproved = resolveApprovedMedia(approvedActivityWithMedia);
    expect(resolvedApproved.state).toBe("approved");
    expect(resolvedApproved.media?.src).toBe(
      "https://media.example.test/approved-lesson.mp4",
    );
    expect(resolvedApproved.media?.captions).toHaveLength(1);
    expect(resolvedApproved.media?.captions?.[0].src).toBe(
      "https://media.example.test/approved-captions.vtt",
    );
  });

  it("renders the server-owned technical playback disclosure beside the player", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: approvedActivityWithMedia,
        api,
        moduleHref: "/learn/module-1",
      }),
    );
    expect(html).toContain("Technical playback test — not course instruction");
    expect(html).toContain("Big Buck Bunny — Sunflower");
    expect(html).toContain(
      "Blender Foundation 2008, Janus Bager Kristensen 2013; Big Buck Bunny, Sunflower version",
    );
    expect(html).toContain(
      'href="https://creativecommons.org/licenses/by/3.0/"',
    );
    expect(html.indexOf("momentum-video-viewer__provenance")).toBeLessThan(
      html.indexOf("momentum-video-player"),
    );
  });

  it("keeps playback settings capability-driven", () => {
    expect(normalizePlaybackRates([1.5, 1, 1.5, Number.NaN, -1])).toEqual([
      1, 1.5,
    ]);
    expect(normalizePlaybackRates()).toEqual([]);
    expect(
      normalizeQualityOptions([
        {
          id: "720",
          label: "720p",
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.test/720.mp4",
        },
        {
          id: "720",
          label: "Duplicate",
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.test/dup.mp4",
        },
        {
          id: "",
          label: "Missing id",
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.test/missing.mp4",
        },
      ]),
    ).toEqual([
      {
        id: "720",
        label: "720p",
        protocol: "progressive",
        contentType: "video/mp4",
        src: "https://media.test/720.mp4",
      },
    ]);

    const withoutCapabilities = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        media: {
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.example.test/lesson.mp4",
        },
      }),
    );
    expect(withoutCapabilities).not.toContain("Playback settings");
    expect(withoutCapabilities).not.toContain("Playback speed");
    expect(withoutCapabilities).not.toContain("Video quality");

    const withCapabilities = renderToStaticMarkup(
      createElement(PlaybackSettingsPanel, {
        playbackRates: [1, 1.25],
        playbackRate: 1,
        onChangeRate: vi.fn(),
        qualities: [
          {
            id: "720",
            label: "720p",
            protocol: "progressive",
            contentType: "video/mp4",
            src: "https://media.test/720.mp4",
          },
        ],
        qualityId: "auto",
        onChangeQuality: vi.fn(),
        onClose: vi.fn(),
      }),
    );
    expect(withCapabilities).toContain("Playback settings");
    expect(withCapabilities).toContain("Playback speed");
    expect(withCapabilities).toContain("Video quality");
    expect(withCapabilities).toContain("720p");
    expect(withCapabilities).toContain(
      "Choose the picture quality and pace that suit you.",
    );
  });

  it("does not activate a manifest-only delivery path", () => {
    const hlsOnlyActivity: ActivityResponse = {
      ...approvedActivityWithMedia,
      media: {
        ...approvedActivityWithMedia.media!,
        delivery: {
          protocol: "hls",
          manifest_url: "https://media.example.test/lesson.m3u8",
          progressive_url: null,
        },
      },
    };
    const resolved = resolveApprovedMedia(hlsOnlyActivity);
    expect(resolved.state).toBe("unavailable");
    expect(resolved.media).toBeNull();
    expect(resolved.reason).toContain("progressive media delivery");

    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: hlsOnlyActivity,
        api,
        moduleHref: "/learn/module-1",
      }),
    );
    expect(html).not.toContain("<video");
    expect(html).toContain("This video isn’t available yet");
    expect(html).not.toContain("No approved progressive media delivery");
  });

  it("renders an honest unavailable state when no authorized media descriptor exists", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        onPlaybackCommitted: vi.fn(),
      }),
    );

    expect(html).toContain("This video isn’t available yet");
    expect(html).toContain(
      "This lesson stays incomplete until you can watch it.",
    );
    expect(html).not.toContain("The server exposes a completion action");
    expect(html).not.toContain("<video");
    expect(html).not.toContain("Mastery");
    expect(html).not.toContain("Complete");
  });

  it("uses the containing lesson heading and never prints backend reason codes", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: {
          ...activity,
          media: {
            ...blockedActivity.media!,
            state: "unavailable",
            playback_available: false,
            reason: "approved_activity_media_binding_unavailable",
          },
        },
        api,
        moduleHref: "/learn/module-1",
        labelledBy: "activity-heading",
      }),
    );
    expect(html).toContain('aria-labelledby="activity-heading"');
    expect(html).not.toContain(activity.title);
    expect(html).not.toContain("approved_activity_media_binding_unavailable");
    expect(html).not.toContain("Server-resolved");
    expect(html).toContain('href="/learn/module-1"');
  });

  it("renders media only from the explicit authorized descriptor", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        media: {
          protocol: "progressive",
          contentType: "video/mp4",
          src: "https://media.example.test/lesson.mp4",
          captions: [
            {
              src: "https://media.example.test/lesson.vtt",
              srclang: "en",
              label: "English",
              default: true,
            },
          ],
          transcript: [{ start: 0, end: 4, text: "Start with the outcome." }],
        },
      }),
    );

    expect(html).toContain("<video");
    expect(html).toContain('src="https://media.example.test/lesson.mp4"');
    expect(html).toContain('kind="captions"');
    expect(html).toContain("Open transcript");
    expect(html).toContain('role="group" aria-label="Video controls"');
    expect(html).toContain('data-media-state="loading"');
    expect(html).toContain('aria-keyshortcuts="k Space"');
  });

  it("renders media automatically from an approved activity media descriptor", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: approvedActivityWithMedia,
        api,
        moduleHref: "/learn/module-1",
      }),
    );

    expect(html).toContain("<video");
    expect(html).toContain(
      'src="https://media.example.test/approved-lesson.mp4"',
    );
    expect(html).toContain('kind="captions"');
    expect(html).toContain(
      'src="https://media.example.test/approved-captions.vtt"',
    );
    expect(html).toContain('role="group" aria-label="Video controls"');
    expect(html).toContain("Skip back 10 seconds");
    expect(html).toContain("Skip forward 10 seconds");
  });

  it("fails closed when activity media descriptor is blocked by policy", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: blockedActivity,
        api,
        moduleHref: "/learn/module-1",
      }),
    );

    expect(html).toContain("This video can’t be played right now");
    expect(html).not.toContain("Media policy blocked");
    expect(html).toContain(
      "Watching and completion are unavailable for this video.",
    );
    expect(html).not.toContain(
      "Lesson media blocked by licensing and compliance policy.",
    );
    expect(html).not.toContain("<video");
  });

  it("renders BlockedMediaStage with honest messaging and return link", () => {
    const html = renderToStaticMarkup(
      createElement(BlockedMediaStage, {
        activity: blockedActivity,
        moduleHref: "/learn/module-1",
        reason: "Content distribution revoked.",
      }),
    );

    expect(html).toContain("This video can’t be played right now");
    expect(html).not.toContain("Content distribution revoked.");
    expect(html).toContain('href="/learn/module-1"');
  });

  it("renders interactive transcript panel with search, cue seeking, and active state", () => {
    const html = renderToStaticMarkup(
      createElement(CaptionsTranscriptPanel, {
        transcript: [
          { start: 0, end: 5, text: "Welcome to high-stakes closing." },
          {
            start: 5,
            end: 12,
            text: "Focus entirely on diagnostic discovery.",
          },
        ],
        currentTime: 7,
        onSeek: vi.fn(),
        captionsEnabled: true,
        onToggleCaptions: vi.fn(),
        isOpen: true,
        onToggleOpen: vi.fn(),
      }),
    );

    expect(html).toContain("Open transcript");
    expect(html).toContain("Welcome to high-stakes closing.");
    expect(html).toContain("Focus entirely on diagnostic discovery.");
    expect(html).toContain('aria-current="time"');
    expect(html).toContain('placeholder="Search transcript…"');
  });

  it("renders an explicit unavailable captions/transcript state", () => {
    const html = renderToStaticMarkup(
      createElement(CaptionsTranscriptPanel, {
        transcript: [],
        captions: [],
        currentTime: 0,
        onSeek: vi.fn(),
        captionsEnabled: false,
        onToggleCaptions: vi.fn(),
        isOpen: true,
        onToggleOpen: vi.fn(),
      }),
    );

    expect(html).toContain("Captions &amp; transcript");
    expect(html).toContain("Transcript is not available for this lesson.");
    expect(html).toContain(
      "Captions and transcript are not available for this lesson yet.",
    );
  });

  it("renders keyboard shortcuts guide with standard video navigation keys", () => {
    const html = renderToStaticMarkup(
      createElement(VideoKeyboardShortcutsDialog, {
        isOpen: true,
        onClose: vi.fn(),
      }),
    );

    expect(html).toContain("Keyboard shortcuts");
    expect(html).toContain("Space / K");
    expect(html).toContain("Play or pause lesson");
    expect(html).toContain("Seek backward / forward 5 seconds");
    expect(html).toContain("Skip backward / forward 10 seconds");
  });

  it("preserves the server-resolved completed state after media is no longer playable", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity: { ...activity, state: "completed", allowed_actions: [] },
        api,
        moduleHref: "/learn/module-1",
      }),
    );

    expect(html).toContain("Lesson complete.");
    expect(html).toContain("accepted the completion evidence");
    expect(html).not.toContain(
      "Watch evidence cannot be submitted while media is unavailable",
    );
    expect(html).not.toContain("No approved lesson media is connected yet.");
  });
});
