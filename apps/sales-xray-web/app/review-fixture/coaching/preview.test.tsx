import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { parseCoaching } from "../../coaching/coaching-client";
import { parseCallCoaching } from "../../coaching/coaching-read";
import { parseTeamCoaching } from "../../coaching/team-contract";
import { CoachingFixture } from "./preview";
import sandbox from "./sandbox.json";

describe("Coaching review fixture", () => {
  it("passes every sandbox payload through the real parsers", () => {
    expect(sandbox.synthetic).toBe(true);
    const call = parseCallCoaching(sandbox.call, sandbox.call.submission_id);
    // The packaged placeholder lessons: one free, one locked with the offer.
    expect(call?.media_clips?.map((clip) => clip.access)).toEqual([
      "full",
      "locked",
    ]);
    expect(call?.media_clips?.[1].offer?.academy?.href).toBe(
      "https://learner.authorityclosers.com/",
    );
    expect(parseCoaching(sandbox.me).calls).toHaveLength(8);
    expect(parseTeamCoaching(sandbox.team)?.suggestions.length).toBeGreaterThan(
      2,
    );
  });
  it("renders the call view with Dipak's lesson and the locked offer", () => {
    const html = renderToStaticMarkup(<CoachingFixture />);
    expect(html).toContain("Synthetic sandbox data");
    expect(html).toContain("Objection: Answer Nahi, Diagnose");
    expect(html).toContain("Part of Dipak’s full coaching");
    expect(html).toContain("Get the full coaching");
    expect(html).not.toContain("<audio");
  });
});
