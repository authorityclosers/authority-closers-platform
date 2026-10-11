import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { parseCoaching } from "../../coaching/coaching-client";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { CoachingFixture } from "./preview";
import sandbox from "./sandbox.json";
import acSandbox from "./sandbox-team.json";

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
    expect(new URLSearchParams(window.location.search).get("view")).toBe("team");
    expect(pressed()).toContain("Team");
    await act(async () => root.unmount());
    host.remove();
    window.history.replaceState(null, "", "/");
  });
});
