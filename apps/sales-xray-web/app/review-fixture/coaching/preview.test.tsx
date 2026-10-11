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
    expect(call?.media_clips?.map((clip) => clip.access)).toEqual([
      "preview",
      "locked",
    ]);
    expect(parseCoaching(sandbox.me).calls).toHaveLength(8);
    expect(parseTeamCoaching(sandbox.team)?.suggestions.length).toBeGreaterThan(
      2,
    );
  });
  it("renders the call view with the preview and locked offer", () => {
    const html = renderToStaticMarkup(<CoachingFixture />);
    expect(html).toContain("Synthetic sandbox data");
    expect(html).toContain("Free preview");
    expect(html).toContain("Part of Dipak’s full coaching");
    expect(html).toContain("Get the full coaching");
    expect(html).not.toContain("<audio");
  });
});
