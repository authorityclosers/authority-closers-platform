import { expect, it } from "vitest";

import { HUB_TABS } from "../organisation/hub-tabs";
import { areaFor, pageHere, sidebarAreas } from "./sidebar-areas";

const outline = (areas: ReturnType<typeof sidebarAreas>) =>
  areas.map((area) => [
    area.label,
    area.pages.map((page) => [
      page.label,
      ...(page.subs ?? []).map((sub) => sub.label),
    ]),
  ]);

// Owner, dev #8 (26 Oct 2026): a ribbon of areas, a panel of that area's pages.
it("draws a personal workspace's areas: Home, Work and Results", () => {
  expect(
    outline(sidebarAreas({ organisation: false, team: false, manager: false })),
  ).toEqual([
    ["Home", [["Home"]]],
    ["Work", [["Leads"], ["Chats"], ["Calls"], ["Prospects"]]],
    ["Results", [["Reports"], ["Coaching"]]],
  ]);
});

// Orchestrator, 26 Oct 2026: on a computer the panel is the hub's only section
// nav, so Team lists every section, Insights and Plan & billing included.
it("adds Team for an organisation, with every hub section by role", () => {
  const owner = sidebarAreas({
    organisation: true,
    team: true,
    manager: true,
  });
  expect(outline(owner)).toEqual([
    ["Home", [["Home"]]],
    ["Work", [["Leads", "All leads"], ["Chats"], ["Calls"], ["Prospects"]]],
    [
      "Team",
      [
        ["Overview"],
        ["Team"],
        ["Analytics"],
        ["Insights"],
        ["Leads setup"],
        ["Connections"],
        ["AI on calls"],
        ["Company"],
        ["Plan & billing"],
      ],
    ],
    ["Results", [["Reports"], ["Coaching"]]],
  ]);
  const team = owner[2].pages;
  expect(team.map((page) => [page.href, page.hubTab ?? null])).toEqual([
    ["/organisation", "overview"],
    ["/organisation?tab=team", "team"],
    ["/organisation?tab=analytics", "analytics"],
    ["/organisation/insights", null],
    ["/organisation?tab=leads", "leads"],
    ["/organisation?tab=connections", "connections"],
    ["/organisation?tab=call-ai", "call-ai"],
    ["/organisation?tab=company", "company"],
    ["/settings/plan", null],
  ]);
  expect(team[0].name).toBe("Organisation overview");
  // A seller sees the sections everyone may open.
  const seller = sidebarAreas({
    organisation: true,
    team: true,
    manager: false,
  });
  expect(seller[2].pages.map((page) => page.label)).toEqual([
    "Overview",
    "Team",
    "Analytics",
    "Company",
  ]);
  // On the hub outside an organisation: its overview only.
  expect(
    sidebarAreas({ organisation: false, team: true, manager: false })[2].pages,
  ).toHaveLength(1);
});

it("lists the hub's sections as the hub does, in its order", () => {
  expect(
    sidebarAreas({
      organisation: true,
      team: true,
      manager: true,
    })[2].pages.map((page) => [page.label, page.icon]),
  ).toEqual(HUB_TABS.map((tab) => [tab.label, tab.icon]));
});

it("puts each place in its area, and lights Reports apart from Home", () => {
  expect(areaFor("dashboard", false)).toBe("home");
  expect(areaFor("dashboard", true)).toBe("results");
  for (const place of ["leads", "chats", "calls", "prospects", "analyse"])
    expect(areaFor(place, false)).toBe("work");
  for (const place of ["organisation", "insights"])
    expect(areaFor(place, false)).toBe("team");
  for (const place of ["coaching", "review"])
    expect(areaFor(place, false)).toBe("results");
  expect(areaFor("account", false)).toBeNull();
  expect(pageHere("reports", "dashboard", true)).toBe(true);
  expect(pageHere("dashboard", "dashboard", true)).toBe(false);
  expect(pageHere("dashboard", "dashboard", false)).toBe(true);
  expect(pageHere("calls", "calls", false)).toBe(true);
});

it("lights a hub section by the tab the hub shows", () => {
  const here = (section: string, place: string, tab: string | null) =>
    pageHere("", place, false, { section, tab });
  expect(here("overview", "organisation", null)).toBe(true);
  expect(here("overview", "organisation", "team")).toBe(false);
  expect(here("team", "organisation", "team")).toBe(true);
  expect(here("team", "insights", "team")).toBe(false);
});
