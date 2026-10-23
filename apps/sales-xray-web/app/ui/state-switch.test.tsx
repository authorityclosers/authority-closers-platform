import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StateSwitch, type StateSwitchProps } from "./state-switch";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const props = (extra: Partial<StateSwitchProps> = {}): StateSwitchProps => ({
  icon: null,
  label: "Taking new leads",
  meaning: "While this is on, the lead rules can give you new leads.",
  onText: "On: you're receiving new leads",
  offText: "Off: new leads go to others",
  chipOn: "Taking leads",
  chipOff: "Not taking leads",
  on: true,
  confirmOff: {
    title: "Stop taking new leads?",
    points: [
      "New leads go to other sellers.",
      "Your open leads stay with you.",
    ],
    confirm: "Stop taking leads",
    keep: "Keep taking leads",
  },
  onChange: vi.fn(async () => undefined),
  ...extra,
});

const render = async (value: StateSwitchProps) => {
  await act(async () => root.render(<StateSwitch {...value} />));
};
const knob = () =>
  host.querySelector<HTMLButtonElement>('button[role="switch"]')!;
const sheetText = () => document.querySelector("dialog")?.textContent ?? "";
const press = async (button: HTMLElement) => {
  await act(async () => button.click());
};
const buttonNamed = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("dialog button")].find(
    (button) => button.textContent === name,
  )!;

it("says the state in words, on, off and paused", async () => {
  await render(props());
  expect(host.textContent).toContain("On: you're receiving new leads");
  expect(knob().getAttribute("aria-checked")).toBe("true");

  await render(props({ on: false }));
  expect(host.textContent).toContain("Off: new leads go to others");
  expect(knob().getAttribute("aria-checked")).toBe("false");

  await render(
    props({
      hold: {
        title: "Paused for work hours",
        reason: "New leads wait until tomorrow 9:00 AM.",
        chip: "Paused, after hours",
        who: "Your owner or admin sets work hours.",
      },
    }),
  );
  expect(host.textContent).toContain("Paused for work hours");
  expect(host.textContent).toContain("New leads wait until tomorrow 9:00 AM.");
  expect(host.textContent).toContain("Your owner or admin sets work hours.");
});

it("adds a detail under the state while it runs", async () => {
  await render(props({ note: "Jio · checked 2 min ago" }));
  expect(host.textContent).toContain("Jio · checked 2 min ago");
  await render(props({ on: false, note: "Jio · checked 2 min ago" }));
  expect(host.textContent).not.toContain("Jio · checked 2 min ago");
});

it("asks before turning off, and saves only on the answer", async () => {
  const value = props();
  await render(value);
  await press(knob());
  expect(value.onChange).not.toHaveBeenCalled();
  expect(sheetText()).toContain("Stop taking new leads?");
  expect(sheetText()).toContain("Your open leads stay with you.");

  await press(buttonNamed("Keep taking leads"));
  expect(value.onChange).not.toHaveBeenCalled();

  await press(knob());
  await press(buttonNamed("Stop taking leads"));
  expect(value.onChange).toHaveBeenCalledWith(false);
});

it("turns back on at once, without a question", async () => {
  const value = props({ on: false });
  await render(value);
  await press(knob());
  expect(value.onChange).toHaveBeenCalledWith(true);
  expect(sheetText()).not.toContain("Stop taking new leads?");
});

it("never flips from the chip: it opens the switch in a sheet", async () => {
  const value = props({ place: "chip" });
  await render(value);
  const chip = host.querySelector<HTMLButtonElement>("button")!;
  expect(chip.textContent).toBe("Taking leads");
  expect(chip.getAttribute("aria-haspopup")).toBe("dialog");
  await press(chip);
  expect(value.onChange).not.toHaveBeenCalled();
  expect(sheetText()).toContain(
    "While this is on, the lead rules can give you new leads.",
  );
  expect(document.querySelector('dialog button[role="switch"]')).not.toBeNull();
});

it("offers the override behind its own question", async () => {
  const run = vi.fn(async () => undefined);
  await render(
    props({
      hold: {
        title: "Paused for work hours",
        reason: "New leads wait until tomorrow 9:00 AM.",
        chip: "Paused, after hours",
        override: {
          label: "Hand out leads after hours",
          confirm: {
            title: "Hand out new leads after hours?",
            points: ["This changes work hours for the whole team."],
            confirm: "Hand out leads now",
            keep: "Keep the pause",
          },
          run,
        },
      },
    }),
  );
  const open = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Hand out leads after hours",
  )!;
  await press(open);
  expect(run).not.toHaveBeenCalled();
  expect(sheetText()).toContain("This changes work hours for the whole team.");
  await press(buttonNamed("Hand out leads now"));
  expect(run).toHaveBeenCalledOnce();
});
