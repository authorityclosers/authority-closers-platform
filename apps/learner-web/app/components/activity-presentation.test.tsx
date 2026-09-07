// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ActivityResponse, LearnerApi } from "../lib/learner-api";
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
let root: Root | undefined;
let container: HTMLDivElement | undefined;

afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
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

  it("keeps a reflection prompt before its response editor", () => {
    const html = renderToStaticMarkup(
      <ConnectedActivityWorkspace
        activity={{
          ...activity,
          kind: "REFLECTION",
          allowed_actions: ["save_draft"],
        }}
        api={api}
      />,
    );
    expect(html.indexOf(activity.prompt!)).toBeLessThan(
      html.indexOf("<textarea"),
    );
    expect(html).toContain("Save reflection");
    expect(html).not.toContain("About this lesson");
  });

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
