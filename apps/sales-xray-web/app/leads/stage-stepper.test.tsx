// v1.96 device polish (the owner's device tests, 360-430 px): on a phone the
// stage strip is the step before, the current one and the next, so a name is
// never cut at the card's edge ("Meetin… schedu…").
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { StageStepper } from "./stage-stepper";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const STEPS = [
  { key: "new", label: "New lead" },
  { key: "open", label: "Open" },
  { key: "interested", label: "Interested" },
  { key: "meeting", label: "Meeting scheduled" },
  { key: "done", label: "Meeting done" },
  { key: "won", label: "Won" },
];

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const show = async (current: string) => {
  await act(async () =>
    root.render(
      <StageStepper
        steps={STEPS}
        current={current}
        movable={new Set()}
        onPick={() => undefined}
      />,
    ),
  );
  return [...host.querySelectorAll("li")].map((item) =>
    item.hasAttribute("data-far")
      ? "-"
      : `${item.textContent}${item.dataset.more ? `(${item.dataset.more})` : ""}`,
  );
};

it("keeps the step before, the current one and the next on a phone", async () => {
  expect(await show("interested")).toEqual([
    "-",
    "Open(before)",
    "Interested",
    "Meeting scheduled(after)",
    "-",
    "-",
  ]);
  // At an end of the path: its first three, or its last three.
  expect(await show("new")).toEqual([
    "New lead",
    "Open",
    "Interested(after)",
    "-",
    "-",
    "-",
  ]);
  expect(await show("won")).toEqual([
    "-",
    "-",
    "-",
    "Meeting scheduled(before)",
    "Meeting done",
    "Won",
  ]);
  const style = host.querySelector("ol")!.getAttribute("style") ?? "";
  expect(style).toContain("--step-count: 6");
  expect(style).toContain("--step-near: 3");
});

it("hides the far steps only on a phone", () => {
  const css = readFileSync(
    join(process.cwd(), "app/leads/lead-page.module.css"),
    "utf8",
  );
  const phone = css.slice(css.indexOf("v1.96 device polish: on a phone"));
  expect(phone).toMatch(
    /@media \(max-width: 599\.98px\) \{[\s\S]*?\.stepper > \.step\[data-far\] \{\s*display: none;/,
  );
});
