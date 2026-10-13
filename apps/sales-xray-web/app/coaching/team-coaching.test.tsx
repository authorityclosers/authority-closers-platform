import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TeamCoachingStory } from "./team-coaching";
import { parseTeamCoaching } from "./team-contract";
import { readCoaching } from "./coaching-read";
import { fictionalCoaching, fictionalTeamCoaching } from "./coaching.fixture";

const rep = (id: number, name: string, skill: string, calls = 3) => ({
  person_id: `00000000-0000-4000-8000-${String(id).padStart(12, "0")}`,
  name,
  skill_id: skill,
  focus_label: `Focus for ${name}`,
  calls,
  latest_call_at: "2026-09-01T10:00:00Z",
});
const sandboxTeam = {
  ...fictionalTeamCoaching,
  scope: "sandbox",
  named_rep_details: true,
  sandbox: true,
  reps_basis: "fictional",
  suggestions: [
    {
      skill_id: "closing_decision_management",
      label: "Closing & Decision Management",
      suggestion_calls: 3,
    },
    {
      skill_id: "qualification",
      label: "Qualification",
      suggestion_calls: 1,
    },
  ],
  reps: [
    ...Array.from({ length: 9 }, (_, i) =>
      rep(i + 1, `Closer ${i + 1}`, "closing_decision_management"),
    ),
    {
      ...rep(20, "Asha Rao", "qualification", 1),
      focus_label: "Confirm who decides before the sale",
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());
describe("anonymous Team coaching", () => {
  it("renders aggregate counts and a clear private-sharing limitation", () => {
    const html = renderToStaticMarkup(
      <TeamCoachingStory coaching={fictionalTeamCoaching} />,
    );
    expect(html).toContain("Analysed calls");
    // The tile's note stays one short line; the date sits in the footnote.
    expect(html).toContain(">2 people<");
    expect(html).toContain("Updates after every call. Latest call 9 Oct 2026.");
    expect(html).toContain("2 of 3 calls");
    expect(html).toContain("67%");
    expect(html).toContain("Private by default");
    expect(html).toContain("Named coaching appears when a rep shares it");
    expect(html).toContain("stop sharing at any time");
    expect(html).not.toContain("/analysis/calls/");
    // Every call over time lives in Insights, not recounted here.
    expect(html).toContain('href="/organisation/insights"');
    expect(html).not.toContain("Play moment");
    expect(html).not.toContain("<audio");
    expect(html).not.toContain("Find a rep");
    expect(html).not.toContain("Find reps");
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
  it("shows which buyer objections the team hears and how many were left open", () => {
    const team = parseTeamCoaching({
      ...fictionalTeamCoaching,
      objection_calls: 2,
      objections: [
        {
          kind: "price_concern",
          label: "Server words",
          calls: 2,
          heard: 3,
          handled: 1,
        },
        { kind: "stall", calls: 1, heard: 1, handled: 1 },
        // Unknown kinds and impossible counts drop only that row.
        { kind: "made_up", calls: 1, heard: 1, handled: 0 },
        { kind: "trust_concern", calls: 5, heard: 5, handled: 0 },
        { kind: "time_constraint", calls: 1, heard: 1, handled: 2 },
      ],
    })!;
    expect(team.objections.map((row) => row.label)).toEqual([
      "Price",
      "Stalling",
    ]);
    const html = renderToStaticMarkup(<TeamCoachingStory coaching={team} />);
    expect(html).toContain("Objections your team hears");
    expect(html).toContain("2 of 3 left open");
    expect(html).toContain("all 1 answered");
    expect(html).not.toContain("Server words");
    // Older reports without a call map never read as "no objections".
    const older = renderToStaticMarkup(
      <TeamCoachingStory coaching={fictionalTeamCoaching} />,
    );
    expect(older).not.toContain("Objections your team hears");
  });
  it("names only fictional AC Sandbox reps, with links to their coaching", () => {
    const team = parseTeamCoaching(sandboxTeam)!;
    expect(team.sandbox).toBe(true);
    expect(team.reps).toHaveLength(10);
    const html = renderToStaticMarkup(<TeamCoachingStory coaching={team} />);
    expect(html).toContain("Fictional AC Sandbox");
    expect(html).toContain("10 fictional reps");
    expect(html).toContain(`/coaching?person=${team.reps[0].person_id}`);
    expect(html).toContain("Focus for Closer 1");
    expect(html).toContain("Latest call 1 Sept 2026");
    expect(html).toContain("Show all 10 people");
    expect(html.indexOf("Who needs help with what")).toBeLessThan(
      html.indexOf("What the team should work on"),
    );
    expect(html).not.toContain("Named coaching appears when a rep shares it");
    expect(html).not.toContain("/organisation/insights");
    // Malformed rows drop; the rest of the team still shows.
    const partial = parseTeamCoaching({
      ...sandboxTeam,
      reps: [{ name: "No id" }, sandboxTeam.reps[0], sandboxTeam.reps[0]],
    })!;
    expect(partial.reps.map((row) => row.name)).toEqual(["Closer 1"]);
  });
  it("names a real rep only after they share, keeping latest-call and share dates separate", () => {
    const shared = {
      ...fictionalTeamCoaching,
      named_rep_details: true,
      reps_basis: "shared",
      suggestions: [
        fictionalTeamCoaching.suggestions[0],
        {
          skill_id: "qualification",
          label: "Qualification",
          suggestion_calls: 1,
        },
      ],
      reps: [
        {
          ...rep(30, "Swati Kale", "qualification", 4),
          focus_label: "Qualification",
          shared_at: "2026-10-11T09:00:00Z",
        },
      ],
    };
    const team = parseTeamCoaching(shared)!;
    expect(team.reps_basis).toBe("shared");
    const html = renderToStaticMarkup(<TeamCoachingStory coaching={team} />);
    expect(html).toContain("1 shared with you");
    expect(html).toContain("Find a rep");
    expect(html).toContain("Find reps working on Qualification");
    // Historic call suggestions never invent a current rep on that skill.
    expect(html).not.toContain("Find reps working on Problem");
    expect(html).toContain("Shared 11 Oct 2026");
    expect(html).toContain("Latest call 1 Sept 2026");
    expect(html).toContain(`/coaching?person=${team.reps[0].person_id}`);
    expect(html).not.toContain("fictional");
    // A real rep without a share date never appears.
    const unshared = parseTeamCoaching({
      ...shared,
      reps: [{ ...shared.reps[0], shared_at: null }],
    })!;
    expect(unshared.reps).toEqual([]);
    expect(
      renderToStaticMarkup(<TeamCoachingStory coaching={unshared} />),
    ).not.toContain("Find reps");
    const noFocus = parseTeamCoaching({
      ...shared,
      reps: [{ ...shared.reps[0], skill_id: null, focus_label: null }],
    })!;
    const noFocusHtml = renderToStaticMarkup(
      <TeamCoachingStory coaching={noFocus} />,
    );
    expect(noFocusHtml).toContain("No focus shown");
    expect(noFocusHtml).toContain("Shared 11 Oct 2026");
    expect(noFocusHtml).toContain("Latest call 1 Sept 2026");
    expect(noFocusHtml).toContain(
      `/coaching?person=${shared.reps[0].person_id}`,
    );
    expect(noFocusHtml).not.toContain("Find reps working on");
    const noDate = parseTeamCoaching({
      ...shared,
      reps: [{ ...shared.reps[0], latest_call_at: null }],
    })!;
    const noDateHtml = renderToStaticMarkup(
      <TeamCoachingStory coaching={noDate} />,
    );
    expect(noDateHtml).toContain("Shared 11 Oct 2026");
    expect(noDateHtml).not.toContain("Latest call 1 Sept 2026");
    expect(
      parseTeamCoaching({ ...shared, sandbox: true, scope: "sandbox" }),
    ).toBeNull();
  });
  it("rejects names on a real team, however they are labelled", () => {
    for (const raw of [
      { ...fictionalTeamCoaching, reps: sandboxTeam.reps },
      { ...sandboxTeam, sandbox: false },
      { ...sandboxTeam, scope: "anonymous" },
      { ...sandboxTeam, named_rep_details: false },
      { ...fictionalTeamCoaching, sandbox: true },
    ])
      expect(parseTeamCoaching(raw)).toBeNull();
  });
  it("finds reps by name, current focus or skill, combines filters and resets disclosure", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <TeamCoachingStory coaching={parseTeamCoaching(sandboxTeam)!} />,
      ),
    );
    const select = host.querySelector<HTMLSelectElement>(
      'select[aria-label="Coaching area"]',
    )!;
    expect([...select.options].map((option) => option.textContent)).toEqual([
      "All areas",
      "Closing",
      "Qualification",
    ]);
    let search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
    expect(search.placeholder).toBe("Name or current focus");
    const setQuery = async (value: string) =>
      act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!.call(search, value);
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
    const links = () => [...host.querySelectorAll<HTMLAnchorElement>("li a")];
    const clearFilters = () =>
      [...host.querySelectorAll("button")].find(
        (button) => button.textContent === "Clear filters",
      );
    expect(clearFilters()).toBeUndefined();
    expect(links()).toHaveLength(8);
    expect(links().some((link) => link.textContent?.includes("Asha Rao"))).toBe(
      false,
    );
    await setQuery("  aShA  ");
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Asha Rao");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("1 rep");
    await act(async () => {
      select.value = "qualification";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain(
      "Confirm who decides before the sale",
    );
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[9].person_id}`,
    );
    // A matching result must be just as easy to reset as an empty one.
    expect(clearFilters()).toBeDefined();
    await act(async () => clearFilters()!.click());
    expect(search.value).toBe("");
    expect(select.value).toBe("all");
    expect(document.activeElement).toBe(search);
    expect(links()).toHaveLength(8);
    expect(clearFilters()).toBeUndefined();
    // Search the actual habit, without knowing the rep's name. Existing
    // area filters still intersect it, and history totals do not change.
    const totalsBefore = host.querySelector(
      'ul[aria-label="Coaching areas"]',
    )!.textContent;
    await setQuery("  wHo DeCiDeS  ");
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Asha Rao");
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[9].person_id}`,
    );
    await act(async () => {
      select.value = "closing_decision_management";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(0);
    expect(host.textContent).toContain(
      "Try another name, focus or coaching area.",
    );
    await act(async () => {
      select.value = "qualification";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(1);
    expect(
      host.querySelector('ul[aria-label="Coaching areas"]')!.textContent,
    ).toBe(totalsBefore);
    await act(async () => clearFilters()!.click());
    expect(search.value).toBe("");
    expect(select.value).toBe("all");
    expect(document.activeElement).toBe(search);
    await act(async () => {
      select.value = "qualification";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await setQuery("Closer");
    expect(links()).toHaveLength(0);
    expect(host.querySelector('[role="status"]')?.textContent).toBe("0 reps");
    expect(host.textContent).toContain("No reps match");
    const clear = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Clear filters",
    )!;
    await act(async () => clear.click());
    expect(search.value).toBe("");
    expect(document.activeElement).toBe(search);
    expect(select.value).toBe("all");
    expect(links()).toHaveLength(8);
    const showAll = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Show all 10 people",
    )!;
    await act(async () => showAll.click());
    expect(links()).toHaveLength(10);
    const fewer = () =>
      [...host.querySelectorAll("button")].find(
        (button) => button.textContent === "Show fewer people",
      )!;
    expect(fewer().getAttribute("aria-expanded")).toBe("true");
    expect(fewer().getAttribute("aria-controls")).toBe(
      links()[0].closest("ul")!.parentElement!.id,
    );
    await act(async () => fewer().click());
    expect(links()).toHaveLength(8);
    expect(document.activeElement).toBe(search);
    expect(showAll.getAttribute("aria-expanded")).toBe("false");
    await setQuery("Closer");
    await act(async () => {
      select.value = "closing_decision_management";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const filteredAll = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Show all 9 people",
    )!;
    await act(async () => filteredAll.click());
    expect(links()).toHaveLength(9);
    await act(async () => fewer().click());
    expect(links()).toHaveLength(8);
    expect(search.value).toBe("Closer");
    expect(select.value).toBe("closing_decision_management");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("9 reps");
    expect(document.activeElement).toBe(search);
    await setQuery("Closer 9");
    expect(links()).toHaveLength(1);
    await setQuery("");
    expect(links()).toHaveLength(8);
    const allClosing = () =>
      [...host.querySelectorAll("button")].find(
        (button) => button.textContent === "Show all 9 people",
      )!;
    await act(async () => allClosing().click());
    expect(links()).toHaveLength(9);
    // Clear an area-only match even after its list has been expanded.
    await act(async () => clearFilters()!.click());
    expect(search.value).toBe("");
    expect(select.value).toBe("all");
    expect(links()).toHaveLength(8);
    expect(document.activeElement).toBe(search);
    expect(clearFilters()).toBeUndefined();
    await setQuery("Closer");
    const findArea = (label: string) =>
      host.querySelector<HTMLButtonElement>(
        `button[aria-label="Find reps working on ${label}"]`,
      )!;
    await act(async () => findArea("Qualification").click());
    expect(search.value).toBe("");
    expect(select.value).toBe("qualification");
    expect(document.activeElement).toBe(search);
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Asha Rao");
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[9].person_id}`,
    );
    await setQuery("Asha");
    await act(async () => findArea("Closing & Decision Management").click());
    expect(search.value).toBe("");
    expect(select.value).toBe("closing_decision_management");
    expect(links()).toHaveLength(8);
    expect(host.querySelector('[role="status"]')?.textContent).toBe("9 reps");
    expect(document.activeElement).toBe(search);
    expect(allClosing().getAttribute("aria-expanded")).toBe("false");
    await setQuery("No match");
    expect(links()).toHaveLength(0);
    // Repeating the same area also clears a name filter; the shortcut isn't
    // a remount keyed only to the area.
    await act(async () => findArea("Closing & Decision Management").click());
    expect(search.value).toBe("");
    expect(links()).toHaveLength(8);
    await act(async () =>
      root.render(
        <TeamCoachingStory
          key="one-area"
          coaching={
            parseTeamCoaching({
              ...sandboxTeam,
              suggestions: [sandboxTeam.suggestions[1]],
            })!
          }
        />,
      ),
    );
    // A current skill remains findable even when absent from the historical
    // suggestion totals. Adding its option must not invent a total or action.
    search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
    const currentAreas = host.querySelector<HTMLSelectElement>("select")!;
    expect([...currentAreas.options].map((option) => option.value)).toEqual([
      "all",
      "qualification",
      "closing_decision_management",
    ]);
    const totals = host.querySelector('ul[aria-label="Coaching areas"]')!;
    expect(totals.querySelectorAll("li")).toHaveLength(1);
    expect(totals.textContent).toContain("1 of 3 calls");
    expect(totals.textContent).not.toContain("Closing");
    expect(findArea("Closing & Decision Management")).toBeNull();
    await act(async () => {
      currentAreas.value = "closing_decision_management";
      currentAreas.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(8);
    expect(links().every((link) => link.textContent?.includes("Closer"))).toBe(
      true,
    );
    expect(host.querySelector('[role="status"]')?.textContent).toBe("9 reps");
    await setQuery("  cLoSeR 9  ");
    expect(links()).toHaveLength(1);
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[8].person_id}`,
    );
    await act(async () => clearFilters()!.click());
    expect(search.value).toBe("");
    expect(document.activeElement).toBe(search);
    expect(currentAreas.value).toBe("all");
    expect(links()).toHaveLength(8);
    await act(async () => findArea("Qualification").click());
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Asha Rao");
    // Even one historic area needs All areas once its shortcut hides other
    // current focuses. A successful filter must always be resettable.
    const oneArea = host.querySelector("select")!;
    expect(oneArea.value).toBe("qualification");
    await act(async () => {
      oneArea.value = "all";
      oneArea.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(8);
    // No historical suggestions still permits current-focus filtering, and
    // a rep without a known skill contributes no made-up area.
    await act(async () =>
      root.render(
        <TeamCoachingStory
          key="no-totals"
          coaching={
            parseTeamCoaching({
              ...sandboxTeam,
              suggestions: [],
              reps: [
                sandboxTeam.reps[0],
                { ...sandboxTeam.reps[9], skill_id: null, focus_label: null },
              ],
            })!
          }
        />,
      ),
    );
    search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
    const withoutTotals = host.querySelector<HTMLSelectElement>("select")!;
    expect([...withoutTotals.options].map((option) => option.value)).toEqual([
      "all",
      "closing_decision_management",
      "no-focus",
    ]);
    expect(host.querySelector('ul[aria-label="Coaching areas"]')).toBeNull();
    expect(host.textContent).toContain("No team suggestions yet");
    expect(findArea("Closing & Decision Management")).toBeNull();
    // A missing focus contributes no made-up searchable habit.
    await setQuery("Focus for");
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Closer 1");
    await setQuery("");
    await act(async () => {
      withoutTotals.value = "closing_decision_management";
      withoutTotals.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(1);
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[0].person_id}`,
    );
    await act(async () => clearFilters()!.click());
    expect(withoutTotals.value).toBe("all");
    expect(links()).toHaveLength(2);
    expect(document.activeElement).toBe(
      host.querySelector('input[type="search"]'),
    );
    // Missing focus is inspectable without inventing an area or diagnosis.
    await act(async () => {
      withoutTotals.value = "no-focus";
      withoutTotals.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("Asha Rao");
    expect(links()[0].textContent).toContain("No focus shown");
    expect(links()[0].getAttribute("href")).toBe(
      `/coaching?person=${sandboxTeam.reps[9].person_id}`,
    );
    await setQuery("  aShA  ");
    expect(links()).toHaveLength(1);
    await setQuery("Closer");
    expect(links()).toHaveLength(0);
    await act(async () => clearFilters()!.click());
    expect(withoutTotals.value).toBe("all");
    expect(search.value).toBe("");
    expect(document.activeElement).toBe(search);
    expect(links()).toHaveLength(2);
    // Even an all-missing set has a usable filter. A known area without a
    // focus label remains in that area too; absence isn't a skill judgment.
    await act(async () =>
      root.render(
        <TeamCoachingStory
          key="missing-focus"
          coaching={
            parseTeamCoaching({
              ...sandboxTeam,
              reps: sandboxTeam.reps.map((rep) => ({
                ...rep,
                focus_label: null,
              })),
            })!
          }
        />,
      ),
    );
    const missingSelect = host.querySelector<HTMLSelectElement>("select")!;
    await act(async () => {
      missingSelect.value = "no-focus";
      missingSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(8);
    expect(host.querySelector('[role="status"]')?.textContent).toBe("10 reps");
    const missingAll = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Show all 10 people",
    )!;
    await act(async () => missingAll.click());
    expect(links()).toHaveLength(10);
    await act(async () => {
      missingSelect.value = "qualification";
      missingSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(links()).toHaveLength(1);
    expect(links()[0].textContent).toContain("No focus shown");
    expect(
      host.querySelector('ul[aria-label="Coaching areas"]')!.textContent,
    ).toContain("3 of 3 calls");
    await act(async () => root.unmount());
    host.remove();
  });
  it("reads another rep's coaching only as that rep's view", async () => {
    const person = "00000000-0000-4000-8000-000000000001";
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ ...fictionalCoaching, person_id: person }),
          { headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    expect((await readCoaching(`person:${person}`)).data?.person_id).toBe(
      person,
    );
    expect(fetch.mock.calls[0][0]).toBe(`/v1/me/coaching/people/${person}`);
    // The viewer's own coaching answered for another person is refused.
    fetch.mockResolvedValue(
      new Response(JSON.stringify(fictionalCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    expect((await readCoaching(`person:${person}`)).data).toBeNull();
    expect((await readCoaching("person:not-a-person")).error).toContain(
      "doesn’t work",
    );
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
