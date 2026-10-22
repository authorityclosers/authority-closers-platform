import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  COMMAND_SEARCH_DELAY_MS,
  CommandBar,
  matchCommands,
  type Command,
} from "./command-bar";

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
  vi.useRealTimers();
});

const command = (
  label: string,
  group = "Go to",
  extra: Partial<Command> = {},
): Command => ({
  id: label,
  group,
  label,
  icon: null,
  run: vi.fn(),
  ...extra,
});

it("finds commands by any word, a label's own start first", () => {
  const home = command("Home", "Go to", { keywords: "dashboard sales" });
  const leads = command("Leads");
  const add = command("Add a lead", "Actions");
  expect(matchCommands([home, leads, add], "").map((c) => c.id)).toEqual([
    "Home",
    "Leads",
    "Add a lead",
  ]);
  expect(matchCommands([home, leads, add], "dash").map((c) => c.id)).toEqual([
    "Home",
  ]);
  // "Leads" starts with the word; "Add a lead" only contains it.
  expect(matchCommands([add, leads], "LEAD").map((c) => c.id)).toEqual([
    "Leads",
    "Add a lead",
  ]);
  expect(matchCommands([home, leads], "nothing here")).toEqual([]);
});

async function render(
  commands: Command[],
  search?: (text: string, signal: AbortSignal) => Promise<Command[]>,
) {
  const onClose = vi.fn();
  await act(async () =>
    root.render(
      <CommandBar open onClose={onClose} commands={commands} search={search} />,
    ),
  );
  const input = document.querySelector<HTMLInputElement>(
    'input[role="combobox"]',
  )!;
  const type = async (value: string) =>
    act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  const press = async (key: string) =>
    act(async () => {
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
      );
    });
  const options = () =>
    [...document.querySelectorAll<HTMLElement>('[role="option"]')].map(
      (option) => option.textContent,
    );
  return { onClose, input, type, press, options };
}

it("lists places and actions, filters as you type, and opens with Enter", async () => {
  const home = command("Home");
  const chats = command("Chats");
  const add = command("Add a lead", "Actions");
  const bar = await render([home, chats, add]);
  expect(bar.options()).toEqual(["Home", "Chats", "Add a lead"]);
  expect(
    [...document.querySelectorAll('[role="group"]')].map((group) =>
      group.getAttribute("aria-label"),
    ),
  ).toEqual(["Go to", "Actions"]);
  await bar.type("ch");
  expect(bar.options()).toEqual(["Chats"]);
  await bar.press("Enter");
  expect(chats.run).toHaveBeenCalledTimes(1);
  expect(bar.onClose).toHaveBeenCalledTimes(1);
});

it("moves through the results with the arrow keys, round the ends", async () => {
  const one = command("One");
  const two = command("Two");
  const bar = await render([one, two]);
  const selected = () =>
    document.querySelector('[role="option"][aria-selected="true"]')
      ?.textContent;
  expect(selected()).toBe("One");
  await bar.press("ArrowDown");
  expect(selected()).toBe("Two");
  expect(bar.input.getAttribute("aria-activedescendant")).toBe(
    document.querySelector('[role="option"][aria-selected="true"]')?.id,
  );
  await bar.press("ArrowDown");
  expect(selected()).toBe("One");
  await bar.press("ArrowUp");
  await bar.press("Enter");
  expect(two.run).toHaveBeenCalledTimes(1);
});

it("asks for leads after a short pause, from two letters, and adds them", async () => {
  vi.useFakeTimers();
  const asha = command("Asha Fictional", "Leads", { hint: "New · Pune" });
  const search = vi.fn(async (text: string) =>
    text.startsWith("a") ? [asha] : [],
  );
  const bar = await render([command("Home")], search);
  await bar.type("a");
  await act(async () => vi.advanceTimersByTime(COMMAND_SEARCH_DELAY_MS));
  expect(search).not.toHaveBeenCalled();
  await bar.type("as");
  await act(async () => vi.advanceTimersByTime(COMMAND_SEARCH_DELAY_MS - 1));
  expect(search).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTime(1));
  expect(search).toHaveBeenCalledWith("as", expect.any(AbortSignal));
  expect(bar.options()).toEqual(["Asha FictionalNew · Pune"]);
  await bar.type("zz");
  await act(async () => vi.advanceTimersByTime(COMMAND_SEARCH_DELAY_MS));
  expect(document.body.textContent).toContain("Nothing matches “zz”");
});
