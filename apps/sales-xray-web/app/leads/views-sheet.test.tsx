// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Notice = {
  title?: string;
  tone?: string;
  action?: { label: string; run: () => void };
};
const notices = vi.hoisted(() => [] as Notice[]);
vi.mock("../notice-center", () => ({
  notify: (notice: Notice) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import type { SavedView, ViewSpec } from "./saved-views";
import { ViewsChip } from "./views-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The ease-of-use wave #8, 22 Oct 2026: Leads → Views.
const OWNER = "person-1:tenant-1";
const STORE = `sx.leads.views.v1:${OWNER}`;
const PUNE: ViewSpec = {
  stage: "open",
  pipeline: null,
  who: "mine",
  q: "pune",
};
const describe = (spec: ViewSpec) =>
  [spec.stage === "open" ? "Open" : "Interested", spec.q && `“${spec.q}”`]
    .filter(Boolean)
    .join(" · ");

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.length = 0;
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  window.localStorage.clear();
});

const press = (text: string) =>
  [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(text),
  )!;
const stored = (): SavedView[] =>
  JSON.parse(window.localStorage.getItem(STORE) ?? "[]");

async function show(current: ViewSpec, onApply = vi.fn()) {
  await act(async () =>
    root.render(
      <ViewsChip
        owner={OWNER}
        current={current}
        describe={describe}
        onApply={onApply}
      />,
    ),
  );
  return onApply;
}

it("saves the view in use under a name, and the chip then names it", async () => {
  await show(PUNE);
  expect(press("Views").getAttribute("aria-label")).toBe("Saved views");
  await act(async () => press("Views").click());
  const name = document.querySelector<HTMLInputElement>("input")!;
  // The name starts as the view in words.
  expect(name.value).toBe("Open · “pune”");
  expect(document.body.textContent).toContain("Save the stage, pipeline");
  await act(async () => press("Save this view").click());
  expect(stored()).toMatchObject([
    { name: "Open · “pune”", stage: "open", who: "mine", q: "pune" },
  ]);
  expect(notices.at(-1)).toMatchObject({ tone: "success" });
  const chip = document.querySelector("button[data-view]");
  expect(chip?.getAttribute("aria-label")).toBe("Saved view: Open · “pune”");
});

it("opens a saved view in one tap, and a removal can be undone", async () => {
  const hot: SavedView = {
    id: "v-hot",
    name: "Hot leads",
    stage: "interested",
    pipeline: null,
    who: "team",
    q: "",
  };
  window.localStorage.setItem(STORE, JSON.stringify([hot]));
  const onApply = await show(PUNE);
  await act(async () => press("Views").click());
  expect(document.body.textContent).toContain("Hot leads");
  await act(async () => press("Hot leads").click());
  expect(onApply).toHaveBeenCalledWith(hot);

  await act(async () => press("Views").click());
  const remove = document.querySelector<HTMLButtonElement>(
    'button[aria-label="Remove Hot leads"]',
  )!;
  await act(async () => remove.click());
  expect(stored()).toEqual([]);
  const undo = notices.at(-1)!;
  expect(undo.title).toBe("Removed “Hot leads”");
  await act(async () => undo.action!.run());
  expect(stored()).toEqual([hot]);
});

it("offers no second save of a view already saved", async () => {
  window.localStorage.setItem(
    STORE,
    JSON.stringify([{ id: "v-1", name: "Pune", ...PUNE, q: "Pune" }]),
  );
  await show(PUNE);
  await act(async () => press("Pune").click());
  expect(document.body.textContent).toContain("This is your saved view Pune");
  expect(press("Save this view")).toBeUndefined();
});
