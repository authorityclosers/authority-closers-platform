// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ListView, TEST } from "./list-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));

// The ease-of-use wave #9, 22 Oct 2026: every empty list has one way on.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () =>
      Response.json({
        schema: "lead-desk/1",
        leads: [],
        total: 0,
        next_offset: null,
      }),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function empty(
  stage: string,
  stageLabel: string,
  query = "",
  filtered = false,
) {
  const calls = { clear: vi.fn(), add: vi.fn(), open: vi.fn() };
  await act(async () =>
    root.render(
      <ListView
        canManage
        stage={stage}
        stageLabel={stageLabel}
        scope="team"
        query={query}
        onOpen={() => undefined}
        version={0}
        filtered={filtered}
        onClearFilters={calls.clear}
        onAdd={calls.add}
        onShowOpen={calls.open}
      />,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  const buttons = [...host.querySelectorAll('[role="status"] button')];
  expect(buttons).toHaveLength(1);
  return { calls, button: buttons[0] as HTMLButtonElement };
}

it("a search with no match clears it", async () => {
  const { calls, button } = await empty("open", "Open", "pune");
  expect(host.textContent).toContain("No leads match");
  expect(button.textContent).toBe("Clear filters");
  await act(async () => button.click());
  expect(calls.clear).toHaveBeenCalledTimes(1);
});

it("whose leads, picked, with nobody there clears it too", async () => {
  const { button } = await empty("interested", "Interested", "", true);
  expect(host.textContent).toContain("Nobody here for whose leads you picked.");
  expect(button.textContent).toBe("Clear filters");
});

it("an empty Open list adds a lead", async () => {
  const { calls, button } = await empty("open", "Open");
  expect(host.textContent).toContain("No leads yet");
  expect(button.textContent).toBe("Add lead");
  await act(async () => button.click());
  expect(calls.add).toHaveBeenCalledTimes(1);
});

it("an empty stage, or no test leads, goes back to the open leads", async () => {
  const { calls, button } = await empty("interested", "Site visit booked");
  expect(host.textContent).toContain("No leads in Site visit booked");
  expect(button.textContent).toBe("See open leads");
  await act(async () => button.click());
  expect(calls.open).toHaveBeenCalledTimes(1);
  const test = await empty(TEST, "Test leads");
  expect(test.button.textContent).toBe("See open leads");
});
