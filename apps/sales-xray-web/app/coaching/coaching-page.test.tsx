import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceAccessValue } from "../workspace-access";
import { CoachingPage, CoachingSkeleton, CoachingStory } from "./coaching-page";
import { fictionalCoaching, fictionalCallCoaching } from "./coaching.fixture";
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
    expect(html).toContain("Your next-call mission");
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
