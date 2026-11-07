import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { SlotLayout, slotPlan, withoutSlots } from "./slot-layout";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const slots = () =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-area]"), (slot) => [
    slot.dataset.area,
    slot.textContent,
  ]);

const PLAN = slotPlan(["finish", "scope", "counts", "next"], {
  wide: { counts: 7, next: 5 },
});

it("draws the blocks in the plan's order, whatever order they come in", () => {
  act(() =>
    root.render(
      <SlotLayout
        plan={PLAN}
        blocks={{ next: "Call", counts: "6 new", scope: "Inbound" }}
      />,
    ),
  );
  expect(slots()).toEqual([
    ["scope", "Inbound"],
    ["counts", "6 new"],
    ["next", "Call"],
  ]);
});

it("leaves no room for a block with nothing to say", () => {
  act(() =>
    root.render(
      <SlotLayout
        plan={PLAN}
        blocks={{ finish: null, scope: false, counts: "6 new" }}
      />,
    ),
  );
  expect(slots()).toEqual([["counts", "6 new"]]);
});

it("takes a block out by plan, not by rewriting the screen", () => {
  act(() =>
    root.render(
      <SlotLayout
        plan={withoutSlots(PLAN, "scope")}
        blocks={{ scope: "Inbound", counts: "6 new", next: "Call" }}
      />,
    ),
  );
  expect(slots().map(([slot]) => slot)).toEqual(["counts", "next"]);
});

it("gives each slot its columns on a computer, and the rest the whole row", () => {
  act(() =>
    root.render(
      <SlotLayout plan={PLAN} blocks={{ scope: "Inbound", counts: "6 new" }} />,
    ),
  );
  const [scope, counts] = Array.from(
    host.querySelectorAll<HTMLElement>("[data-area]"),
  );
  expect(scope.style.getPropertyValue("--span")).toBe("");
  expect(counts.style.getPropertyValue("--span")).toBe("7");
});
