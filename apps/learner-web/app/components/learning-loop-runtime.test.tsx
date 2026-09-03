import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ActivityResponse } from "../lib/learner-api";
import {
  canStartPlayback,
  formatMediaTime,
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

  it("renders an honest unavailable state when no authorized media descriptor exists", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        onPlaybackCommitted: vi.fn(),
      }),
    );

    expect(html).toContain("No approved lesson media is connected yet.");
    expect(html).toContain("The server exposes a completion action");
    expect(html).toContain(
      "Watch evidence cannot be submitted while media is unavailable",
    );
    expect(html).not.toContain("<video");
    expect(html).not.toContain("Mastery");
    expect(html).not.toContain("Complete");
  });

  it("renders media only from the explicit authorized descriptor", () => {
    const html = renderToStaticMarkup(
      createElement(VideoViewer, {
        activity,
        api,
        moduleHref: "/learn/module-1",
        media: {
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
