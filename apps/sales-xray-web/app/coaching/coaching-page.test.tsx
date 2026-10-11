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
  it("points an AC Sandbox importer with no own calls to the fictional team", () => {
    const empty = {
      ...fictionalCoaching,
      state: "not_enough_evidence" as const,
      analysed_calls: 0,
      focus: null,
      mission: null,
      practice: null,
      lesson: null,
      evidence: [],
      calls: [],
      sandbox_reps: 60,
    };
    const html = renderToStaticMarkup(<CoachingStory coaching={empty} />);
    expect(html).toContain("See 60 fictional reps’ coaching");
    expect(html).toContain('href="/coaching?view=team"');
    expect(html).toContain("Your own coaching follows your own calls");
    const plain = renderToStaticMarkup(
      <CoachingStory coaching={{ ...empty, sandbox_reps: 0 }} />,
    );
    expect(plain).not.toContain("fictional reps");
    // Sharing can always be stopped, focus or not.
    expect(plain).toContain("Who sees your coaching");
    // Another rep's empty view speaks about them, with no action of the viewer's.
    const theirs = renderToStaticMarkup(
      <CoachingStory coaching={{ ...empty, sandbox_reps: 0 }} readOnly />,
    );
    expect(theirs).toContain("What They Should Work On Now");
    expect(theirs).not.toContain("Analyse a call");
    expect(theirs).not.toContain("Who sees your coaching");
  });
  it("labels a fictional AC Sandbox call and leads back to Team, not a report", () => {
    const html = renderToStaticMarkup(
      <CallCoachingStory
        coaching={{ ...fictionalCallCoaching, sandbox: true }}
      />,
    );
    expect(html).toContain("Fictional AC Sandbox");
    expect(html).toContain("Back to team coaching");
    expect(html).not.toContain("/analysis/calls/");
    const withRep = renderToStaticMarkup(
      <CallCoachingStory
        coaching={{
          ...fictionalCallCoaching,
          sandbox: true,
          rep_person_id: "00000000-0000-4000-8000-0000000000aa",
          rep_name: "Rohan Kendrekar",
        }}
      />,
    );
    expect(withRep).toContain("Rohan Kendrekar’s coaching across calls");
    expect(withRep).toContain(
      "/coaching?person=00000000-0000-4000-8000-0000000000aa",
    );
  });
  it("opens a fictional rep's coaching under their name, read-only", async () => {
    const person = "00000000-0000-4000-8000-0000000000aa";
    mocks.access = {
      status: "ready",
      authenticated: true,
      context: {
        personId: fictionalCoaching.person_id,
        tenantId: fictionalCoaching.tenant_id,
        sessionId: "00000000-0000-4000-8000-000000000003",
      },
      workspaces: [],
      retry: () => {},
    } as unknown as WorkspaceAccessValue;
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <CoachingPage
          sharedPersonId={person}
          initialResult={{
            data: {
              ...fictionalCoaching,
              person_id: person,
              session_id: null,
              sandbox: true,
              person_name: "Rohan Kendrekar",
            },
            error: null,
          }}
        />,
      ),
    );
    expect(host.querySelector("h1")?.textContent).toBe("Rohan Kendrekar");
    expect(host.textContent).toContain("Fictional AC Sandbox rep");
    expect(host.textContent).toContain("Back to team");
    expect(host.textContent).not.toContain("Saving your agreement");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("renders a single call's four pillars with no invented pattern or mastery gate", () => {
    const html = renderToStaticMarkup(
      <CallCoachingStory coaching={fictionalCallCoaching} />,
    );
    expect(html).toContain("What You Should Work On Now");
    expect(html).toContain("What Happened on This Call");
    expect(html).toContain("Here’s What Better Looks Like");
    expect(html).toContain("Try This on Your Next Call");
    expect(html.match(/data-active-mission/g)).toHaveLength(1);
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
    expect(html.match(/data-active-mission/g)).toHaveLength(1);
    expect(html).toContain("Not clear yet");
    expect(html).toContain("Not Enough Evidence");
    // Regression said honestly; no trend arrow without a known trend.
    expect(html).toContain("Not enough calls on this skill to tell yet");
    expect(html).not.toContain("Improving ↑");
    expect(html).not.toContain("autoplay");
    expect(html).not.toContain("<audio");
    expect(html).toContain("हैंडओवर");
    expect(html).toContain("कामाला");
    // Spec 12.6: agree / not completely, after the evidence; sharing below.
    expect(html.indexOf("Not completely")).toBeGreaterThan(
      html.indexOf("Where We Go From Here"),
    );
    expect(html).toContain("Who sees your coaching");
    // A fictional or shared rep's view is read-only: nothing to save.
    const readOnly = renderToStaticMarkup(
      <CoachingStory coaching={fictionalCoaching} readOnly />,
    );
    expect(readOnly).not.toContain("Not completely");
    expect(readOnly).not.toContain("Who sees your coaching");
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
    // The full lesson ends with the same active mission (spec 6.6).
    expect(position(textOnly, "Your next-call mission")).toBeGreaterThan(
      position(textOnly, "Quick checklist"),
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
    expect(html).toContain("One call doesn’t make it a proven strength yet.");
    expect(html.lastIndexOf(moment.call_label)).toBeGreaterThan(
      html.indexOf("Use your strength"),
    );
  });
  it("says the report holds more suggestions while coaching keeps one", () => {
    const html = renderToStaticMarkup(
      <CallCoachingStory
        coaching={{ ...fictionalCallCoaching, other_suggestions: 2 }}
      />,
    );
    expect(html).toContain(
      "2 more suggestions there; Coaching keeps one focus",
    );
    expect(
      renderToStaticMarkup(
        <CallCoachingStory coaching={fictionalCallCoaching} />,
      ),
    ).not.toContain("more suggestion");
  });
  it("marks a call whose focus also came up on other calls, and only that call", () => {
    const row = (id: string, recurring: boolean | null) => ({
      submission_id: id,
      call_label: `Call ${id.slice(-1)}`,
      created_at: "2026-10-01T10:00:00Z",
      state: "ready" as const,
      focus_label: "Explore the consequence",
      recurring,
    });
    const html = renderToStaticMarkup(
      <CoachingStory
        coaching={{
          ...fictionalCoaching,
          calls: [
            row("00000000-0000-0000-0000-000000000091", true),
            row("00000000-0000-0000-0000-000000000092", false),
            row("00000000-0000-0000-0000-000000000093", null),
          ],
        }}
      />,
    );
    expect(html.match(/Also on other calls/g)).toHaveLength(1);
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
  it("shows what this skill's calls said since the mission, never success", () => {
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
      "Since your mission started: 1 of 1 call used this skill with nothing to fix. Not proof of change yet.",
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
    expect(html.match(/data-active-mission/g)).toHaveLength(1);
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
