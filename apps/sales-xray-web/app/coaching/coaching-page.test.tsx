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
          initialResult={{ data: null, error: "This link doesn’t work." }}
        />,
      ),
    );
    const retry = [...host.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Try again"),
    )!;
    await act(async () => retry.click());
    expect(fetch).not.toHaveBeenCalled();
    expect(host.textContent).toContain("This link doesn’t work.");
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
  it("says “their” across another rep's coaching and “your” on your own", () => {
    const progress = [
      {
        submission_id: "00000000-0000-4000-8000-0000000000c1",
        created_at: "2026-09-01T10:00:00Z",
        state: "suggested" as const,
        after_mission: true,
      },
    ];
    const theirs = renderToStaticMarkup(
      <CoachingStory coaching={{ ...fictionalCoaching, progress }} readOnly />,
    );
    for (const words of [
      "What They Should Work On Now",
      "Their highest-priority improvement.",
      "On their next call",
      "From their calls",
      "using their own calls",
      "Try This on Their Next Call",
      "Their next-call mission",
      "See How They’re Improving",
      "Their calls on this skill",
      "Since their mission started",
      "See the next stage of their development.",
    ])
      expect(theirs).toContain(words);
    for (const words of [
      "What You Should Work On Now",
      "On your next call",
      "From your calls",
      "Your next-call mission",
      "See How You’re Improving",
      "Your calls on this skill",
      "Your call ·",
    ])
      expect(theirs).not.toContain(words);
    expect(theirs).toContain('aria-label="Moments from their calls"');
    expect(theirs).not.toContain("Your report brought you here");
    const calls = [
      {
        submission_id: "00000000-0000-4000-8000-0000000000c2",
        call_label: "Fictional call",
        created_at: "2026-09-02T10:00:00Z",
        state: "ready" as const,
        focus_label: "Explain value first",
      },
    ];
    // A shared real rep's calls open their reports (a call's own coaching is
    // only ever the rep's); a fictional rep's calls open its Coaching.
    const shared = renderToStaticMarkup(
      <CoachingStory coaching={{ ...fictionalCoaching, calls }} readOnly />,
    );
    expect(shared).toContain(
      'href="/analysis/calls/00000000-0000-4000-8000-0000000000c2"',
    );
    expect(shared).not.toContain("/coaching?call=");
    const fictional = renderToStaticMarkup(
      <CoachingStory
        coaching={{ ...fictionalCoaching, calls, sandbox: true }}
        readOnly
      />,
    );
    expect(fictional).toContain(
      'href="/coaching?call=00000000-0000-4000-8000-0000000000c2"',
    );
    const mine = renderToStaticMarkup(
      <CoachingStory coaching={{ ...fictionalCoaching, progress }} />,
    );
    expect(mine).toContain("What You Should Work On Now");
    expect(mine).toContain("From your calls");
    expect(mine).toContain("Since your mission started");
    expect(mine).not.toContain("Their next-call mission");
    expect(mine).toContain('aria-label="Moments from your calls"');
    // One sentence for screen readers, not a row per progress dot.
    expect(mine).toContain(
      "Your calls on this skill, oldest first: 1 needed work.",
    );
    expect(theirs).toContain(
      "Their calls on this skill, oldest first: 1 needed work.",
    );
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
    // A fictional rep's call says "their"; the importer's own calls say "your".
    expect(withRep).toContain("What They Should Work On Now");
    expect(withRep).toContain("Their next-call mission");
    expect(withRep).toContain(
      "Rohan Kendrekar’s coaching follows all their calls.",
    );
    expect(withRep).not.toContain("My coaching follows all your calls");
    expect(withRep).not.toContain("On your next call");
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
  it("shows a synthetic monologue once when the lesson repeats it as an observation", () => {
    const quote =
      "One long fictional seller monologue, without an extra lesson finding. ".repeat(
        20,
      );
    const moment = {
      ...fictionalCallCoaching.evidence[0],
      quote,
      observation: quote,
    };
    const call = {
      ...fictionalCallCoaching,
      evidence: [moment],
      lesson: { ...fictionalCallCoaching.lesson!, own_call: moment },
    };
    const html = renderToStaticMarkup(<CallCoachingStory coaching={call} />);
    const container = document.createElement("div");
    container.innerHTML = html;
    expect(container.querySelector("blockquote")?.textContent).toBe(quote);
    expect(container.textContent?.split(quote)).toHaveLength(2);
    expect(container.textContent).toContain("Read the moment above.");
    expect(container.textContent).toContain("Read full quote");
    expect(container.textContent).toContain(call.mission!.behavior);
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
  it("says an authored lesson's mission once in the lesson, not as its idea too", () => {
    // AC Sandbox's dataset gives one sentence as idea, better direction and mission.
    const mission =
      "Before describing the offer, ask for one recent example and one consequence of the problem.";
    const lesson = {
      ...fictionalCoaching.lesson!,
      quick_idea: mission,
      good_looks_like: `${mission.slice(0, -1)} `,
      better_direction: mission,
      next_call_connection: mission,
    };
    const html = renderToStaticMarkup(
      <CoachingStory coaching={{ ...fictionalCoaching, lesson }} />,
    );
    const start = html.indexOf('id="coaching-better"');
    const pillar = html.slice(start, html.indexOf('id="mission"', start));
    expect(start).toBeGreaterThan(-1);
    // Better direction, then the full lesson's closing mission (spec 6.6).
    expect(pillar.split(mission.slice(0, -1)).length - 1).toBe(2);
    expect(pillar).not.toContain("What good looks like");
    const distinct = renderToStaticMarkup(
      <CoachingStory coaching={fictionalCoaching} />,
    );
    expect(distinct).toContain(fictionalCoaching.lesson!.quick_idea);
    expect(distinct).toContain("What good looks like");
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
    expect(html).toContain("One call doesn’t prove a strength yet.");
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
            {
              submission_id: "00000000-0000-4000-8000-0000000000c3",
              created_at: "2026-10-11T10:00:00Z",
              state: "not_covered",
              after_mission: true,
            },
          ],
        }}
      />,
    );
    // The third call gave no chance to use the skill, so it isn't counted.
    expect(html).toContain(
      "Since your mission started: 1 of 1 call on this skill needed no fix. Too early to call it a change.",
    );
    expect(html.match(/data-mission-start/g)).toHaveLength(1);
    // The legend names the bar, and only when the bar is drawn.
    expect(html.match(/Mission started</g)).toHaveLength(1);
    expect(html).toContain("Not Enough Evidence");
    const before = renderToStaticMarkup(
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
          ],
        }}
      />,
    );
    expect(before).not.toContain("data-mission-start");
    expect(before).not.toContain("Mission started<");
  });
  it("leaves the loading frame once access settles: ready reads once, signed out asks to sign in", async () => {
    const loading = {
      status: "loading",
      authenticated: null,
      context: null,
      retry: vi.fn(),
    } as WorkspaceAccessValue;
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fictionalCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const coachingReads = () =>
      fetch.mock.calls.filter(([url]) =>
        String(url).endsWith("/v1/me/coaching"),
      ).length;
    // Loading: the skeleton, and no read before the account is confirmed.
    mocks.access = loading;
    await act(async () => root.render(<CoachingPage />));
    expect(host.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    // Ready: one read, then the learner's six pillars and no skeleton.
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
    await act(async () => root.render(<CoachingPage />));
    await act(async () => {});
    expect(coachingReads()).toBe(1);
    expect(host.querySelectorAll("section[data-coaching-pillar]")).toHaveLength(
      6,
    );
    expect(host.querySelector('[aria-busy="true"]')).toBeNull();
    // Loading again, then signed out: the sign-in card, never skeletons.
    mocks.access = loading;
    await act(async () => root.render(<CoachingPage key="signed-out" />));
    mocks.access = {
      ...loading,
      status: "unauthenticated",
      authenticated: false,
    };
    await act(async () => root.render(<CoachingPage key="signed-out" />));
    expect(host.textContent).toContain("Sign in for your Coaching");
    expect(host.querySelector('[aria-busy="true"]')).toBeNull();
    expect(coachingReads()).toBe(1);
  });
  it("ends a failed or missing read on the unavailable card, never on skeletons", async () => {
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
    for (const answer of [
      () => Promise.resolve(new Response("", { status: 404 })),
      () => Promise.resolve(new Response("", { status: 409 })),
      () => Promise.resolve(new Response("", { status: 500 })),
      () => Promise.reject(new TypeError("network down")),
    ]) {
      vi.stubGlobal("fetch", vi.fn(answer));
      for (const callId of [null, fictionalCallCoaching.submission_id]) {
        await act(async () =>
          root.render(<CoachingPage key={`${callId}`} callId={callId} />),
        );
        await act(async () => {});
        expect(host.textContent).toContain("Coaching didn’t load");
        expect(host.querySelector('[aria-busy="true"]')).toBeNull();
        expect(host.querySelector('[role="alert"]')).not.toBeNull();
      }
    }
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
