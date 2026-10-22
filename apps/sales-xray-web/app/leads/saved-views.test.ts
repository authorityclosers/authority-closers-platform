// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

import {
  asScope,
  findView,
  NAME_LIMIT,
  parseViews,
  sameView,
  VIEWS_LIMIT,
  withoutView,
  withView,
  writeViews,
  type SavedView,
  type ViewSpec,
} from "./saved-views";

// The ease-of-use wave #8, 22 Oct 2026: saved views on Leads, on this device first.
const OPEN_MINE: ViewSpec = {
  stage: "open",
  pipeline: null,
  who: "mine",
  q: "",
};

const view = (
  id: string,
  name: string,
  spec: Partial<ViewSpec> = {},
): SavedView => ({
  ...OPEN_MINE,
  ...spec,
  id,
  name,
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

it("reads only well-formed views, never throws on junk", () => {
  expect(parseViews("")).toEqual([]);
  expect(parseViews("{not json")).toEqual([]);
  expect(parseViews(JSON.stringify({ a: 1 }))).toEqual([]);
  const good = view("a", "Pune follow-ups", { q: "pune" });
  expect(
    parseViews(
      JSON.stringify([
        good,
        { ...good, id: "b", who: "everyone" },
        { ...good, id: "c", name: "  " },
        { ...good, id: "d", pipeline: 3 },
      ]),
    ),
  ).toEqual([good]);
  const many = Array.from({ length: VIEWS_LIMIT + 3 }, (_, index) =>
    view(`v${index}`, `View ${index}`),
  );
  expect(parseViews(JSON.stringify(many))).toHaveLength(VIEWS_LIMIT);
});

it("matches a view whatever the search's case or spaces", () => {
  const saved = view("a", "Pune", { q: "Pune" });
  expect(sameView(saved, { ...OPEN_MINE, q: " pune " })).toBe(true);
  expect(sameView(saved, { ...OPEN_MINE, q: "pune", who: "team" })).toBe(false);
  expect(
    sameView(saved, { ...OPEN_MINE, q: "pune", pipeline: "partner" }),
  ).toBe(false);
  expect(findView([saved], { ...OPEN_MINE, q: "PUNE" })).toBe(saved);
  expect(findView([saved], OPEN_MINE)).toBeNull();
});

it("saves under a name, replacing one of the same name where it stood", () => {
  const first = view("a", "Hot", { stage: "interested" });
  const second = view("b", "Pune", { q: "pune" });
  const next = withView(
    [first, second],
    { ...OPEN_MINE, q: " nashik " },
    " hot ",
    "c",
  );
  expect(next.map((item) => item.id)).toEqual(["c", "b"]);
  expect(next[0]).toMatchObject({ name: "hot", q: "nashik", stage: "open" });
  const long = withView([], OPEN_MINE, "x".repeat(NAME_LIMIT + 10), "d");
  expect(long[0].name).toHaveLength(NAME_LIMIT);
  expect(withoutView(next, "c").map((item) => item.id)).toEqual(["b"]);
});

it("says so when the browser keeps nothing", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("QuotaExceededError");
  });
  expect(writeViews("p:t", [view("a", "Hot")])).toBe(false);
});

it("takes whose leads from the address only when it is a real choice", () => {
  expect(asScope("mine")).toBe("mine");
  expect(asScope("unassigned")).toBe("unassigned");
  expect(asScope("everyone")).toBeNull();
  expect(asScope(null)).toBeNull();
});
