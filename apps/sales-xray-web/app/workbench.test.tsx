import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Workbench } from "./workbench";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const caps = {
  product: "Sales Xray",
  intake: "unavailable",
  provider_processing: "disabled",
  numeric_publication: "withheld",
  reasons: [],
};
const example = {
  id: "synthetic-example",
  title: "Synthetic conversation",
  duration_ms: 20000,
  state: "example",
  transcript: {
    revision: "script-1",
    segments: [
      {
        id: "a",
        speaker_id: "seller",
        start_ms: 0,
        end_ms: 10000,
        text: "नमस्ते <img src=x onerror=alert(1)>",
      },
      {
        id: "b",
        speaker_id: "prospect",
        start_ms: 10000,
        end_ms: 20000,
        text: "What about the price?",
      },
    ],
  },
  measurements: {},
  profile: {
    name: "Dipak draft",
    declared_total: 100,
    source_total: 95,
    numeric_score: null,
  },
};
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.endsWith("capabilities") ? caps : example),
    })),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function render() {
  await act(async () => root.render(<Workbench />));
}
function button(text: string) {
  const found = [...container.querySelectorAll("button")].find((v) =>
    v.textContent?.includes(text),
  );
  if (!found) throw new Error(`Missing button ${text}`);
  return found;
}
it("renders literal Unicode evidence, with no HTML execution or numeric score", async () => {
  await render();
  expect(container.textContent).toContain(
    "नमस्ते <img src=x onerror=alert(1)>",
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain("No published score");
  expect(container.textContent).toContain("SYNTHETIC EXAMPLE");
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("offers retry on a real service failure without silently replacing it with fabricated analysis", async () => {
  vi.mocked(fetch).mockRejectedValue(new Error("Service unavailable"));
  await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Service unavailable",
  );
  expect(button("Retry service")).toBeDefined();
  expect(container.textContent).not.toContain("Synthetic conversation");
});
it("keeps unsubmitted review lanes distinct and requires evidence before preparing a proposal", async () => {
  await render();
  await act(async () => button("Review notes").click());
  expect(container.querySelector('[aria-label="Review lane"]')).not.toBeNull();
  expect(button("Prepare local proposal").disabled).toBe(true);
  await act(async () => button("Measurement & attribution").click());
  expect(button("Measurement & attribution").getAttribute("aria-pressed")).toBe(
    "true",
  );
  expect(button("Sales context").getAttribute("aria-pressed")).toBe("false");
  expect(container.textContent).toContain(
    "Authenticated submission is unavailable",
  );
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("keeps the original profile discrepancy visible in evidence", async () => {
  await render();
  await act(async () => button("Source & evidence").click());
  expect(container.querySelector(".weight-comparison")?.textContent).toContain(
    "95Source total≠100Declared total",
  );
  expect(container.textContent).toContain("Ethics is a hard constraint");
});
it("changes appearance without persisting conversation data", async () => {
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  await render();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        '[aria-label="Switch to dark appearance"]',
      )!
      .click(),
  );
  expect(container.querySelector(".xray-app")?.getAttribute("data-theme")).toBe(
    "dark",
  );
  expect(setItem).not.toHaveBeenCalled();
});
