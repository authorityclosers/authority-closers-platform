import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TeamCoachingStory } from "./team-coaching";
import { parseTeamCoaching } from "./team-contract";
import { readCoaching } from "./coaching-read";
import { fictionalTeamCoaching } from "./coaching.fixture";

afterEach(() => vi.unstubAllGlobals());
describe("anonymous Team coaching", () => {
  it("renders aggregate counts and a clear private-sharing limitation", () => {
    const html = renderToStaticMarkup(
      <TeamCoachingStory coaching={fictionalTeamCoaching} />,
    );
    expect(html).toContain("Analysed calls");
    expect(html).toContain("2 people · updated 9 Oct 2026");
    expect(html).toContain("2 of 3 calls");
    expect(html).toContain("67%");
    expect(html).toContain("Private by default");
    expect(html).toContain("Named coaching appears when a rep shares it");
    expect(html).toContain("stop sharing at any time");
    expect(html).not.toContain("/analysis/calls/");
    expect(html).not.toContain("Play evidence");
    expect(html).not.toContain("<audio");
  });
  it("defaults absent counts and rows and discards source-supplied labels", () => {
    const sparse = parseTeamCoaching({
      ...fictionalTeamCoaching,
      suggestions: undefined,
      analysed_calls: undefined,
    })!;
    expect(sparse.analysed_calls).toBe(0);
    expect(sparse.suggestions).toEqual([]);
    const data = structuredClone(fictionalTeamCoaching);
    data.suggestions[0].label = "Private rep name and context";
    expect(parseTeamCoaching(data)?.suggestions[0].label).toBe(
      "Problem, Impact & Desire Clarity",
    );
  });
  it("rejects named details, private fields and invalid counts", () => {
    for (const raw of [
      { ...fictionalTeamCoaching, named_rep_details: true },
      { ...fictionalTeamCoaching, evidence: [] },
      { ...fictionalTeamCoaching, analysed_calls: -1 },
      {
        ...fictionalTeamCoaching,
        suggestions: [{ skill_id: "made_up_skill", suggestion_calls: 1 }],
      },
      {
        ...fictionalTeamCoaching,
        suggestions: [{ skill_id: "qualification", suggestion_calls: 4 }],
      },
    ])
      expect(parseTeamCoaching(raw)).toBeNull();
  });
  it("loads the team projection in one same-account request", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fictionalTeamCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    expect((await readCoaching("team")).data?.schema).toBe(
      "ac.sales-xray.team-coaching/1",
    );
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0][0]).toBe("/v1/me/coaching/team");
  });
});
