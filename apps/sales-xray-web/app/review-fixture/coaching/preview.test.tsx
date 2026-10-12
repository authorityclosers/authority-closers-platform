import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { parseCoaching } from "../../coaching/coaching-client";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { CoachingFixture } from "./preview";
import sandbox from "./sandbox.json";
import acSandbox from "./sandbox-team.json";
import longQuote from "./long-quote.json";

describe("Coaching review fixture", () => {
  it("passes every sandbox payload through the real parsers", () => {
    expect(sandbox.synthetic).toBe(true);
    const call = parseCallCoaching(sandbox.call, sandbox.call.submission_id);
    // The packaged placeholder lessons: one free, one 15 s preview with the offer.
    expect(call?.media_clips?.map((clip) => clip.access)).toEqual([
      "full",
      "preview",
    ]);
    expect(call?.media_clips?.[1].preview_end_ms).toBe(15000);
    expect(call?.media_clips?.[1].offer?.academy?.href).toBe(
      "https://learner.authorityclosers.com/",
    );
    expect(parseCoaching(sandbox.me).calls).toHaveLength(8);
    expect(parseTeamCoaching(sandbox.team)?.suggestions.length).toBeGreaterThan(
      2,
    );
  });
  it("renders the call view with Dipak's lesson and the 15 s preview hook", () => {
    const html = renderToStaticMarkup(<CoachingFixture />);
    expect(html).toContain("Synthetic sandbox data");
    expect(html).toContain("Objection: Answer Nahi, Diagnose");
    expect(html).toContain("Free preview · 0:15");
    expect(html).toContain("The first 15 seconds are free.");
    // The offer opens once the preview ends (media-player tests cover it).
    expect(html).toContain("End of the free preview");
    expect(html).not.toContain("<audio");
  });
  it("passes the AC Sandbox states through the same parsers", () => {
    const team = parseTeamCoaching(acSandbox.team);
    expect(team?.sandbox).toBe(true);
    expect(team?.reps.length).toBe(acSandbox.team.rep_count);
    const rep = parseCoaching(acSandbox.rep);
    expect(rep.sandbox).toBe(true);
    expect(rep.person_name).toBeTruthy();
    expect(rep.focus?.skill_id).toBeTruthy();
    const call = parseCallCoaching(
      acSandbox.call,
      acSandbox.call.submission_id,
    );
    expect(call?.state).toBe("ready");
    expect(call?.evidence.every((moment) => !moment.playable)).toBe(true);
  });
  it("keeps the long synthetic quote and its original span in the opt-in review", async () => {
    window.history.replaceState(
      null,
      "",
      "/review-fixture/coaching?data=sandbox&example=long-quote",
    );
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => root.render(<CoachingFixture />));
    const quote = longQuote.call.evidence[0].quote;
    expect(quote.length).toBeGreaterThan(1000);
    expect(host.querySelector("blockquote")?.textContent).toBe(quote);
    expect(host.textContent).toContain("2:10–3:37");
    expect(host.textContent).toContain("Read full quote");
    expect(host.textContent).toContain("Read the moment above.");
    expect(host.textContent).not.toContain("Play moment");
    expect(host.querySelector("audio")).toBeNull();
    const call = parseCallCoaching(
      longQuote.call,
      longQuote.call.submission_id,
    )!;
    expect(call.evidence[0]).toMatchObject({
      quote,
      source_sha256: longQuote.sourcePayloadSha256,
      start_ms: 130930,
      end_ms: 217313,
    });
    await act(async () => root.unmount());
    host.remove();
    window.history.replaceState(null, "", "/");
  });
  it("opens the level named in the address and keeps a new choice there", async () => {
    window.history.replaceState(null, "", "/review-fixture/coaching?view=me");
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => root.render(<CoachingFixture />));
    const pressed = () =>
      [...host.querySelectorAll('button[aria-pressed="true"]')].map(
        (button) => button.textContent,
      );
    expect(pressed()).toContain("My coaching");
    expect(host.textContent).toContain("Why This Keeps Happening");
    const team = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Team",
    );
    await act(async () => team?.click());
    expect(new URLSearchParams(window.location.search).get("view")).toBe(
      "team",
    );
    expect(pressed()).toContain("Team");
    await act(async () => root.unmount());
    host.remove();
    window.history.replaceState(null, "", "/");
  });
  it("shows the feedback and sharing flows in the page without sending anything", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    const fetch = vi.fn().mockRejectedValue(new Error("no network here"));
    vi.stubGlobal("fetch", fetch);
    window.history.replaceState(null, "", "/review-fixture/coaching?view=me");
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => root.render(<CoachingFixture />));
    const button = (name: string) =>
      [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
    expect(host.textContent).toContain("Taps here aren’t saved");
    await act(async () => button("Not completely").click());
    expect(
      host.querySelectorAll('ul[aria-label="This focus is based on"] li')
        .length,
    ).toBe(sandbox.me.evidence.length);
    expect(host.textContent).toContain("What did we miss?");
    await act(async () => button("I noticed it later").click());
    expect(button("I noticed it later").getAttribute("aria-pressed")).toBe(
      "true",
    );
    await act(async () => button("Share with your admins").click());
    expect(host.textContent).toContain("Stop sharing");
    expect(fetch).not.toHaveBeenCalled();
    await act(async () => root.unmount());
    host.remove();
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  });
});
