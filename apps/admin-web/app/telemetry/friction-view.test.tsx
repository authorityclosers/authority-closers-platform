// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { frictionFixture } from "../review-fixture/telemetry-friction/friction-fixture";
import {
  frictionQuery,
  normalizeFriction,
  peopleWords,
  recentWeeks,
  weekWords,
  zoneWords,
} from "./friction-data";
import { FrictionView } from "./friction-view";

const NOW = new Date("2026-10-26T06:00:00Z");

const host = (markup: string) => {
  const element = document.createElement("div");
  element.innerHTML = markup;
  return element;
};

it("reads the week asked for, or the last full one, and offers the markdown", () => {
  expect(frictionQuery({})).toEqual({
    week: null,
    path: "/v1/admin/telemetry/friction",
    markdown: "/v1/admin/telemetry/friction?format=markdown",
  });
  expect(frictionQuery({ week: "2026-10-19" })).toEqual({
    week: "2026-10-19",
    path: "/v1/admin/telemetry/friction?week=2026-10-19",
    markdown: "/v1/admin/telemetry/friction?week=2026-10-19&format=markdown",
  });
  expect(frictionQuery({ week: "last week" }).week).toBeNull();
  // Monday 26 Oct, 11:30 IST: this week, then the five before it.
  expect(recentWeeks(NOW)).toEqual([
    "2026-10-26",
    "2026-10-19",
    "2026-10-12",
    "2026-10-05",
    "2026-09-28",
    "2026-09-21",
  ]);
  // Sunday 25 Oct, 23:00 IST is still the week of 19 Oct in India.
  expect(recentWeeks(new Date("2026-10-25T17:30:00Z"))[0]).toBe("2026-10-19");
  expect(weekWords("2026-10-19")).toBe("19 Oct");
  expect(zoneWords("r1c3")).toBe("top right");
  expect(peopleWords("<3")).toBe("fewer than 3 people");
  expect(peopleWords(1)).toBe("1 person");
});

it("keeps fewer than three people unnumbered and reads every part", () => {
  const friction = normalizeFriction(frictionFixture(NOW));
  expect(friction.available).toBe(true);
  expect(friction.findings[0]).toMatchObject({
    rank: 1,
    key: "flow_quit:onboarding:business",
    severity: 4,
    people: 9,
    peopleBefore: 6,
    isNew: false,
  });
  const rage = friction.findings.find((item) => item.kind === "rage_tap")!;
  expect(rage.evidence).toContainEqual([
    "where on screen",
    "upper middle right, upper middle centre",
  ]);
  expect(friction.permissions[3].people).toBe("<3");
  expect(friction.flows[0].worstStep).toBe("business");
  expect(friction.workspaces.directions).toEqual([
    ["personal_to_organisation", 38],
    ["organisation_to_personal", 26],
  ]);
  expect(normalizeFriction({}).available).toBe(false);
});

it("shows what to fix first with the question to answer, flows, prompts and switching", () => {
  const page = host(
    renderToStaticMarkup(
      <FrictionView
        friction={normalizeFriction(frictionFixture(NOW))}
        markdownHref="/v1/admin/telemetry/friction?format=markdown"
      />,
    ),
  );
  const text = page.textContent ?? "";
  expect(text).toContain("What to fix first");
  expect(text).toContain("First-run setup: people stop at “What you sell”");
  expect(text).toContain("Ask: Why stop here");
  expect(text).toContain("First-run setup: 33% finish");
  expect(text).toContain("9 stopped");
  expect(text).toContain("Permission prompts in phone setup");
  expect(text).toContain("Straight back");
  expect(text).toContain("Screens by friction");
  expect(text).toContain("Gone since the week before");
  expect(page.querySelector("a[download]")?.getAttribute("href")).toBe(
    "/v1/admin/telemetry/friction?format=markdown",
  );
  const empty = host(
    renderToStaticMarkup(
      <FrictionView
        friction={normalizeFriction(frictionFixture(NOW, "empty"))}
      />,
    ),
  );
  expect(empty.textContent).toContain("Nothing reached the bar this week");
  expect(empty.textContent).toContain("No flow events yet");
  const missing = host(
    renderToStaticMarkup(<FrictionView friction={normalizeFriction(null)} />),
  );
  expect(missing.textContent).toContain("doesn’t have the friction report yet");
});
