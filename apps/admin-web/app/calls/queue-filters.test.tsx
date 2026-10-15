// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { normalizeQueue } from "./call-data";
import { QueueFilters } from "./queue-filters";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/calls",
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  push.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const facets = normalizeQueue({
  facets: { prompts: [{ value: "coaching-v5", count: 4 }] },
}).facets;

it("counts chosen filters on the phone toggle, which opens and closes them", async () => {
  await act(async () =>
    root.render(
      <QueueFilters
        filters={{ review: "new", prompt: "coaching-v5", language: "en" }}
        facets={facets}
      />,
    ),
  );
  const toggle = host.querySelector("button[aria-expanded]")!;
  // The review tab isn't a filter here; prompt and language are.
  expect(toggle.textContent).toBe("Filters · 2");
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  await act(async () => (toggle as HTMLButtonElement).click());
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(
    host.querySelector("[data-shown]")?.querySelector('[role="group"]'),
  ).toBeTruthy();
});

it("chooses a prompt version through the address, dropping the page cursor", async () => {
  await act(async () =>
    root.render(
      <QueueFilters filters={{ cursor: "bzo1MA" }} facets={facets} />,
    ),
  );
  expect(host.querySelector("button[aria-expanded]")?.textContent).toBe(
    "Filters",
  );
  const prompt = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Prompt"]',
  )!;
  expect([...prompt.options].map((option) => option.textContent)).toEqual([
    "Prompt: all",
    "coaching-v5 (4)",
  ]);
  await act(async () => {
    prompt.value = "coaching-v5";
    prompt.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(push).toHaveBeenCalledWith("/calls?prompt=coaching-v5", {
    scroll: false,
  });
});
