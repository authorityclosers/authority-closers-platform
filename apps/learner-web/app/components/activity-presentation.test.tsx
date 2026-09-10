// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
  type LearningResponse,
} from "../lib/learner-api";
import { ConnectedActivityWorkspace } from "./learner-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const activity: ActivityResponse = {
  id: "presentation-video",
  module_id: "presentation-module",
  program_id: "presentation-program",
  enrollment_id: "presentation-enrollment",
  program_version_id: "presentation-version",
  position: 1,
  kind: "VIDEO",
  title: "Make your next conversation count",
  prompt: "Observe how the conversation begins.",
  state: "available",
  revision: 1,
  required: true,
  allowed_actions: [],
  draft_revision: 0,
  draft_payload: null,
  explanation: {
    activity_id: "presentation-video",
    state: "available",
    required: true,
    reason: "fixture_only",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
};
const api = {} as LearnerApi;
const NOW = new Date("2026-09-09T12:00:00Z");

function approvedVideo(title = activity.title): ActivityResponse {
  const key = "synthetic/presentation-lesson.mp4";
  // Synthetic envelope only, as in the playback interaction suite. The real
  // resolver checks its metadata; this fixture makes no authentication claim.
  const claims = {
    typ: "AC-MEDIA",
    token_type: "playback",
    iat: NOW.getTime() / 1000,
    exp: NOW.getTime() / 1000 + 120,
    activity_id: activity.id,
    activity_version: "published-presentation-1",
    asset_id: "presentation-asset",
    version_id: "presentation-media-version",
    binding_id: "presentation-binding",
    enrollment_id: activity.enrollment_id,
    delivery_grant_id: "synthetic-presentation-grant",
    key,
  };
  const token = `AC-MEDIA.${btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.${"a".repeat(43)}`;
  return {
    ...activity,
    title,
    media: {
      state: "approved",
      reason: "approved_media_delivery_available",
      binding_id: "presentation-binding",
      media_id: "presentation-asset",
      media_version_id: "presentation-media-version",
      activity_version: "published-presentation-1",
      content_type: "video/mp4",
      duration_seconds: 120,
      width: 1920,
      height: 1080,
      renditions: [],
      captions: [],
      playback_available: true,
      delivery: {
        protocol: "progressive",
        manifest_url: null,
        progressive_url: `https://learner.example.invalid/v1/media/playback/${encodeURIComponent(key)}?token=${token}`,
      },
    },
  };
}

function learningFixture(current: ActivityResponse): LearningResponse {
  return {
    program_id: current.program_id,
    program_version_id: current.program_version_id,
    program_slug: "presentation-course",
    program_title: "Synthetic presentation course",
    version_number: 1,
    enrollment_id: current.enrollment_id,
    modules: [
      {
        id: current.module_id,
        position: 1,
        title: "Synthetic conversation module",
        activities: [
          current,
          {
            ...activity,
            id: "presentation-sibling",
            position: 2,
            kind: "REFLECTION",
            title: "Synthetic sibling response",
            explanation: {
              ...activity.explanation,
              activity_id: "presentation-sibling",
            },
          },
        ],
      },
    ],
    projection: {
      scope_type: "program",
      scope_id: current.program_id,
      program_version: current.program_version_id,
      projection_version: "presentation-projection-1",
      denominator: 2,
      completed_count: 0,
      percentage: 0,
      predicate: "required_activities_complete",
      missing_module_ids: [],
      activity_reasons: [],
    },
  };
}

function expectBefore(first: Element, second: Element) {
  expect(
    first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
}

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("activity presentation", () => {
  it("renders one video title and places authored lesson notes after the player", () => {
    const html = renderToStaticMarkup(
      <ConnectedActivityWorkspace activity={activity} api={api} />,
    );
    expect(html.split(activity.title)).toHaveLength(2);
    expect(html).toContain('id="activity-title-presentation-video"');
    expect(html).toContain(
      'aria-labelledby="activity-title-presentation-video"',
    );
    expect(html.indexOf("lesson-media-notice")).toBeLessThan(
      html.indexOf("About this lesson"),
    );
    expect(html).toContain(activity.prompt);
    expect(html).not.toContain(
      "Learner evidence — not an autonomous evaluation.",
    );
    expect(html).not.toContain("Server-resolved");
    expect(html).not.toContain("<textarea");
  });

  it("keeps the reflection prompt, module disclosure, and response editor in order", () => {
    const rendered = document.createElement("div");
    rendered.innerHTML = renderToStaticMarkup(
      <ConnectedActivityWorkspace
        activity={{
          ...activity,
          kind: "REFLECTION",
          allowed_actions: ["save_draft"],
        }}
        api={api}
      />,
    );
    const prompt = rendered.querySelector(".activity-prompt")!;
    const path = rendered.querySelector<HTMLDetailsElement>(
      ".activity-mobile-path",
    )!;
    const editor = rendered.querySelector("textarea")!;
    expect(prompt.textContent).toContain(activity.prompt);
    expectBefore(prompt, path);
    expectBefore(path, editor);
    expect(path.open).toBe(false);
    expect(rendered.textContent).toContain("Save reflection");
    expect(rendered.textContent).not.toContain("About this lesson");
  });

  it("places one fully labelled video heading before the picture and its closed module path", () => {
    const current = approvedVideo();
    const rendered = document.createElement("div");
    rendered.innerHTML = renderToStaticMarkup(
      <ConnectedActivityWorkspace
        activity={current}
        learning={learningFixture(current)}
        learningPathStatus="ready"
        api={api}
      />,
    );
    const title = rendered.querySelector("h1")!;
    const video = rendered.querySelector("video")!;
    const viewer = video.closest("section")!;
    const path = rendered.querySelector<HTMLDetailsElement>(
      ".activity-mobile-path",
    )!;
    const previewNote = viewer.querySelector('[role="note"]')!;
    expect(rendered.querySelectorAll("h1")).toHaveLength(1);
    expect(title.textContent).toBe(current.title);
    expect(viewer.getAttribute("aria-labelledby")).toBe(title.id);
    expect(video.getAttribute("aria-label")).toBe(current.title);
    expect(video.getAttribute("src")).toBe(
      current.media!.delivery!.progressive_url,
    );
    expect(
      video.closest("[data-playback-mode]")?.getAttribute("data-playback-mode"),
    ).toBe("read-only");
    expectBefore(title, video);
    expectBefore(video, previewNote);
    expectBefore(video, path);
    expectBefore(path, rendered.querySelector(".lesson-context")!);
    expect(path.open).toBe(false);
    expect(path.querySelector("summary")?.textContent).toContain("1 of 2");
    expect(previewNote.textContent).toContain(
      "Watching here won’t change your course progress.",
    );
  });

  it("retains the complete long lesson title in the heading and player labels", () => {
    const title =
      "Build trust throughout a challenging sales conversation by listening carefully, responding with clarity, and agreeing on the next meaningful step together";
    const current = approvedVideo(title);
    const rendered = document.createElement("div");
    rendered.innerHTML = renderToStaticMarkup(
      <ConnectedActivityWorkspace activity={current} api={api} />,
    );
    expect(rendered.querySelectorAll("h1")).toHaveLength(1);
    expect(rendered.querySelector("h1")?.textContent).toBe(title);
    expect(rendered.querySelector("video")?.getAttribute("aria-label")).toBe(
      title,
    );
    expect(
      rendered.querySelector('[role="region"]')?.getAttribute("aria-label"),
    ).toBe(`Video player for ${title}`);
  });

  it("opens and closes the module path without replacing or restarting the video or writing progress", async () => {
    const current = approvedVideo();
    const playbackApi = {
      activity: vi.fn(async () => current),
      startPlayback: vi.fn(),
      heartbeatPlayback: vi.fn(),
      finishPlayback: vi.fn(),
      submitEvidence: vi.fn(),
      saveDraft: vi.fn(),
    };
    const onMutationCommitted = vi.fn();
    const load = vi
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => undefined);
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConnectedActivityWorkspace
          activity={current}
          learning={learningFixture(current)}
          learningPathStatus="ready"
          api={playbackApi as unknown as LearnerApi}
          onMutationCommitted={onMutationCommitted}
        />,
      );
    });
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 120,
    });
    Object.defineProperty(video, "readyState", {
      configurable: true,
      value: 4,
    });
    await act(async () => {
      video.dispatchEvent(new Event("loadedmetadata"));
      video.currentTime = 37;
      video.playbackRate = 1.5;
      video.dispatchEvent(new Event("timeupdate"));
    });
    const source = video.src;
    const loadsBeforeToggle = load.mock.calls.length;
    const path = container.querySelector<HTMLDetailsElement>(
      ".activity-mobile-path",
    )!;
    const summary = path.querySelector("summary")!;
    expect(path.open).toBe(false);
    for (const open of [true, false, true, false]) {
      await act(async () => summary.click());
      expect(path.open).toBe(open);
      expect(container.querySelector("video")).toBe(video);
      expect(video.src).toBe(source);
      expect(video.currentTime).toBe(37);
      expect(video.playbackRate).toBe(1.5);
      expect(load).toHaveBeenCalledTimes(loadsBeforeToggle);
      expect(play).not.toHaveBeenCalled();
      for (const method of Object.values(playbackApi)) {
        expect(method).not.toHaveBeenCalled();
      }
      expect(onMutationCommitted).not.toHaveBeenCalled();
    }
  });

  it.each([
    ["error", 503, "The module path could not refresh."],
    ["forbidden", 403, "This account cannot open the complete module path."],
  ] as const)(
    "keeps the %s path truthful and omits siblings from the stale learning response",
    (learningPathStatus, status, message) => {
      const current = approvedVideo();
      const rendered = document.createElement("div");
      rendered.innerHTML = renderToStaticMarkup(
        <ConnectedActivityWorkspace
          activity={current}
          learning={learningFixture(current)}
          learningPathStatus={learningPathStatus}
          learningPathError={
            new ApiError(status, "Synthetic module path failure")
          }
          onRetryLearningPath={vi.fn()}
          api={api}
        />,
      );
      const path = rendered.querySelector<HTMLDetailsElement>(
        ".activity-mobile-path",
      )!;
      expectBefore(rendered.querySelector("video")!, path);
      expect(path.open).toBe(false);
      expect(rendered.textContent).toContain(message);
      expect(path.querySelector("summary")?.textContent).toContain("Step 1");
      expect(path.querySelector("summary")?.textContent).not.toContain("of 2");
      expect(path.querySelectorAll(".activity-loop__step")).toHaveLength(1);
      expect(path.querySelector('[role="alert"]')?.textContent).toContain(
        learningPathStatus === "forbidden"
          ? "This account is not permitted to use this learner action."
          : "The learning service could not complete this request. Try again.",
      );
      expect(rendered.textContent).not.toContain("Synthetic sibling response");
      expect(
        rendered.querySelector('a[href*="presentation-sibling"]'),
      ).toBeNull();
      expect(rendered.textContent).not.toContain(
        "Synthetic conversation module",
      );
      expect(path.textContent).toContain(
        learningPathStatus === "forbidden"
          ? "Contact learner support"
          : "Retry module path",
      );
    },
  );

  it("discloses device-storage trouble without dominating a video with no response", async () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("synthetic blocked storage");
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConnectedActivityWorkspace
          activity={activity}
          api={api}
          personId="presentation-person"
          tenantId="presentation-tenant"
        />,
      );
    });
    const storageSummary = [...container.querySelectorAll("summary")].find(
      (element) => element.textContent === "Device storage notice",
    );
    expect(storageSummary).toBeDefined();
    expect(storageSummary?.parentElement?.tagName).toBe("DETAILS");
    expect(storageSummary?.parentElement?.hasAttribute("open")).toBe(false);
    expect(storageSummary?.parentElement?.textContent).toContain(
      "could not verify",
    );
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
