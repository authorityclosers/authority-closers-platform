import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceAccessValue } from "../workspace-access";
import { CoachingPage, CoachingSkeleton, CoachingStory } from "./coaching-page";
import {
  fictionalCallCoaching,
  fictionalClip,
  fictionalCoaching,
} from "./coaching.fixture";
import { CallCoachingStory } from "./call-coaching";
import { requestedSkill } from "./focus-request";

const mocks = vi.hoisted(() => ({
  access: null as WorkspaceAccessValue | null,
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => mocks.access,
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: React.ReactNode }) => (
    <main>{children}</main>
  ),
}));
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mocks.access = null;
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
describe("Coaching story", () => {
  it("does not reuse a server result from a different session of the same person", async () => {
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCallCoaching.person_id,
        tenantId: fictionalCallCoaching.tenant_id,
        sessionId: "00000000-0000-0000-0000-000000000071",
      },
      retry: vi.fn(),
    };
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("private diagnostic", { status: 403 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <CoachingPage
          callId={fictionalCallCoaching.submission_id}
          initialResult={{
            data: {
              ...fictionalCallCoaching,
              session_id: "00000000-0000-0000-0000-000000000072",
            },
            error: null,
          }}
        />,
      ),
    );
    expect(host.textContent).not.toContain("Ask one impact question.");
    expect(fetch).toHaveBeenCalledOnce();
  });
  it("does not turn an invalid call's retry into a My coaching read", async () => {
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCallCoaching.person_id,
        tenantId: fictionalCallCoaching.tenant_id,
        sessionId: "session-a",
      },
      retry: vi.fn(),
    };
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <CoachingPage
          invalidCall
          initialResult={{ data: null, error: "This call link is invalid." }}
        />,
      ),
    );
    const retry = [...host.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Try again"),
    )!;
    await act(async () => retry.click());
    expect(fetch).not.toHaveBeenCalled();
    expect(host.textContent).toContain("This call link is invalid.");
  });
  it("renders a single call's four pillars with no invented pattern or mastery gate", () => {
    const html = renderToStaticMarkup(
      <CallCoachingStory coaching={fictionalCallCoaching} />,
    );
    expect(html).toContain("One focus for this call");
    expect(html).toContain("Why this is the focus for this call");
    expect(html).toContain("Here’s What Better Looks Like");
    expect(html).toContain("Try This on Your Next Call");
    expect(html.match(/Active mission/g)).toHaveLength(1);
    expect(html).not.toContain("Not Enough Evidence");
    expect(html).not.toContain("Compare one more evidence moment");
    expect(html).not.toContain("<audio");
  });
  it("server data renders before account bootstrap and hydration does not fetch twice", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const props = {
      callId: fictionalCallCoaching.submission_id,
      initialResult: { data: fictionalCallCoaching, error: null } as const,
    };
    await act(async () => root.render(<CoachingPage {...props} />));
    expect(host.textContent).toContain("Ask one impact question.");
    expect(host.querySelector('[aria-busy="true"]')).toBeNull();
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCallCoaching.person_id,
        tenantId: fictionalCallCoaching.tenant_id,
        sessionId: "session-a",
      },
      retry: vi.fn(),
    };
    await act(async () => root.render(<CoachingPage {...props} />));
    expect(host.textContent).toContain("Ask one impact question.");
    expect(fetch).not.toHaveBeenCalled();
    mocks.access = {
      ...mocks.access,
      context: { ...mocks.access.context!, sessionId: "session-b" },
    };
    fetch.mockResolvedValue(new Response("private error", { status: 403 }));
    await act(async () => root.render(<CoachingPage {...props} />));
    expect(host.textContent).not.toContain("Ask one impact question.");
    expect(fetch).toHaveBeenCalledOnce();
  });
  it("keeps six pillars in narrative order, one mission and honest unknown progress", () => {
    const html = renderToStaticMarkup(
      <CoachingStory coaching={fictionalCoaching} />,
    );
    const headings = [
      "What You Should Work On Now",
      "Why This Keeps Happening",
      "Here’s What Better Looks Like",
      "Try This on Your Next Call",
      "See How You’re Improving",
      "Where We Go From Here",
    ];
    let previous = -1;
    for (const heading of headings) {
      const position = html.indexOf(heading);
      expect(position).toBeGreaterThan(previous);
      previous = position;
    }
    expect(html.match(/Active mission/g)).toHaveLength(1);
    expect(html).toContain("Unknown / Uncertain");
    expect(html).toContain("Not Enough Evidence");
    expect(html).not.toContain("autoplay");
    expect(html).not.toContain("<audio");
    expect(html).toContain("हैंडओवर");
    expect(html).toContain("कामाला");
    expect(html).toContain(
      "Saving agreement, disagreement and reflection is not available yet.",
    );
  });
  it("teaches in the spec's order and keeps the text short beside a clip", () => {
    const position = (html: string, text: string) => {
      const at = html.indexOf(text);
      expect(at).toBeGreaterThan(-1);
      return at;
    };
    const wording = fictionalCoaching.lesson!.example_wording[0];
    const withClip = renderToStaticMarkup(
      <CoachingStory
        coaching={{ ...fictionalCoaching, media_clips: [fictionalClip] }}
      />,
    );
    const order = [
      fictionalCoaching.lesson!.quick_idea,
      'aria-label="Framework"',
      "Better direction",
      fictionalClip.title,
      "Read the full lesson",
      wording,
    ].map((text) => position(withClip, text));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    const textOnly = renderToStaticMarkup(
      <CoachingStory coaching={fictionalCoaching} />,
    );
    expect(position(textOnly, wording)).toBeLessThan(
      position(textOnly, "Read the full lesson"),
    );
  });
  it("offers this call's quoted strength last in the lesson, playable", () => {
    const moment = fictionalCallCoaching.evidence[0];
    const html = renderToStaticMarkup(
      <CallCoachingStory
        coaching={{
          ...fictionalCallCoaching,
          strength: {
            title: "Asked for a consequence",
            explanation: "It made the problem specific.",
            evidence: [{ ...moment, quote: "What happened because of it?" }],
          },
        }}
      />,
    );
    const at = (text: string) => html.indexOf(text);
    expect(at("Use your strength")).toBeGreaterThan(at("Better direction"));
    expect(at("Use your strength")).toBeLessThan(at("Read the full lesson"));
    expect(html).toContain("What happened because of it?");
    expect(html).not.toContain("<audio");
    expect(
      renderToStaticMarkup(
        <CallCoachingStory coaching={fictionalCallCoaching} />,
      ),
    ).not.toContain("Use your strength");
  });
  it("names the call a My coaching strength came from, never a trait", () => {
    const moment = fictionalCoaching.evidence[0];
    const html = renderToStaticMarkup(
      <CoachingStory
        coaching={{
          ...fictionalCoaching,
          strength: {
            title: "Asked a follow-up",
            explanation: "It made the problem specific.",
            evidence: [moment],
          },
        }}
      />,
    );
    expect(html).toContain("Use your strength");
    expect(html).toContain("One call is not an established strength.");
    expect(html.lastIndexOf(moment.call_label)).toBeGreaterThan(
      html.indexOf("Use your strength"),
    );
  });
  it("opens with the three newest calls on one column until asked", async () => {
    const calls = Array.from({ length: 5 }, (_, index) => ({
      submission_id: `00000000-0000-0000-0000-00000000009${index}`,
      call_label: `Call ${index + 1}`,
      created_at: `2026-10-0${index + 1}T10:00:00Z`,
      state: "ready" as const,
      focus_label: null,
    }));
    await act(async () =>
      root.render(<CoachingStory coaching={{ ...fictionalCoaching, calls }} />),
    );
    const list = host.querySelector('[aria-label="Your recent calls"]')!;
    expect(list.querySelectorAll("li")).toHaveLength(5);
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(false);
    const more = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Show all 5 calls",
    )!;
    await act(async () => more.click());
    expect(list.parentElement!.hasAttribute("data-expanded")).toBe(true);
    expect(host.textContent).not.toContain("Show all 5 calls");
  });
  it("shows what comparable calls said since the mission, never success", () => {
    const html = renderToStaticMarkup(
      <CoachingStory
        coaching={{
          ...fictionalCoaching,
          progress: [
            {
              submission_id: fictionalCoaching.evidence[0].submission_id,
              created_at: "2026-10-09T10:00:00Z",
              state: "suggested",
              after_mission: false,
            },
            {
              submission_id: fictionalCoaching.evidence[1].submission_id,
              created_at: "2026-10-10T10:00:00Z",
              state: "no_suggestion",
              after_mission: true,
            },
          ],
        }}
      />,
    );
    expect(html).toContain(
      "Since your mission started: 1 of 1 comparable call had evidence for this skill and no suggestion. That is not proof of change yet.",
    );
    expect(html.match(/data-mission-start/g)).toHaveLength(1);
    expect(html).toContain("Not Enough Evidence");
  });
  it("has a loading skeleton and makes no request without a confirmed account", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<CoachingPage />));
    expect(host.textContent).toContain("My coaching");
    expect(fetch).not.toHaveBeenCalled();
    expect(renderToStaticMarkup(<CoachingSkeleton />)).toContain(
      'aria-label="Loading Coaching"',
    );
    expect(renderToStaticMarkup(<CoachingSkeleton />)).toContain(
      'aria-busy="true"',
    );
  });
  it("accepts a report focus as context while keeping the one active mission", () => {
    const before = structuredClone(fictionalCoaching.mission);
    const html = renderToStaticMarkup(
      <CoachingStory
        coaching={fictionalCoaching}
        requestedFocus="qualification"
      />,
    );
    expect(html).toContain("Your report brought you here for Qualification");
    expect(html.match(/Active mission/g)).toHaveLength(1);
    expect(fictionalCoaching.mission).toEqual(before);
    for (const input of [
      "unknown",
      "__proto__",
      "constructor",
      ["qualification"],
      null,
    ])
      expect(requestedSkill(input)).toBeUndefined();
    expect(requestedSkill("qualification")).toBe("qualification");
  });
  it("rejects a stale workspace response and clears prior learner data on context change", async () => {
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCoaching.person_id,
        tenantId: fictionalCoaching.tenant_id,
        sessionId: "session-a",
      },
      retry: vi.fn(),
    };
    const response = () =>
      new Response(JSON.stringify(fictionalCoaching), {
        headers: { "content-type": "application/json" },
      });
    const fetch = vi.fn().mockImplementation(async () => response());
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<CoachingPage />));
    expect(host.textContent).toContain("Ask one impact question.");
    mocks.access = {
      ...mocks.access,
      context: {
        ...mocks.access.context!,
        tenantId: "00000000-0000-0000-0000-000000000099",
      },
    };
    await act(async () => root.render(<CoachingPage />));
    expect(host.textContent).not.toContain("Ask one impact question.");
    expect(host.textContent).toContain("Your workspace changed. Try again.");
  });
  it("shows a corner recovery card with Try again after a network failure", async () => {
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCoaching.person_id,
        tenantId: fictionalCoaching.tenant_id,
        sessionId: "session-a",
      },
      retry: vi.fn(),
    };
    const fetch = vi
      .fn()
      .mockRejectedValue(new Error("private upstream diagnostic"));
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<CoachingPage />));
    expect(host.querySelector('aside[role="alert"]')?.textContent).toContain(
      "Try again",
    );
    expect(host.textContent).not.toContain("private upstream diagnostic");
  });
});
