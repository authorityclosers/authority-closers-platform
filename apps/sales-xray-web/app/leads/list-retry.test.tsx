// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ListView } from "./list-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));

// Report #27, 26 Oct 2026: a list that didn't load says so calmly, and tries again.
let host: HTMLDivElement;
let root: Root;
let down: boolean;
beforeEach(() => {
  down = true;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => {
      if (down) throw new TypeError("Failed to fetch");
      return Response.json({
        schema: "lead-desk/1",
        leads: [],
        total: 0,
        next_offset: null,
      });
    }),
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

const settle = () =>
  act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });

it("a list that didn't load offers Try again, which asks once more", async () => {
  await act(async () =>
    root.render(
      <ListView
        canManage
        stage="open"
        stageLabel="Open"
        scope="team"
        query=""
        onOpen={() => undefined}
        version={0}
        onAdd={() => undefined}
      />,
    ),
  );
  await settle();
  const status = host.querySelector('[role="status"]');
  expect(status?.textContent).toContain("Sales X-Ray isn't answering");
  expect(status?.textContent).toContain("Your leads are safe.");
  expect(host.querySelector('[role="alert"]')).toBeNull();
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  );
  expect(retry).toBeDefined();

  down = false;
  await act(async () => retry!.click());
  await settle();
  expect(host.textContent).not.toContain("Your leads are safe.");
  expect(host.textContent).toContain("No leads yet");
});
